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

struct MainView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        TabView {
            Tab("Home", systemImage: "house") { HomeView() }
            Tab("Movies", systemImage: "film") { NavigationStack { LibraryView(kind: .movies) } }
            Tab("TV Shows", systemImage: "tv") { NavigationStack { LibraryView(kind: .shows) } }
            Tab(role: .search) { NavigationStack { SearchView() } }
        }
        .tabViewStyle(.sidebarAdaptable)
        // Back in the app: another device may have watched something meanwhile
        .onChange(of: scenePhase) { _, phase in if phase == .active { model.refreshToken += 1 } }
    }
}
