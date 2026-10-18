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
        .toolbar(.hidden, for: .navigationBar)
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

/// Cover Flow, as on the TV: the centre cover faces you, the others fan out on both sides
/// facing it. Drags move sideways only and settle on a cover; tapping a side cover brings it
/// to the centre, tapping the centre one opens it.
struct CoverFlowView: View {
    let items: [MediaItem]
    @Binding var centered: String?
    var onOpen: (MediaItem) -> Void

    @State private var position: CGFloat = 0          // index of the centre, fractional while dragging
    @State private var dragStart: CGFloat?
    @State private var lastTick = 0
    private let tick = UISelectionFeedbackGenerator()

    var body: some View {
        GeometryReader { geo in
            let height = min(geo.size.height * 0.72, 520)
            let width = height * 2 / 3
            let gap = width * 0.78                       // centre cover to the first side cover
            let step = width * 0.24                      // between side covers
            let perItem = max(step * 1.4, 70)            // drag distance that moves one cover
            ZStack {
                ForEach(visible, id: \.self) { i in
                    let p = CGFloat(i) - position
                    cover(items[i], width: width, height: height)
                        .rotation3DEffect(.degrees(Double(-max(-1, min(1, p)) * 64)), axis: (x: 0, y: 1, z: 0),
                                          perspective: 0.5)
                        .scaleEffect(1 - min(abs(p), 1) * 0.12)
                        .brightness(-Double(min(abs(p), 1.5)) * 0.18)
                        .offset(x: abs(p) <= 1 ? p * gap : (p > 0 ? 1 : -1) * (gap + (abs(p) - 1) * step))
                        .zIndex(-Double(abs(p)))
                        .onTapGesture { tap(i) }
                }
            }
            .frame(width: geo.size.width, height: geo.size.height)
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 8)
                    .onChanged { g in
                        if dragStart == nil { dragStart = position; tick.prepare() }
                        let raw = (dragStart ?? 0) - g.translation.width / perItem
                        position = min(max(raw, -0.35), CGFloat(items.count - 1) + 0.35)
                        let nearest = Int(position.rounded())
                        if nearest != lastTick { lastTick = nearest; tick.selectionChanged() }
                    }
                    .onEnded { g in
                        let flung = (dragStart ?? position) - g.predictedEndTranslation.width / perItem
                        dragStart = nil
                        settle(on: Int(flung.rounded()))
                    }
            )
        }
        .frame(minHeight: 320)
        .onAppear {
            position = CGFloat(items.firstIndex { $0.id == centered } ?? 0)
            lastTick = Int(position)
            if centered == nil { centered = items.first?.id }
        }
        .onChange(of: centered) { _, id in
            // moved from outside (e.g. another shelf): follow without a jump if it's already there
            if let i = items.firstIndex(where: { $0.id == id }), Int(position.rounded()) != i, dragStart == nil {
                withAnimation(.spring(response: 0.4, dampingFraction: 0.88)) { position = CGFloat(i) }
            }
        }
    }

    /// The covers worth drawing: those near the centre.
    private var visible: [Int] {
        guard !items.isEmpty else { return [] }
        let c = Int(position.rounded())
        return Array(max(0, c - 7)...min(items.count - 1, c + 7))
    }

    private func settle(on index: Int) {
        let target = min(max(index, 0), items.count - 1)
        withAnimation(.spring(response: 0.38, dampingFraction: 0.86)) { position = CGFloat(target) }
        centered = items[target].id
        if target != lastTick { lastTick = target; tick.selectionChanged() }
    }

    private func tap(_ i: Int) {
        if i == Int(position.rounded()) { onOpen(items[i]) } else { settle(on: i) }
    }

    private func cover(_ item: MediaItem, width: CGFloat, height: CGFloat) -> some View {
        VStack(spacing: 6) {
            PosterView(item: item, width: 600)
                .frame(width: width, height: height)
                .shadow(color: .black.opacity(0.55), radius: 18, y: 10)
            // reflection
            PosterView(item: item, width: 600, showProgress: false)
                .frame(width: width, height: height)
                .scaleEffect(x: 1, y: -1)
                .frame(width: width, height: height * 0.22, alignment: .top)
                .clipped()
                .mask(LinearGradient(colors: [.white.opacity(0.28), .clear], startPoint: .top, endPoint: .bottom))
                .allowsHitTesting(false)
        }
    }
}
