import SwiftUI

/// Movies or TV shows as a poster grid, with genre filters.
struct LibraryView: View {
    enum Kind { case movies, shows }
    @Environment(AppModel.self) private var model
    let kind: Kind
    @State private var list: ItemList?
    @State private var genre: String?
    @State private var error: String?

    private var items: [MediaItem] {
        guard let all = list?.items else { return [] }
        guard let genre else { return all }
        return all.filter { $0.genres.contains(genre) }
    }

    var body: some View {
        Group {
            if list != nil {
                ScrollView {
                    if let genres = list?.genres, !genres.isEmpty { genreBar(genres) }
                    PosterGrid(items: items)
                }
            } else if let error {
                ErrorBox(message: error) { Task { await load() } }
            } else {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .navigationTitle(kind == .movies ? "Movies" : "TV Shows")
        .navigationDestination(for: ItemRoute.self) { destination(for: $0) }
        .task(id: model.refreshToken) { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        guard let api = model.api else { return }
        do {
            list = try await api.get(kind == .movies ? "/api/v1/movies" : "/api/v1/shows", as: ItemList.self)
            error = nil
        } catch {
            if list == nil { self.error = error.localizedDescription }
        }
    }

    private func genreBar(_ genres: [String]) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                chip("All", selected: genre == nil) { genre = nil }
                ForEach(genres, id: \.self) { g in chip(g, selected: genre == g) { genre = g } }
            }
            .padding(.horizontal, 20).padding(.vertical, 8)
        }
    }

    private func chip(_ title: String, selected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(.subheadline.weight(.semibold)).padding(.horizontal, 14).padding(.vertical, 7)
                .background(selected ? Color.white : Color.white.opacity(0.1), in: Capsule())
                .foregroundStyle(selected ? Color.black : Color.white)
        }
        .buttonStyle(.plain)
    }
}

struct PosterGrid: View {
    let items: [MediaItem]
    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 150, maximum: 210), spacing: 18)], spacing: 22) {
            ForEach(items) { item in
                NavigationLink(value: ItemRoute(item: item)) {
                    VStack(alignment: .leading, spacing: 6) {
                        PosterView(item: item, width: 400).aspectRatio(2 / 3, contentMode: .fit)
                        Text(item.title).font(.subheadline.weight(.semibold)).lineLimit(1)
                        Text(item.year.map(String.init) ?? " ").font(.caption).foregroundStyle(.secondary)
                    }
                }
                .buttonStyle(.plain)
            }
        }
        .padding(20)
    }
}

struct SearchView: View {
    @Environment(AppModel.self) private var model
    @State private var query = ""
    @State private var results: SearchResults?

    var body: some View {
        ScrollView {
            if let r = results {
                if r.movies.isEmpty && r.shows.isEmpty && r.episodes.isEmpty {
                    ContentUnavailableView.search(text: query)
                }
                if !r.movies.isEmpty { section("Movies", r.movies) }
                if !r.shows.isEmpty { section("TV Shows", r.shows) }
                if !r.episodes.isEmpty {
                    VStack(alignment: .leading, spacing: 0) {
                        Text("Episodes").font(.title2.bold()).padding(.horizontal, 20)
                        ForEach(r.episodes) { ep in EpisodeRow(episode: ep) }
                    }
                }
            } else {
                ContentUnavailableView("Search your library", systemImage: "magnifyingglass",
                                       description: Text("Movies, shows and episodes."))
            }
        }
        .navigationTitle("Search")
        .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: "Titles")
        .navigationDestination(for: ItemRoute.self) { destination(for: $0) }
        .task(id: query) {
            let q = query.trimmingCharacters(in: .whitespaces)
            guard !q.isEmpty else { results = nil; return }
            try? await Task.sleep(for: .milliseconds(300))
            guard !Task.isCancelled, let api = model.api else { return }
            let encoded = q.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? q
            results = try? await api.get("/api/v1/search?q=\(encoded)", as: SearchResults.self)
        }
    }

    private func section(_ title: String, _ items: [MediaItem]) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(title).font(.title2.bold()).padding(.horizontal, 20).padding(.top, 12)
            PosterGrid(items: items)
        }
    }
}
