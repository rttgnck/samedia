import SwiftUI

/// Home: the server's shelves (Continue Watching, New Movies, ...) as tabs over a Cover Flow.
struct HomeView: View {
    @Environment(AppModel.self) private var model
    @State private var home: Home?
    @State private var shelfID: String?
    @State private var centered: String?
    @State private var error: String?
    @State private var path: [ItemRoute] = []

    private var shelf: Shelf? { home?.shelves.first { $0.id == shelfID } ?? home?.shelves.first }
    private var focused: MediaItem? { shelf?.items.first { $0.id == centered } ?? shelf?.items.first }

    var body: some View {
        NavigationStack(path: $path) { content }
    }

    private var content: some View {
        VStack(spacing: 0) {
            if let home {
                shelfTabs(home.shelves)
                if let shelf, !shelf.items.isEmpty {
                    CoverFlowView(items: shelf.items, centered: $centered) { open($0) }
                        .id(shelf.id)
                    if let item = focused { caption(item) }
                } else {
                    ContentUnavailableView("Nothing here yet", systemImage: "film.stack")
                }
            } else if let error {
                ErrorBox(message: error) { Task { await load() } }
            } else {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .background(backdrop)
        .navigationTitle(model.info?.name.capitalized ?? "Samedia")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                if let p = model.profile {
                    Menu {
                        Button("Switch profile", systemImage: "person.2") { model.switchProfile() }
                        Button("Use a different server", systemImage: "server.rack") { model.forgetServer() }
                    } label: {
                        HStack(spacing: 8) { AvatarView(profile: p, size: 30); Text(p.name) }
                    }
                }
            }
        }
        .navigationDestination(for: ItemRoute.self) { destination(for: $0) }
        .task(id: model.refreshToken) { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        guard let api = model.api else { return }
        do {
            let fresh = try await api.get("/api/v1/home", as: Home.self)
            error = nil
            home = fresh
            if shelfID == nil || !fresh.shelves.contains(where: { $0.id == shelfID }) { shelfID = fresh.shelves.first?.id }
        } catch {
            if home == nil { self.error = error.localizedDescription }
        }
    }

    private func open(_ item: MediaItem) {
        if item.isPlayable, item.resumeAt != nil {
            model.play(item, from: item.resumeAt)
        } else {
            path.append(ItemRoute(item: item))
        }
    }

    private func shelfTabs(_ shelves: [Shelf]) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                ForEach(shelves) { s in
                    Button {
                        withAnimation(.snappy) { shelfID = s.id; centered = s.items.first?.id }
                    } label: {
                        Text(s.title).font(.subheadline.weight(.semibold))
                            .padding(.horizontal, 16).padding(.vertical, 8)
                            .background(s.id == shelf?.id ? Color.white : Color.white.opacity(0.1), in: Capsule())
                            .foregroundStyle(s.id == shelf?.id ? Color.black : Color.white)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 24).padding(.vertical, 12)
        }
        .frame(height: 60)          // or the Cover Flow below squeezes it away
    }

    @ViewBuilder
    private func caption(_ item: MediaItem) -> some View {
        VStack(spacing: 10) {
            Text(item.title).font(.title.bold()).lineLimit(1)
            if let ep = item.episodeLabel, let show = item.showTitle {
                Text("\(show)  ·  \(ep)").foregroundStyle(.secondary)
            }
            Text(Format.meta(item)).font(.subheadline).foregroundStyle(.secondary)
            WatchStateLine(item: item)
            HStack(spacing: 12) {
                if item.isPlayable {
                    Button {
                        model.play(item, from: item.resumeAt)
                    } label: {
                        Label(item.resumeAt != nil ? "Resume" : "Play", systemImage: "play.fill").frame(minWidth: 120)
                    }
                    .buttonStyle(.borderedProminent).controlSize(.large)
                }
                NavigationLink(value: ItemRoute(item: item)) {
                    Label(item.kind == "show" ? "Episodes" : item.kind == "collection" ? "All movies" : "Details",
                          systemImage: "info.circle").frame(minWidth: 120)
                }
                .buttonStyle(.bordered).controlSize(.large)
            }
            .padding(.top, 4)
        }
        .padding(.horizontal, 24).padding(.bottom, 28).padding(.top, 8)
        .animation(.default, value: item.id)
    }

    @ViewBuilder
    private var backdrop: some View {
        ZStack {
            Color.black
            if let item = focused {
                RemoteImage(url: model.api?.art(item.backdrop ?? item.poster, width: 1280))
                    .blur(radius: 40).opacity(0.45)
                    .animation(.easeInOut(duration: 0.4), value: item.id)
            }
            LinearGradient(colors: [.black.opacity(0.2), .black.opacity(0.85)], startPoint: .top, endPoint: .bottom)
        }
        .ignoresSafeArea()
    }
}

/// Posters in a row that tilt away from the centre one, like Cover Flow.
struct CoverFlowView: View {
    let items: [MediaItem]
    @Binding var centered: String?
    var onOpen: (MediaItem) -> Void

    var body: some View {
        GeometryReader { geo in
            let height = min(geo.size.height * 0.86, 560)
            let width = height * 2 / 3
            let centerIndex = items.firstIndex { $0.id == centered } ?? 0
            ScrollView(.horizontal, showsIndicators: false) {
                LazyHStack(spacing: -width * 0.32) {
                    ForEach(Array(items.enumerated()), id: \.element.id) { index, item in
                        PosterView(item: item, width: 600)
                            .frame(width: width, height: height)
                            .shadow(color: .black.opacity(0.6), radius: 20, y: 12)
                            .scrollTransition(.interactive, axis: .horizontal) { content, phase in
                                content
                                    .rotation3DEffect(.degrees(phase.value * -58), axis: (x: 0, y: 1, z: 0),
                                                      anchor: phase.value < 0 ? .trailing : .leading, perspective: 0.45)
                                    .scaleEffect(1 - min(abs(phase.value), 1) * 0.16)
                                    .brightness(-min(abs(phase.value), 1) * 0.25)
                            }
                            .zIndex(-Double(abs(index - centerIndex)))
                            .onTapGesture {
                                if item.id == (centered ?? items.first?.id) {
                                    onOpen(item)
                                } else {
                                    withAnimation(.snappy) { centered = item.id }
                                }
                            }
                            .id(item.id)
                    }
                }
                .scrollTargetLayout()
                .frame(height: geo.size.height)
            }
            .contentMargins(.horizontal, (geo.size.width - width) / 2, for: .scrollContent)
            .scrollTargetBehavior(.viewAligned)
            .scrollPosition(id: $centered, anchor: .center)
            .onAppear { if centered == nil || !items.contains(where: { $0.id == centered }) { centered = items.first?.id } }
        }
        .frame(minHeight: 300)
    }
}
