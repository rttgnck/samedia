import SwiftUI

/// "Play on…": start a title on another screen without playing it here.
struct PlayOnButton: View {
    @Environment(AppModel.self) private var model
    let item: MediaItem
    var position: Double?
    @State private var picking = false

    var body: some View {
        if model.hasRemote, item.isPlayable {
            Button { picking = true } label: {
                Label("Play on…", systemImage: "tv.and.mediabox")
            }
            .buttonStyle(.bordered).controlSize(.large)
            .sheet(isPresented: $picking) { ScreenPicker(item: item, position: position) }
        }
    }
}

struct ScreenPicker: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let item: MediaItem
    var position: Double?
    @State private var players: [RemotePlayer]?

    var body: some View {
        NavigationStack {
            List {
                if let players, players.isEmpty {
                    Text("No other Samedia screens are on right now.").foregroundStyle(.secondary)
                }
                ForEach(players ?? []) { p in
                    Button {
                        Task { if await model.playOn(p, item: item, at: position) { dismiss() } }
                    } label: {
                        HStack(spacing: 14) {
                            Image(systemName: p.symbol).font(.title2).frame(width: 36)
                            VStack(alignment: .leading) {
                                Text(p.name).font(.headline)
                                Text(p.nowPlaying.map { ($0.playing ? "Playing " : "Paused · ") + ($0.title ?? "") } ?? "Idle")
                                    .font(.subheadline).foregroundStyle(.secondary).lineLimit(1)
                            }
                        }
                    }
                }
            }
            .overlay { if players == nil { ProgressView() } }
            .navigationTitle("Play \(item.title) on")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
        }
        .presentationDetents([.medium])
        .task { players = await model.players() }
    }
}

/// The other screens and what they play, with controls: the app as a remote.
struct RemoteView: View {
    @Environment(AppModel.self) private var model
    @State private var players: [RemotePlayer] = []
    @State private var loaded = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("Remote").font(.largeTitle.bold())
                if loaded && players.isEmpty {
                    ContentUnavailableView("No other screens are on", systemImage: "tv.slash",
                                           description: Text("Open Samedia on a TV, phone or tablet and it shows up here."))
                }
                ForEach(players) { p in PlayerCard(player: p) { await refresh() } }
            }
            .padding(.vertical, 24).padding(.trailing, 24).padding(.leading, Rail.width + 10)
        }
        .task {
            while !Task.isCancelled {
                await refresh()
                try? await Task.sleep(for: .seconds(2))
            }
        }
    }

    private func refresh() async {
        players = await model.players()
        loaded = true
    }
}

struct PlayerCard: View {
    @Environment(AppModel.self) private var model
    let player: RemotePlayer
    var changed: () async -> Void
    @State private var scrub: Double?
    @State private var locking = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 12) {
                Image(systemName: player.symbol).font(.title2)
                Text(player.name).font(.title3.bold())
                Spacer()
                if player.kind == "tv" {
                    Button { locking = true } label: { Label("Lock…", systemImage: "lock") }.buttonStyle(.bordered)
                }
                if player.nowPlaying != nil {
                    Button(role: .destructive) { send(["action": "stop"]) } label: { Image(systemName: "stop.fill") }
                        .buttonStyle(.bordered)
                }
            }
            if let now = player.nowPlaying {
                if now.kind == "track" {
                    HStack(spacing: 14) {
                        CoverArt(path: now.art, title: now.title ?? "").frame(width: 70)
                        VStack(alignment: .leading) {
                            Text(now.title ?? "").font(.headline).lineLimit(1)
                            Text(now.artist ?? "").font(.subheadline).foregroundStyle(.secondary).lineLimit(1)
                        }
                    }
                } else {
                    Text(now.title ?? "").font(.headline).lineLimit(1)
                }
                if let d = now.duration, d > 0 {
                    let at = scrub ?? now.position ?? 0
                    Slider(value: Binding(get: { at }, set: { scrub = $0 }), in: 0...d) { editing in
                        if !editing, let to = scrub { send(["action": "seek", "position": to]); scrub = nil }
                    }
                    HStack {
                        Text(Format.clock(at)).monospacedDigit()
                        Spacer()
                        Text("-" + Format.clock(max(0, d - at))).monospacedDigit()
                    }
                    .font(.caption).foregroundStyle(.secondary)
                }
                HStack(spacing: 34) {
                    Spacer()
                    if now.kind == "track" {
                        Button { send(["action": "previous"]) } label: { Image(systemName: "backward.fill") }
                    } else {
                        Button { send(["action": "skip", "delta": -10]) } label: { Image(systemName: "gobackward.10") }
                    }
                    Button { send(["action": "toggle"]) } label: {
                        Image(systemName: now.playing ? "pause.circle.fill" : "play.circle.fill").font(.system(size: 54))
                    }
                    if now.kind == "track" {
                        Button { send(["action": "next"]) } label: { Image(systemName: "forward.fill") }
                    } else {
                        Button { send(["action": "skip", "delta": 30]) } label: { Image(systemName: "goforward.30") }
                    }
                    Spacer()
                }
                .font(.title)
                .buttonStyle(.plain)
            } else {
                Text("Nothing playing").foregroundStyle(.secondary)
            }
            if player.can.contains("keys") || player.can.contains("volume") {
                HStack(alignment: .center, spacing: 40) {
                    Spacer()
                    if player.can.contains("keys") { DPad { send(["action": "key", "key": $0]) } }
                    if player.can.contains("volume") {
                        VStack(spacing: 14) {
                            KeyButton(symbol: "speaker.plus.fill") { send(["action": "volume", "key": "up"]) }
                            KeyButton(symbol: "speaker.slash.fill") { send(["action": "volume", "key": "mute"]) }
                            KeyButton(symbol: "speaker.minus.fill") { send(["action": "volume", "key": "down"]) }
                        }
                    }
                    Spacer()
                }
                .padding(.top, 6)
            }
        }
        .padding(20)
        .background(Color.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 18))
        .sheet(isPresented: $locking) { LockEditor(player: player) }
    }

    private func send(_ body: [String: Any]) {
        Task {
            do { try await model.command(player, body) } catch { model.show(error.localizedDescription) }
            try? await Task.sleep(for: .milliseconds(300))
            await changed()
        }
    }
}

/// Arrows, OK, Back and Home for the screen's own menus.
private struct DPad: View {
    let press: (String) -> Void

    var body: some View {
        VStack(spacing: 12) {
            ZStack {
                Circle().fill(Color.white.opacity(0.08)).frame(width: 210, height: 210)
                VStack(spacing: 0) {
                    arrow("chevron.up", "up")
                    HStack(spacing: 0) {
                        arrow("chevron.left", "left")
                        Button { tap("enter") } label: {
                            Text("OK").font(.headline).frame(width: 74, height: 74)
                                .background(Color.accentColor, in: Circle()).foregroundStyle(.white)
                        }
                        arrow("chevron.right", "right")
                    }
                    arrow("chevron.down", "down")
                }
            }
            HStack(spacing: 16) {
                Button { tap("back") } label: { Label("Back", systemImage: "arrow.uturn.backward") }
                Button { tap("home") } label: { Label("Home", systemImage: "house") }
            }
            .buttonStyle(.bordered)
        }
        .buttonStyle(.plain)
    }

    private func arrow(_ symbol: String, _ key: String) -> some View {
        Button { tap(key) } label: {
            Image(systemName: symbol).font(.title2.weight(.semibold)).frame(width: 66, height: 66).contentShape(Rectangle())
        }
    }

    private func tap(_ key: String) {
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
        press(key)
    }
}

private struct KeyButton: View {
    let symbol: String
    let action: () -> Void

    var body: some View {
        Button {
            UIImpactFeedbackGenerator(style: .light).impactOccurred()
            action()
        } label: {
            Image(systemName: symbol).font(.title3).frame(width: 54, height: 54)
                .background(Color.white.opacity(0.08), in: Circle())
        }
        .buttonStyle(.plain)
    }
}
