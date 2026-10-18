import SwiftUI

/// A movie or an episode: art, how far in, play/resume, plot and credits.
struct DetailView: View {
    @Environment(AppModel.self) private var model
    let item: MediaItem
    @State private var detail: ItemDetail?
    @State private var error: String?

    private var current: MediaItem { detail?.item ?? item }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                header
                VStack(alignment: .leading, spacing: 18) {
                    if let plot = current.plot, !plot.isEmpty {
                        Text(plot).font(.body).foregroundStyle(.secondary).frame(maxWidth: 820, alignment: .leading)
                    }
                    credits
                    if let next = detail?.next {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Next episode").font(.headline)
                            EpisodeRow(episode: next)
                        }
                    }
                    if let error { Text(error).foregroundStyle(.red) }
                }
                .padding(28).padding(.leading, Rail.width - 28)
            }
        }
        .ignoresSafeArea(edges: .top)
        .background(Color.black)
        .navigationBarTitleDisplayMode(.inline)
        .task(id: model.refreshToken) { await load() }
    }

    private func load() async {
        guard let api = model.api else { return }
        do {
            detail = try await api.get("/api/v1/items/\(item.id)", as: ItemDetail.self)
        } catch {
            self.error = error.localizedDescription
        }
    }

    private var header: some View {
        ZStack(alignment: .bottomLeading) {
            RemoteImage(url: model.api?.art(current.backdrop ?? current.poster, width: 1920))
                .frame(height: 460).frame(maxWidth: .infinity).clipped()
                .overlay(LinearGradient(colors: [.clear, .black.opacity(0.5), .black], startPoint: .top, endPoint: .bottom))
            HStack(alignment: .bottom, spacing: 26) {
                PosterView(item: current, width: 500, showProgress: false)
                    .frame(width: 190, height: 285).shadow(radius: 20)
                VStack(alignment: .leading, spacing: 10) {
                    if let show = current.showTitle, let ep = current.episodeLabel {
                        Text("\(show)  ·  \(ep)").font(.headline).foregroundStyle(.secondary)
                    }
                    Text(current.title).font(.system(size: 40, weight: .heavy)).lineLimit(2)
                    if let tagline = detail?.tagline, !tagline.isEmpty {
                        Text(tagline).italic().foregroundStyle(.secondary)
                    }
                    HStack(spacing: 10) {
                        Text(Format.meta(current)).foregroundStyle(.secondary)
                        ForEach(current.badges, id: \.self) { b in
                            Text(b).font(.caption.weight(.bold)).padding(.horizontal, 6).padding(.vertical, 2)
                                .overlay(RoundedRectangle(cornerRadius: 4).stroke(.secondary))
                                .foregroundStyle(.secondary)
                        }
                    }
                    WatchStateLine(item: current)
                    buttons.padding(.top, 6)
                }
            }
            .padding(28).padding(.leading, Rail.width - 28)
        }
    }

    private var buttons: some View {
        HStack(spacing: 12) {
            Button {
                model.play(current, from: current.resumeAt)
            } label: {
                Label(current.resumeAt.map { "Resume \(Format.clock($0))" } ?? "Play", systemImage: "play.fill")
                    .frame(minWidth: 140)
            }
            .buttonStyle(.borderedProminent).controlSize(.large)
            if current.resumeAt != nil {
                Button { model.play(current, from: nil) } label: {
                    Label("Start over", systemImage: "backward.end.fill")
                }
                .buttonStyle(.bordered).controlSize(.large)
            }
            PlayOnButton(item: current, position: current.resumeAt)
            Button {
                Task { await model.setWatched(current, !current.watched) }
            } label: {
                Label(current.watched ? "Mark unwatched" : "Mark watched",
                      systemImage: current.watched ? "eye.slash" : "checkmark")
            }
            .buttonStyle(.bordered).controlSize(.large)
        }
    }

    @ViewBuilder
    private var credits: some View {
        if let director = detail?.director, !director.isEmpty {
            Text("Director  ").font(.caption.weight(.bold)).foregroundStyle(.tertiary) + Text(director)
        }
        if let cast = detail?.cast, !cast.isEmpty {
            VStack(alignment: .leading, spacing: 4) {
                Text("CAST").font(.caption.weight(.bold)).foregroundStyle(.tertiary)
                Text(cast.prefix(10).map { member in member.role.map { "\(member.name) (\($0))" } ?? member.name }.joined(separator: ", "))
                    .foregroundStyle(.secondary).frame(maxWidth: 820, alignment: .leading)
            }
        }
    }
}

struct EpisodeRow: View {
    @Environment(AppModel.self) private var model
    let episode: MediaItem

    var body: some View {
        Button {
            model.play(episode, from: episode.resumeAt)
        } label: {
            HStack(spacing: 16) {
                ZStack(alignment: .bottom) {
                    Color(white: 0.15)
                    RemoteImage(url: model.api?.art(episode.thumb ?? episode.backdrop ?? episode.poster, width: 480))
                    if let at = episode.resumeAt, let d = episode.duration, d > 0 {
                        ProgressBar(value: at / d).frame(height: 4).padding(6)
                    }
                    Image(systemName: "play.circle.fill").font(.largeTitle).foregroundStyle(.white.opacity(0.85))
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
                .frame(width: 200, height: 112).clipShape(RoundedRectangle(cornerRadius: 8))
                VStack(alignment: .leading, spacing: 5) {
                    HStack {
                        if let ep = episode.episodeLabel { Text(ep).font(.caption.weight(.bold)).foregroundStyle(.tint) }
                        if episode.watched { Image(systemName: "checkmark").font(.caption.bold()).foregroundStyle(.green) }
                    }
                    Text(episode.title).font(.headline).lineLimit(1)
                    if let plot = episode.plot { Text(plot).font(.subheadline).foregroundStyle(.secondary).lineLimit(2) }
                    Text([Format.runtime(episode.duration), Format.progress(episode)].compactMap { $0 }.joined(separator: "  ·  "))
                        .font(.caption).foregroundStyle(.tertiary)
                }
                Spacer(minLength: 0)
            }
            .contentShape(Rectangle())
            .padding(.horizontal, 20).padding(.leading, Rail.width - 20).padding(.vertical, 8)
        }
        .buttonStyle(.plain)
        .contextMenu {
            Button(episode.watched ? "Mark unwatched" : "Mark watched", systemImage: "checkmark") {
                Task { await model.setWatched(episode, !episode.watched) }
            }
            if episode.resumeAt != nil {
                Button("Start over", systemImage: "backward.end") { model.play(episode, from: nil) }
            }
        }
    }
}

/// A show: seasons and their episodes.
struct ShowView: View {
    @Environment(AppModel.self) private var model
    let show: MediaItem
    @State private var detail: ShowDetail?
    @State private var season: Int?
    @State private var error: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                ZStack(alignment: .bottomLeading) {
                    RemoteImage(url: model.api?.art(show.backdrop ?? show.poster, width: 1920))
                        .frame(height: 360).frame(maxWidth: .infinity).clipped()
                        .overlay(LinearGradient(colors: [.clear, .black], startPoint: .center, endPoint: .bottom))
                    VStack(alignment: .leading, spacing: 8) {
                        Text(show.title).font(.system(size: 40, weight: .heavy))
                        Text(Format.meta(detail?.show ?? show)).foregroundStyle(.secondary)
                        if let next = detail?.nextUp {
                            Button {
                                model.play(next, from: next.resumeAt)
                            } label: {
                                Label(next.resumeAt != nil ? "Resume \(next.episodeLabel ?? "")" : "Play \(next.episodeLabel ?? "")",
                                      systemImage: "play.fill")
                            }
                            .buttonStyle(.borderedProminent).controlSize(.large).padding(.top, 4)
                        }
                    }
                    .padding(28).padding(.leading, Rail.width - 28)
                }
                if let plot = (detail?.show ?? show).plot {
                    Text(plot).foregroundStyle(.secondary).padding(.horizontal, 28).padding(.leading, Rail.width - 28).frame(maxWidth: 860, alignment: .leading)
                }
                if let detail {
                    if detail.seasons.count > 1 {
                        Picker("Season", selection: Binding(get: { season ?? detail.seasons.first?.season ?? 1 }, set: { season = $0 })) {
                            ForEach(detail.seasons, id: \.season) { s in
                                Text(s.season == 0 ? "Specials" : "Season \(s.season)").tag(s.season)
                            }
                        }
                        .pickerStyle(.segmented).padding(.horizontal, 28).padding(.leading, Rail.width - 28)
                    }
                    let current = season ?? detail.nextUp?.season ?? detail.seasons.first?.season
                    ForEach(detail.episodes.filter { current == nil || $0.season == current }) { ep in
                        EpisodeRow(episode: ep)
                    }
                } else if let error {
                    Text(error).foregroundStyle(.red).padding(28).padding(.leading, Rail.width - 28)
                } else {
                    ProgressView().frame(maxWidth: .infinity).padding(40)
                }
            }
            .padding(.bottom, 30)
        }
        .ignoresSafeArea(edges: .top)
        .background(Color.black)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Button("Mark show watched", systemImage: "checkmark") { Task { await model.setWatched(show, true) } }
                    Button("Mark show unwatched", systemImage: "eye.slash") { Task { await model.setWatched(show, false) } }
                } label: { Image(systemName: "ellipsis.circle") }
            }
        }
        .task(id: model.refreshToken) {
            guard let api = model.api else { return }
            do {
                let d = try await api.get("/api/v1/shows/\(show.id)", as: ShowDetail.self)
                detail = d
                if season == nil { season = d.nextUp?.season ?? d.seasons.first?.season }
            } catch {
                self.error = error.localizedDescription
            }
        }
    }
}

/// A franchise or folder of movies.
struct CollectionView: View {
    @Environment(AppModel.self) private var model
    let collection: MediaItem
    @State private var detail: CollectionDetail?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 6) {
                Text(collection.title).font(.largeTitle.bold())
                Text([collection.years, collection.itemCount.map { "\($0) movies" }].compactMap { $0 }.joined(separator: "  ·  "))
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 20).padding(.leading, Rail.width - 20).padding(.top, 10)
            if let detail { PosterGrid(items: detail.items) } else { ProgressView().padding(40) }
        }
        .navigationBarTitleDisplayMode(.inline)
        .task(id: model.refreshToken) {
            detail = try? await model.api?.get("/api/v1/collections/\(collection.id)", as: CollectionDetail.self)
        }
    }
}
