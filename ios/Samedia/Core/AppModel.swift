import Foundation
import Observation
import SwiftUI

/// App state: which server, which profile, and what the screens show.
@MainActor
@Observable
final class AppModel {
    enum Stage { case connect, profiles, main }

    var stage: Stage = .connect
    var api: APIClient?
    var info: ServerInfo?
    var profiles: [Profile] = []
    var profile: Profile?
    var needsPin = false
    var busy = false
    var error: String?
    /// Bumped when what the screens show may have changed (after playback, watched marks...).
    var refreshToken = 0
    let player = PlayerCoordinator()
    let remote = RemoteLink()
    /// A short message shown at the bottom of the screen.
    var toast: String?

    private let defaults = UserDefaults.standard

    init() {
        guard let saved = defaults.string(forKey: "server"), let url = URL(string: saved) else { return }
        api = APIClient(base: url, token: defaults.string(forKey: "token") ?? "")
        if let data = defaults.data(forKey: "profile"), let p = try? JSONDecoder().decode(Profile.self, from: data) {
            profile = p
            api?.profileID = p.id
        }
        stage = .profiles
        Task { await reconnect() }
    }

    /// Back to a saved server on launch: straight to the last profile when it is still offered.
    func reconnect() async {
        guard let api else { stage = .connect; return }
        busy = true
        defer { busy = false }
        do {
            info = try await api.get("/api/v1/info", as: ServerInfo.self)
            try await loadProfiles()
            if let p = profile, let current = profiles.first(where: { $0.id == p.id }) {
                select(current)
            } else if profiles.count == 1 {
                select(profiles[0])
            } else {
                stage = .profiles
            }
        } catch {
            self.error = error.localizedDescription
            stage = .connect
        }
    }

    /// "nasos.local", "192.168.1.20" or a full URL -> http://host:8097
    static func normalize(_ text: String) -> URL? {
        var s = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !s.isEmpty else { return nil }
        if !s.contains("://") { s = "http://" + s }
        guard var c = URLComponents(string: s), c.host != nil else { return nil }
        if c.port == nil { c.port = 8097 }
        c.path = ""
        return c.url
    }

    func connect(to url: URL) async {
        busy = true
        error = nil
        defer { busy = false }
        let client = APIClient(base: url)
        do {
            let info = try await client.get("/api/v1/info", as: ServerInfo.self)
            self.info = info
            api = client
            defaults.set(url.absoluteString, forKey: "server")
            defaults.removeObject(forKey: "token")
            defaults.removeObject(forKey: "profile")
            profile = nil
            if info.pinRequired {
                needsPin = true
                return
            }
            try await loadProfiles()
            if profiles.count == 1 { select(profiles[0]) } else { stage = .profiles }
        } catch {
            self.error = "That doesn't look like a Samedia server: \(error.localizedDescription)"
        }
    }

    func pair(pin: String) async {
        guard let api else { return }
        busy = true
        error = nil
        defer { busy = false }
        struct Pair: Decodable { let token: String }
        do {
            let reply = try await api.post("/api/v1/auth", ["pin": pin], as: Pair.self)
            api.token = reply.token
            defaults.set(reply.token, forKey: "token")
            needsPin = false
            try await loadProfiles()
            if profiles.count == 1 { select(profiles[0]) } else { stage = .profiles }
        } catch {
            self.error = error.localizedDescription
        }
    }

    func loadProfiles() async throws {
        guard let api else { return }
        profiles = try await api.get("/api/v1/profiles", as: ProfilesResponse.self).profiles
    }

    func select(_ p: Profile) {
        profile = p
        api?.profileID = p.id
        if let data = try? JSONEncoder().encode(p) { defaults.set(data, forKey: "profile") }
        stage = .main
        refreshToken += 1
        remote.start(model: self)
    }

    func switchProfile() {
        stage = .profiles
        Task { try? await loadProfiles() }
    }

    func forgetServer() {
        remote.stop()
        for key in ["server", "token", "profile"] { defaults.removeObject(forKey: key) }
        api = nil
        info = nil
        profile = nil
        profiles = []
        stage = .connect
    }

    func setAvatar(_ avatar: String, for p: Profile) async {
        guard let api else { return }
        do {
            let updated = try await api.post("/api/v1/profiles/\(p.id)/avatar", ["avatar": avatar], as: Profile.self)
            if let i = profiles.firstIndex(where: { $0.id == p.id }) { profiles[i] = updated }
            if profile?.id == p.id { profile = updated }
        } catch {
            self.error = error.localizedDescription
        }
    }

    func play(_ item: MediaItem, from start: Double?) {
        player.play(item, start: start, model: self)
    }

    func setWatched(_ item: MediaItem, _ watched: Bool) async {
        guard let api else { return }
        let path = item.kind == "show" ? "/api/v1/shows/\(item.id)/watched" : "/api/v1/items/\(item.id)/watched"
        try? await api.postIgnoringReply(path, ["watched": watched])
        refreshToken += 1
    }

    var hasAvatars: Bool { info?.features.contains("avatars") ?? false }
    var hasRemote: Bool { info?.features.contains("remote") ?? false }

    func show(_ message: String) {
        toast = message
        Task {
            try? await Task.sleep(for: .seconds(3))
            if toast == message { toast = nil }
        }
    }

    // ── remote control ──

    /// The other screens that are on.
    func players() async -> [RemotePlayer] {
        (try? await api?.get("/api/v1/remote/players", as: RemotePlayers.self).players) ?? []
    }

    func command(_ player: RemotePlayer, _ body: [String: Any]) async throws {
        guard let api else { return }
        try await api.postIgnoringReply("/api/v1/remote/players/\(player.id)/command", body)
    }

    /// Start a title on another screen, as this profile, from a position.
    func playOn(_ player: RemotePlayer, item: MediaItem, at position: Double?) async -> Bool {
        do {
            var body: [String: Any] = ["action": "play", "item_id": item.id, "position": position ?? 0]
            if let p = profile { body["profile_id"] = p.id }
            try await command(player, body)
            show("Playing on \(player.name)")
            return true
        } catch {
            show(error.localizedDescription)
            return false
        }
    }

    /// A command from another device.
    func remoteCommand(_ msg: [String: Any]) {
        guard let action = msg["action"] as? String else { return }
        guard action == "play" else { player.command(action, msg); return }
        guard let itemID = msg["item_id"] as? String, let api else { return }
        let position = msg["position"] as? Double
        Task {
            if let pid = msg["profile_id"] as? String, pid != profile?.id {
                try? await loadProfiles()
                if let p = profiles.first(where: { $0.id == pid }) { select(p) }
            }
            guard let detail = try? await api.get("/api/v1/items/\(itemID)", as: ItemDetail.self) else { return }
            player.replace(with: detail.item, start: position, model: self)
        }
    }
}
