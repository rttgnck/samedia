import SwiftUI

@main
struct SamediaApp: App {
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .preferredColorScheme(.dark)
                .tint(Color("AccentColor"))
        }
    }
}

struct RootView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        switch model.stage {
        case .connect: ConnectView()
        case .profiles: ProfilesView()
        case .main: MainView()
        }
    }
}

/// The app's screens with the TV-style rail of soft icons floating over them (it never
/// moves the content).
struct MainView: View {
    enum Section: CaseIterable { case home, movies, shows, music, search, remote }

    @Environment(AppModel.self) private var model
    @Environment(\.scenePhase) private var scenePhase
    @State private var section: Section = .home
    @State private var nowPlaying = false

    var body: some View {
        ZStack(alignment: .leading) {
            Group {
                switch section {
                case .home: HomeView()
                case .movies: NavigationStack { LibraryView(kind: .movies) }
                case .shows: NavigationStack { LibraryView(kind: .shows) }
                case .music: MusicView()
                case .search: NavigationStack { SearchView() }
                case .remote: RemoteView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            Rail(section: $section)
        }
        .overlay(alignment: .bottom) { MiniPlayerBar(showing: $nowPlaying) }
        .fullScreenCover(isPresented: $nowPlaying) { NowPlayingView() }
        .overlay(alignment: .bottom) {
            if let toast = model.toast {
                Text(toast).font(.callout.weight(.semibold)).padding(.horizontal, 18).padding(.vertical, 10)
                    .background(.regularMaterial, in: Capsule()).padding(.bottom, 30)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.snappy, value: model.toast)
        // Back in the app: another device may have watched something meanwhile
        .onChange(of: scenePhase) { _, phase in if phase == .active { model.refreshToken += 1 } }
    }
}

struct Rail: View {
    /// Room the rail takes at the left edge; scrolling content keeps clear of it.
    static let width: CGFloat = 88

    @Environment(AppModel.self) private var model
    @Binding var section: MainView.Section

    var body: some View {
        VStack(spacing: 10) {
            icon(.home, "house.fill")
            icon(.movies, "film.fill")
            icon(.shows, "tv.fill")
            icon(.music, "music.note")
            icon(.search, "magnifyingglass")
            if model.hasRemote { icon(.remote, "appletvremote.gen4.fill") }
            if let p = model.profile {
                Menu {
                    Button("Switch profile", systemImage: "person.2") { model.switchProfile() }
                    Button("Use a different server", systemImage: "server.rack") { model.forgetServer() }
                } label: {
                    AvatarView(profile: p, size: 40).padding(.top, 14)
                }
            }
        }
        .padding(.vertical, 18).padding(.horizontal, 10)
        .background(.ultraThinMaterial.opacity(0.55), in: Capsule())
        .overlay(Capsule().stroke(.white.opacity(0.08)))
        .padding(.leading, 14)
    }

    private func icon(_ s: MainView.Section, _ symbol: String) -> some View {
        let on = section == s
        return Button {
            withAnimation(.easeOut(duration: 0.15)) { section = s }
        } label: {
            Image(systemName: symbol)
                .font(.system(size: 22, weight: .semibold))
                .foregroundStyle(on ? Color.black : Color.white.opacity(0.65))
                .frame(width: 50, height: 50)
                .background(on ? Color.white : Color.clear, in: Circle())
                .shadow(color: on ? .white.opacity(0.35) : .clear, radius: 10)
        }
        .buttonStyle(.plain)
    }
}
