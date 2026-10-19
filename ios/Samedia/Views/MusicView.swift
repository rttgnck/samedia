import SwiftUI

enum MusicRoute: Hashable {
    case album(String)
    case artist(String, String)
    case playlist(String)
}

/// Album art (or a Spotify image URL) in a square.
struct CoverArt: View {
    @Environment(AppModel.self) private var model
    let path: String?
    var title: String = ""
    var round = false

    var body: some View {
        ZStack {
            LinearGradient(colors: [Color(white: 0.2), Color(white: 0.1)], startPoint: .top, endPoint: .bottom)
            Text(title).font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center).padding(6)
            RemoteImage(url: url)
        }
        .aspectRatio(1, contentMode: .fit)
        .clipShape(round ? AnyShape(Circle()) : AnyShape(RoundedRectangle(cornerRadius: 10, style: .continuous)))
    }

    private var url: URL? {
        guard let path else { return nil }
        if path.hasPrefix("http") { return URL(string: path) }
        return model.api?.art(path, width: 600)
    }
}

// ── the section ──

struct MusicView: View {
    @Environment(AppModel.self) private var model
    @State private var path = NavigationPath()
    @State private var section = "albums"
    @State private var query = ""
    @State private var home: MusicHome?
    @State private var albums: [Album] = []
    @State private var artists: [Artist] = []
    @State private var playlists: [SpotifyPlaylist] = []
    @State private var spotifyOn = false
    @State private var found: MusicSearch?
    @State private var spotifyFound: SpotifySearch?
    @State private var pickFor: SpotifyTrack?

    private let grid = [GridItem(.adaptive(minimum: 150), spacing: 18)]

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text("Music").font(.largeTitle.bold())
                    TextField(spotifyOn ? "Your music and Spotify" : "Artists, albums, songs", text: $query)
                        .textFieldStyle(.roundedBorder).frame(maxWidth: 520)
                    if query.trimmingCharacters(in: .whitespaces).isEmpty {
                        Picker("", selection: $section) {
                            Text("Albums").tag("albums")
                            Text("Artists").tag("artists")
                            if spotifyOn { Text("Spotify").tag("spotify") }
                        }
                        .pickerStyle(.segmented).frame(maxWidth: 420)
                        content
                    } else {
                        results
                    }
                }
                .padding(.vertical, 24).padding(.trailing, 24).padding(.leading, Rail.width + 10)
                .padding(.bottom, 80)
            }
            .navigationDestination(for: MusicRoute.self) { route in
                switch route {
                case .album(let id): AlbumView(id: id)
                case .artist(let id, let name): ArtistView(id: id, name: name)
                case .playlist(let id): PlaylistView(id: id)
                }
            }
        }
        .task(id: model.refreshToken) { await load() }
        .task(id: query) { await search() }
        .task(id: section) {
            if section == "artists", artists.isEmpty { artists = (try? await model.api?.get("/api/v1/music/artists", as: ArtistList.self))?.artists ?? [] }
            if section == "spotify", playlists.isEmpty { playlists = (try? await model.api?.get("/api/v1/spotify/playlists", as: SpotifyPlaylists.self))?.playlists ?? [] }
        }
        .sheet(item: $pickFor) { t in SpotifyDevicePicker { d in model.spotifyPlay(d, uris: [t.uri].compactMap { $0 }) } }
    }

    @ViewBuilder private var content: some View {
        switch section {
        case "artists":
            LazyVGrid(columns: grid, spacing: 22) {
                ForEach(artists) { a in
                    NavigationLink(value: MusicRoute.artist(a.id, a.name)) {
                        VStack { CoverArt(path: a.art, title: a.name, round: true); Text(a.name).font(.subheadline).lineLimit(1) }
                    }.buttonStyle(.plain)
                }
            }
        case "spotify":
            LazyVGrid(columns: grid, spacing: 22) { ForEach(playlists) { p in playlistTile(p) } }
        default:
            ForEach((home?.shelves ?? []).filter { $0.id != "recent" }) { shelf in
                Text(shelf.title).font(.title3.bold())
                ScrollView(.horizontal, showsIndicators: false) {
                    LazyHStack(spacing: 16) { ForEach(shelf.items) { a in albumTile(a).frame(width: 150) } }
                }
            }
            if albums.isEmpty && !spotifyOn {
                Text("No music yet. Put music in a media folder (or set a folder to Music in the server admin page) and scan.")
                    .foregroundStyle(.secondary)
            } else {
                Text("All albums").font(.title3.bold())
                LazyVGrid(columns: grid, spacing: 22) { ForEach(albums) { a in albumTile(a) } }
            }
        }
    }

    @ViewBuilder private var results: some View {
        if let f = found {
            if !f.albums.isEmpty {
                Text("Albums").font(.title3.bold())
                LazyVGrid(columns: grid, spacing: 22) { ForEach(f.albums) { a in albumTile(a) } }
            }
            if !f.tracks.isEmpty {
                Text("Songs").font(.title3.bold())
                ForEach(Array(f.tracks.enumerated()), id: \.element.id) { _, t in
                    TrackRowView(track: t, showArtist: true) { model.music.play([t], model: model) }
                }
            }
        }
        if let s = spotifyFound {
            if !s.playlists.isEmpty {
                Text("Spotify playlists").font(.title3.bold())
                LazyVGrid(columns: grid, spacing: 22) { ForEach(s.playlists.prefix(12)) { p in playlistTile(p) } }
            }
            if !s.tracks.isEmpty {
                Text("Spotify songs").font(.title3.bold())
                ForEach(s.tracks) { t in
                    Button { pickFor = t } label: {
                        HStack { Text(t.title); Text(t.artist ?? "").foregroundStyle(.secondary); Spacer() }.padding(.vertical, 6)
                    }.buttonStyle(.plain)
                }
            }
        }
    }

    private func albumTile(_ a: Album) -> some View {
        NavigationLink(value: MusicRoute.album(a.id)) {
            VStack(alignment: .leading, spacing: 4) {
                CoverArt(path: a.art, title: a.title)
                Text(a.title).font(.subheadline.weight(.semibold)).lineLimit(1)
                Text(a.artist ?? "").font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
        }.buttonStyle(.plain)
    }

    private func playlistTile(_ p: SpotifyPlaylist) -> some View {
        NavigationLink(value: MusicRoute.playlist(p.id)) {
            VStack(alignment: .leading, spacing: 4) {
                CoverArt(path: p.image, title: p.title)
                Text(p.title).font(.subheadline.weight(.semibold)).lineLimit(1)
                Text("\(p.count) songs").font(.caption).foregroundStyle(.secondary)
            }
        }.buttonStyle(.plain)
    }

    private func load() async {
        guard let api = model.api else { return }
        home = try? await api.get("/api/v1/music/home", as: MusicHome.self)
        albums = (try? await api.get("/api/v1/music/albums?sort=artist", as: AlbumList.self))?.albums ?? []
        spotifyOn = (try? await api.get("/api/v1/spotify/status", as: SpotifyStatus.self))?.connected ?? false
    }

    private func search() async {
        let q = query.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty, let api = model.api else { found = nil; spotifyFound = nil; return }
        try? await Task.sleep(for: .milliseconds(300))
        guard !Task.isCancelled else { return }
        let enc = q.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? q
        found = try? await api.get("/api/v1/music/search?q=\(enc)", as: MusicSearch.self)
        spotifyFound = spotifyOn ? try? await api.get("/api/v1/spotify/search?q=\(enc)", as: SpotifySearch.self) : nil
    }
}

struct TrackRowView: View {
    @Environment(AppModel.self) private var model
    let track: Track
    var number: Int?
    var showArtist = false
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 14) {
                if let number { Text("\(number)").foregroundStyle(.secondary).frame(width: 30, alignment: .trailing) }
                VStack(alignment: .leading) {
                    Text(track.title).foregroundStyle(model.music.current?.id == track.id ? Color.accentColor : .primary).lineLimit(1)
                    if showArtist, let a = track.artist { Text(a).font(.caption).foregroundStyle(.secondary).lineLimit(1) }
                }
                Spacer()
                Text(track.duration.map { Format.clock($0) } ?? "").font(.callout).foregroundStyle(.secondary).monospacedDigit()
            }
            .padding(.vertical, 10).contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

/// The cover big, the same blurred behind it.
private struct CoverHeader: View {
    let art: String?
    let title: String
    var body: some View {
        ZStack {
            CoverArt(path: art, title: title).blur(radius: 50).opacity(0.5).frame(height: 300).clipped()
            CoverArt(path: art, title: title).frame(width: 240).shadow(radius: 30)
        }
        .frame(maxWidth: .infinity)
    }
}

struct AlbumView: View {
    @Environment(AppModel.self) private var model
    let id: String
    @State private var album: Album?
    @State private var playOn = false

    var body: some View {
        ScrollView {
            if let a = album {
                VStack(spacing: 10) {
                    CoverHeader(art: a.art, title: a.title)
                    Text(a.title).font(.title.bold()).multilineTextAlignment(.center)
                    if let artist = a.artist, let rid = a.artistID {
                        NavigationLink(value: MusicRoute.artist(rid, artist)) { Text(artist).font(.title3) }
                    }
                    Text([a.year.map(String.init), "\(a.trackCount) songs", Format.runtime(a.duration), a.genre].compactMap { $0 }
                        .joined(separator: "  ·  ")).font(.callout).foregroundStyle(.secondary)
                    HStack(spacing: 12) {
                        Button { model.music.play(a.tracks, model: model) } label: { Label("Play", systemImage: "play.fill") }
                            .buttonStyle(.borderedProminent).controlSize(.large)
                        Button { model.music.play(a.tracks, start: Int.random(in: 0..<max(1, a.tracks.count)), shuffled: true, model: model) } label: {
                            Label("Shuffle", systemImage: "shuffle") }.buttonStyle(.bordered).controlSize(.large)
                        if model.hasRemote {
                            Button { playOn = true } label: { Label("Play on…", systemImage: "tv.and.mediabox") }
                                .buttonStyle(.bordered).controlSize(.large)
                        }
                    }
                    .padding(.vertical, 8)
                    VStack(spacing: 0) {
                        ForEach(Array(a.tracks.enumerated()), id: \.element.id) { i, t in
                            TrackRowView(track: t, number: t.track ?? i + 1, showArtist: a.artist == "Various Artists") {
                                model.music.play(a.tracks, start: i, model: model)
                            }
                            Divider().opacity(0.3)
                        }
                    }
                    .frame(maxWidth: 820)
                }
                .padding(.leading, Rail.width).padding(.horizontal, 24).padding(.bottom, 90)
            } else {
                ProgressView().padding(80)
            }
        }
        .task { album = try? await model.api?.get("/api/v1/music/albums/\(id)", as: Album.self) }
        .sheet(isPresented: $playOn) { MusicPlayOnPicker(tracks: album?.tracks ?? [], start: 0) }
    }
}

struct ArtistView: View {
    @Environment(AppModel.self) private var model
    let id: String
    let name: String
    @State private var artist: Artist?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text(name).font(.largeTitle.bold())
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 160), spacing: 18)], spacing: 22) {
                    ForEach(artist?.albums ?? []) { a in
                        NavigationLink(value: MusicRoute.album(a.id)) {
                            VStack(alignment: .leading, spacing: 4) {
                                CoverArt(path: a.art, title: a.title)
                                Text(a.title).font(.subheadline.weight(.semibold)).lineLimit(1)
                                Text(a.year.map(String.init) ?? "").font(.caption).foregroundStyle(.secondary)
                            }
                        }.buttonStyle(.plain)
                    }
                }
            }
            .padding(.vertical, 24).padding(.trailing, 24).padding(.leading, Rail.width + 10).padding(.bottom, 80)
        }
        .task { artist = try? await model.api?.get("/api/v1/music/artists/\(id)", as: Artist.self) }
    }
}

struct PlaylistView: View {
    @Environment(AppModel.self) private var model
    let id: String
    @State private var playlist: SpotifyPlaylist?
    @State private var choose: ((SpotifyDevice) -> Void)?
    @State private var picking = false

    var body: some View {
        ScrollView {
            if let p = playlist {
                VStack(spacing: 10) {
                    CoverHeader(art: p.image, title: p.title)
                    Text(p.title).font(.title.bold())
                    Text((p.owner.map { "by \($0)  ·  " } ?? "") + "\(p.tracks.count) songs  ·  long-press a song for a radio")
                        .font(.callout).foregroundStyle(.secondary)
                    Button { pick { d in model.spotifyPlay(d, contextURI: p.uri) } } label: { Label("Play on Spotify…", systemImage: "play.fill") }
                        .buttonStyle(.borderedProminent).controlSize(.large).padding(.vertical, 8)
                    VStack(spacing: 0) {
                        ForEach(Array(p.tracks.enumerated()), id: \.element.id) { i, t in
                            Button { pick { d in model.spotifyPlay(d, contextURI: p.uri, offset: i) } } label: {
                                HStack(spacing: 12) {
                                    CoverArt(path: t.image).frame(width: 40)
                                    VStack(alignment: .leading) { Text(t.title).lineLimit(1); Text(t.artist ?? "").font(.caption).foregroundStyle(.secondary) }
                                    Spacer()
                                    Text(t.duration.map { Format.clock($0) } ?? "").foregroundStyle(.secondary).monospacedDigit()
                                }
                                .padding(.vertical, 6).contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .contextMenu {
                                if let uri = t.uri {
                                    Button("Radio from this song", systemImage: "dot.radiowaves.left.and.right") { pick { d in model.spotifyRadio(d, seed: uri) } }
                                }
                            }
                            Divider().opacity(0.3)
                        }
                    }
                    .frame(maxWidth: 820)
                }
                .padding(.leading, Rail.width).padding(.horizontal, 24).padding(.bottom, 90)
            } else {
                ProgressView().padding(80)
            }
        }
        .task { playlist = try? await model.api?.get("/api/v1/spotify/playlists/\(id)", as: SpotifyPlaylist.self) }
        .sheet(isPresented: $picking) { SpotifyDevicePicker { d in choose?(d) } }
    }

    private func pick(_ action: @escaping (SpotifyDevice) -> Void) { choose = action; picking = true }
}

// ── pickers ──

struct SpotifyDevicePicker: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    var onPick: (SpotifyDevice) -> Void
    @State private var devices: [SpotifyDevice]?

    var body: some View {
        NavigationStack {
            List {
                if let devices, devices.isEmpty { Text("Open Spotify on a TV, phone or speaker: it shows up here then.").foregroundStyle(.secondary) }
                ForEach(devices ?? []) { d in
                    Button { onPick(d); dismiss() } label: {
                        Label { VStack(alignment: .leading) { Text(d.name); Text(d.type ?? "").font(.caption).foregroundStyle(.secondary) } }
                            icon: { Image(systemName: "hifispeaker.2") }
                    }
                }
            }
            .overlay { if devices == nil { ProgressView() } }
            .navigationTitle("Play on Spotify device").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
        }
        .presentationDetents([.medium])
        .task { devices = (try? await model.api?.get("/api/v1/spotify/devices", as: SpotifyDevices.self))?.devices ?? [] }
    }
}

struct MusicPlayOnPicker: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let tracks: [Track]
    let start: Int
    @State private var players: [RemotePlayer]?

    var body: some View {
        NavigationStack {
            List {
                if let players, players.isEmpty { Text("No other Samedia screens are on right now.").foregroundStyle(.secondary) }
                ForEach(players ?? []) { p in
                    Button {
                        Task {
                            var body: [String: Any] = ["action": "play_music", "tracks": tracks.map(\.id), "index": start]
                            if let pr = model.profile { body["profile_id"] = pr.id }
                            do { try await model.command(p, body); model.show("Playing on \(p.name)"); dismiss() }
                            catch { model.show(error.localizedDescription) }
                        }
                    } label: { Label(p.name, systemImage: p.symbol) }
                }
            }
            .overlay { if players == nil { ProgressView() } }
            .navigationTitle("Play on").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
        }
        .presentationDetents([.medium])
        .task { players = await model.players() }
    }
}

// ── mini player and Now Playing ──

struct MiniPlayerBar: View {
    @Environment(AppModel.self) private var model
    @Binding var showing: Bool

    var body: some View {
        if let t = model.music.current {
            HStack(spacing: 14) {
                CoverArt(path: t.art, title: t.album ?? "").frame(width: 48)
                VStack(alignment: .leading) {
                    Text(t.title).font(.headline).lineLimit(1)
                    Text(t.artist ?? "").font(.subheadline).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer()
                Button { model.music.toggle() } label: { Image(systemName: model.music.playing ? "pause.fill" : "play.fill").font(.title2) }
                Button { model.music.next() } label: { Image(systemName: "forward.fill").font(.title2) }
            }
            .buttonStyle(.plain)
            .padding(10).padding(.trailing, 10)
            .frame(maxWidth: 560)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 20))
            .contentShape(Rectangle())
            .onTapGesture { showing = true }
            .padding(.bottom, 16)
        }
    }
}

struct NowPlayingView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @AppStorage("vizMode") private var mode = "bars"
    @State private var scrub: Double?
    @State private var playOn = false

    var body: some View {
        let t = model.music.current
        ZStack {
            Color.black.ignoresSafeArea()
            CoverArt(path: t?.art, title: "").blur(radius: 70).opacity(0.35).ignoresSafeArea()
            VStack(spacing: 18) {
                HStack {
                    Button { dismiss() } label: { Image(systemName: "chevron.down").font(.title2) }
                    Spacer()
                    Picker("", selection: $mode) {
                        Text("Spectrum").tag("bars"); Text("Scope").tag("scope"); Text("Vinyl").tag("disc"); Text("Cover").tag("cover")
                    }.pickerStyle(.segmented).frame(maxWidth: 420)
                }
                if mode == "cover" {
                    CoverArt(path: t?.art, title: t?.album ?? "").frame(maxWidth: 440).shadow(radius: 30).frame(maxHeight: .infinity)
                } else {
                    VisualizerView(mode: mode, art: t?.art).frame(maxHeight: .infinity)
                }
                Text(t?.title ?? "Nothing playing").font(.largeTitle.bold()).lineLimit(1)
                Text([t?.artist, t?.album].compactMap { $0 }.joined(separator: " — ")).foregroundStyle(.secondary).lineLimit(1)
                let d = max(t?.duration ?? 1, 1)
                let at = scrub ?? min(model.music.position, d)
                Slider(value: Binding(get: { at }, set: { scrub = $0 }), in: 0...d) { editing in
                    if !editing, let s = scrub { model.music.seek(s); scrub = nil }
                }
                HStack { Text(Format.clock(at)); Spacer(); Text("-" + Format.clock(d - at)) }.font(.caption).foregroundStyle(.secondary).monospacedDigit()
                HStack(spacing: 44) {
                    Button { model.music.previous() } label: { Image(systemName: "backward.fill") }
                    Button { model.music.toggle() } label: { Image(systemName: model.music.playing ? "pause.circle.fill" : "play.circle.fill").font(.system(size: 70)) }
                    Button { model.music.next() } label: { Image(systemName: "forward.fill") }
                    if model.hasRemote { Button { playOn = true } label: { Image(systemName: "tv.and.mediabox") } }
                }
                .font(.title).buttonStyle(.plain)
            }
            .padding(30)
            .foregroundStyle(.white)
        }
        .sheet(isPresented: $playOn) { MusicPlayOnPicker(tracks: model.music.queue, start: model.music.index) }
    }
}

/// The visualizer: Winamp's bars with peak caps, an oscilloscope, a record with a radial spectrum.
struct VisualizerView: View {
    @Environment(AppModel.self) private var model
    let mode: String
    let art: String?
    @State private var peaks = [CGFloat](repeating: 0, count: 28)

    var body: some View {
        TimelineView(.animation) { timeline in
            Canvas { g, size in
                let playing = model.music.playing
                switch mode {
                case "scope":
                    let w = Levels.shared.wave(256, playing: playing)
                    var path = Path()
                    for (i, v) in w.enumerated() {
                        let p = CGPoint(x: CGFloat(i) / CGFloat(w.count - 1) * size.width, y: size.height / 2 + CGFloat(v) * size.height * 0.38)
                        i == 0 ? path.move(to: p) : path.addLine(to: p)
                    }
                    g.stroke(path, with: .color(Color(red: 0, green: 1, blue: 0.55).opacity(0.25)), lineWidth: 12)
                    g.stroke(path, with: .color(Color(red: 0, green: 1, blue: 0.55)), lineWidth: 3)
                case "disc":
                    let n = 64
                    let b = Levels.shared.bands(n / 2, playing: playing)
                    let r = min(size.width, size.height) * 0.2
                    let c = CGPoint(x: size.width / 2, y: size.height / 2)
                    for i in 0..<n {
                        let v = CGFloat(b[i < n / 2 ? i : n - 1 - i])
                        let a = CGFloat(i) / CGFloat(n) * 2 * .pi - .pi / 2
                        let len = 8 + pow(v, 1.2) * min(size.width, size.height) * 0.25
                        var p = Path()
                        p.move(to: CGPoint(x: c.x + cos(a) * (r + 8), y: c.y + sin(a) * (r + 8)))
                        p.addLine(to: CGPoint(x: c.x + cos(a) * (r + 8 + len), y: c.y + sin(a) * (r + 8 + len)))
                        g.stroke(p, with: .color(Color(hue: (200 + Double(i) / Double(n) * 160).truncatingRemainder(dividingBy: 360) / 360,
                                                       saturation: 0.85, brightness: 0.95)), style: StrokeStyle(lineWidth: 6, lineCap: .round))
                    }
                    g.fill(Path(ellipseIn: CGRect(x: c.x - r, y: c.y - r, width: r * 2, height: r * 2)), with: .color(Color(white: 0.07)))
                default:
                    let n = 28
                    let b = Levels.shared.bands(n, playing: playing)
                    let gap = size.width * 0.008, bw = (size.width - gap * CGFloat(n - 1)) / CGFloat(n)
                    let base = size.height * 0.85, seg = size.height * 0.02
                    for i in 0..<n {
                        let h = pow(CGFloat(b[i]), 1.3) * base * 0.95
                        var y = base - seg
                        while y > base - h {
                            let f = (base - y) / base
                            let color: Color = f > 0.8 ? Color(red: 1, green: 0.13, blue: 0) : f > 0.55 ? Color(red: 1, green: 0.7, blue: 0) : Color(red: 0, green: 0.8, blue: 0)
                            g.fill(Path(CGRect(x: CGFloat(i) * (bw + gap), y: y, width: bw, height: seg)), with: .color(color))
                            y -= seg * 1.25
                        }
                        let peak = max(peaks[i] - base * 0.006, h)
                        DispatchQueue.main.async { peaks[i] = peak }
                        g.fill(Path(CGRect(x: CGFloat(i) * (bw + gap), y: base - peak - seg * 0.5, width: bw, height: seg * 0.35)),
                               with: .color(Color(white: 0.8)))
                    }
                }
                _ = timeline.date
            }
        }
        .overlay {
            if mode == "disc" {
                GeometryReader { geo in
                    let d = min(geo.size.width, geo.size.height) * 0.36
                    CoverArt(path: art, round: true).frame(width: d).position(x: geo.size.width / 2, y: geo.size.height / 2)
                        .rotationEffect(.degrees(model.music.playing ? 360 : 0))
                        .animation(model.music.playing ? .linear(duration: 8).repeatForever(autoreverses: false) : .default, value: model.music.playing)
                }
            }
        }
    }
}

// ── locking a screen to approved music (admin) ──

struct LockEditor: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let player: RemotePlayer
    @State private var lock: DeviceLock?
    @State private var locked = false
    @State private var profiles: [Profile] = []
    @State private var artists: [Artist] = []
    @State private var albums: [Album] = []
    @State private var playlists: [SpotifyPlaylist] = []
    @State private var filter = ""

    var body: some View {
        NavigationStack {
            Form {
                Section { Text("A locked screen shows one profile and plays only the music approved here: no films or shows.").foregroundStyle(.secondary) }
                if lock != nil {
                    Section("Profile") {
                        Picker("Locked to", selection: Binding(get: { lock?.profile ?? "" }, set: { lock?.profile = $0 })) {
                            ForEach(profiles) { Text($0.name).tag($0.id) }
                        }
                    }
                    Section { TextField("Filter", text: $filter) }
                    if !playlists.isEmpty {
                        Section("Spotify playlists") { ForEach(playlists.filter(match)) { p in check(p.title, \.playlists, p.id) } }
                    }
                    Section("Artists (all their albums)") { ForEach(artists.filter(match)) { a in check(a.name, \.artists, a.id) } }
                    Section("Albums") { ForEach(albums.filter(match)) { a in check("\(a.artist ?? "") — \(a.title)", \.albums, a.id) } }
                    if locked {
                        Section { Button("Unlock \(player.name)", role: .destructive) { Task { await unlock() } } }
                    }
                }
            }
            .navigationTitle("Lock \(player.name)").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button(locked ? "Save" : "Lock") { Task { await save() } }.disabled(lock == nil) }
            }
        }
        .task { await load() }
    }

    private func match(_ a: Artist) -> Bool { filter.isEmpty || a.name.localizedCaseInsensitiveContains(filter) }
    private func match(_ a: Album) -> Bool { filter.isEmpty || a.title.localizedCaseInsensitiveContains(filter) || (a.artist ?? "").localizedCaseInsensitiveContains(filter) }
    private func match(_ p: SpotifyPlaylist) -> Bool { filter.isEmpty || p.title.localizedCaseInsensitiveContains(filter) }

    private func check(_ label: String, _ key: WritableKeyPath<DeviceLock, [String]>, _ id: String) -> some View {
        Toggle(label, isOn: Binding(get: { lock?[keyPath: key].contains(id) ?? false },
                                    set: { on in
                                        guard var l = lock else { return }
                                        if on { l[keyPath: key].append(id) } else { l[keyPath: key].removeAll { $0 == id } }
                                        lock = l
                                    }))
    }

    private func load() async {
        guard let api = model.api else { return }
        profiles = (try? await api.get("/api/v1/profiles?all=true", as: ProfilesResponse.self))?.profiles ?? []
        artists = (try? await api.get("/api/v1/music/artists", as: ArtistList.self))?.artists ?? []
        albums = (try? await api.get("/api/v1/music/albums?sort=artist", as: AlbumList.self))?.albums ?? []
        playlists = (try? await api.get("/api/v1/spotify/playlists", as: SpotifyPlaylists.self))?.playlists ?? []
        let existing = (try? await api.get("/api/v1/admin/devices", as: AdminDevices.self))?.devices.first { $0.id == player.id }?.lock
        locked = existing != nil
        lock = existing ?? DeviceLock(profile: profiles.first { $0.kids == true }?.id ?? profiles.first?.id ?? "default")
    }

    private func save() async {
        guard let lock, let api = model.api, let data = try? JSONEncoder().encode(lock),
              let body = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        do {
            try await api.send("/api/v1/admin/devices/\(player.id)/lock", method: "PUT", body)
            model.show("\(player.name) is locked to music")
            dismiss()
        } catch { model.show(error.localizedDescription) }
    }

    private func unlock() async {
        try? await model.api?.send("/api/v1/admin/devices/\(player.id)/lock", method: "DELETE", nil)
        model.show("\(player.name) is unlocked")
        dismiss()
    }
}
