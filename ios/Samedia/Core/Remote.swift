import Foundation

/// Another Samedia screen that is on (TV, iPad, phone), with what it is playing.
struct RemotePlayer: Decodable, Identifiable, Hashable {
    struct NowPlaying: Decodable, Hashable {
        let itemID: String
        let title: String?
        let position: Double?
        let duration: Double?
        let playing: Bool
        enum CodingKeys: String, CodingKey { case item_id, title, position, duration, playing }
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            itemID = try c.decode(String.self, forKey: .item_id)
            title = try? c.decode(String.self, forKey: .title)
            position = try? c.decode(Double.self, forKey: .position)
            duration = try? c.decode(Double.self, forKey: .duration)
            playing = (try? c.decode(Bool.self, forKey: .playing)) ?? false
        }
    }

    let id: String
    let name: String
    let kind: String
    let nowPlaying: NowPlaying?
    /// Extra controls it takes: "keys" (arrows/OK/back for its menus), "volume".
    let can: [String]
    enum CodingKeys: String, CodingKey { case id, name, kind, now_playing, can }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = (try? c.decode(String.self, forKey: .name)) ?? "Screen"
        kind = (try? c.decode(String.self, forKey: .kind)) ?? "tv"
        nowPlaying = try? c.decode(NowPlaying.self, forKey: .now_playing)
        can = (try? c.decode([String].self, forKey: .can)) ?? []
    }

    var symbol: String { kind == "tv" ? "tv" : kind == "android" ? "iphone.gen3" : "ipad" }
}

struct RemotePlayers: Decodable { let players: [RemotePlayer] }

/// Keeps this device reachable for remote commands and tells the server what it is playing.
@MainActor
final class RemoteLink {
    private var task: URLSessionWebSocketTask?
    private var retry: Double = 1
    private var lastState: [String: Any] = ["type": "state", "item_id": NSNull()]
    private weak var model: AppModel?
    private var generation = 0

    func start(model: AppModel) {
        self.model = model
        guard let api = model.api, model.info?.features.contains("remote") == true else { return }
        stop()
        generation += 1
        let mine = generation
        var url = api.url("/api/v1/remote/ws", query: [
            URLQueryItem(name: "device", value: APIClient.deviceID),
            URLQueryItem(name: "name", value: APIClient.deviceName),
            URLQueryItem(name: "kind", value: "ios"),
            URLQueryItem(name: "app", value: APIClient.appTag),
        ])
        if var c = URLComponents(url: url, resolvingAgainstBaseURL: false) {
            c.scheme = c.scheme == "https" ? "wss" : "ws"
            url = c.url ?? url
        }
        let task = APIClient.session.webSocketTask(with: url)
        self.task = task
        task.resume()
        send(lastState)
        receive(task, generation: mine)
        Task { [weak self] in await self?.keepAlive(task, generation: mine) }
    }

    func stop() {
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
    }

    /// What this device plays now (nil when stopped).
    func report(_ state: [String: Any]?) {
        var s: [String: Any] = ["type": "state", "item_id": NSNull()]
        state?.forEach { s[$0.key] = $0.value }
        lastState = s
        send(s)
    }

    private func send(_ obj: [String: Any]) {
        guard let task, let data = try? JSONSerialization.data(withJSONObject: obj),
              let text = String(data: data, encoding: .utf8) else { return }
        task.send(.string(text)) { _ in }
    }

    private func receive(_ task: URLSessionWebSocketTask, generation: Int) {
        task.receive { [weak self] result in
            Task { @MainActor in
                guard let self, generation == self.generation else { return }
                switch result {
                case .success(.string(let text)):
                    self.retry = 1
                    if let data = text.data(using: .utf8),
                       let msg = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                       msg["type"] as? String == "command" {
                        self.model?.remoteCommand(msg)
                    }
                    self.receive(task, generation: generation)
                case .success:
                    self.receive(task, generation: generation)
                case .failure:
                    self.reconnectLater()
                }
            }
        }
    }

    private func keepAlive(_ task: URLSessionWebSocketTask, generation: Int) async {
        while generation == self.generation {
            try? await Task.sleep(for: .seconds(20))
            guard generation == self.generation else { return }
            send(["type": "ping"])
        }
    }

    private func reconnectLater() {
        task = nil
        let delay = retry
        retry = min(retry * 2, 30)
        Task { [weak self] in
            try? await Task.sleep(for: .seconds(delay))
            guard let self, self.task == nil, let model = self.model else { return }
            self.start(model: model)
        }
    }
}
