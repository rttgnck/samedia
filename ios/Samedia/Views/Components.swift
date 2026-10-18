import SwiftUI
import UIKit

/// Decoded artwork kept in memory (the URL cache keeps the bytes on disk).
@MainActor
final class ImageCache {
    static let shared = ImageCache()
    private let cache = NSCache<NSURL, UIImage>()
    private var inflight: [URL: Task<UIImage?, Never>] = [:]

    init() { cache.countLimit = 400 }

    func cached(_ url: URL) -> UIImage? { cache.object(forKey: url as NSURL) }

    func image(for url: URL) async -> UIImage? {
        if let hit = cache.object(forKey: url as NSURL) { return hit }
        if let running = inflight[url] { return await running.value }
        let task = Task<UIImage?, Never> {
            guard let (data, response) = try? await APIClient.session.data(from: url),
                  (response as? HTTPURLResponse)?.statusCode == 200,
                  let image = UIImage(data: data) else { return nil }
            return image.preparingForDisplay() ?? image
        }
        inflight[url] = task
        let image = await task.value
        inflight[url] = nil
        if let image { cache.setObject(image, forKey: url as NSURL) }
        return image
    }
}

struct RemoteImage: View {
    let url: URL?
    var contentMode: ContentMode = .fill
    @State private var image: UIImage?

    var body: some View {
        ZStack {
            if let image {
                Image(uiImage: image).resizable().aspectRatio(contentMode: contentMode)
            }
        }
        .task(id: url) {
            guard let url else { image = nil; return }
            if let hit = ImageCache.shared.cached(url) { image = hit; return }
            image = await ImageCache.shared.image(for: url)
        }
    }
}

/// A poster with its title as the stand-in until (or unless) there is art.
struct PosterView: View {
    @Environment(AppModel.self) private var model
    let item: MediaItem
    var width: Int = 500
    var showProgress = true

    var body: some View {
        ZStack(alignment: .bottom) {
            LinearGradient(colors: [Color(white: 0.2), Color(white: 0.1)], startPoint: .top, endPoint: .bottom)
            Text(item.title)
                .font(.headline).multilineTextAlignment(.center).foregroundStyle(.secondary)
                .padding(12).frame(maxWidth: .infinity, maxHeight: .infinity)
            RemoteImage(url: model.api?.art(item.poster, width: width))
            if showProgress, let at = item.resumeAt, let d = item.duration, d > 0 {
                ProgressBar(value: at / d).frame(height: 5).padding(8)
            }
        }
        .overlay(alignment: .topTrailing) {
            if item.watched {
                Image(systemName: "checkmark.circle.fill")
                    .font(.title3).symbolRenderingMode(.palette).foregroundStyle(.black, .green)
                    .padding(8)
            } else if let n = item.unwatched, n > 0, item.kind != "movie" {
                Text("\(n)").font(.caption.bold()).padding(.horizontal, 8).padding(.vertical, 3)
                    .background(.tint, in: Capsule()).foregroundStyle(.white).padding(8)
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}

struct ProgressBar: View {
    let value: Double
    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(.white.opacity(0.25))
                Capsule().fill(.tint).frame(width: max(4, geo.size.width * min(1, max(0, value))))
            }
        }
    }
}

/// A profile's picture, or its initial on its color.
struct AvatarView: View {
    let profile: Profile
    var size: CGFloat = 44

    var body: some View {
        ZStack {
            Circle().fill(Color(hex: profile.color) ?? .accentColor)
            if let avatar = profile.avatar, UIImage(named: "avatar-\(avatar)") != nil {
                Image("avatar-\(avatar)").resizable().scaledToFill()
            } else {
                Text(profile.name.prefix(1).uppercased())
                    .font(.system(size: size * 0.45, weight: .heavy)).foregroundStyle(.white)
            }
        }
        .frame(width: size, height: size)
        .clipShape(Circle())
    }
}

struct WatchStateLine: View {
    let item: MediaItem
    var body: some View {
        if let text = Format.progress(item), let at = item.resumeAt, let d = item.duration {
            VStack(alignment: .leading, spacing: 6) {
                Text(text).font(.subheadline.weight(.semibold)).monospacedDigit()
                ProgressBar(value: at / d).frame(width: 260, height: 5)
            }
        } else if item.watched {
            Label("Watched", systemImage: "checkmark").font(.subheadline.weight(.semibold)).foregroundStyle(.green)
        }
    }
}

extension Color {
    init?(hex: String?) {
        guard var s = hex?.trimmingCharacters(in: .whitespaces), s.hasPrefix("#"), s.count == 7 else { return nil }
        s.removeFirst()
        guard let v = UInt32(s, radix: 16) else { return nil }
        self.init(red: Double((v >> 16) & 0xff) / 255, green: Double((v >> 8) & 0xff) / 255, blue: Double(v & 0xff) / 255)
    }
}

/// Where tapping a title goes.
struct ItemRoute: Hashable {
    let item: MediaItem
}

@ViewBuilder
func destination(for route: ItemRoute) -> some View {
    switch route.item.kind {
    case "show": ShowView(show: route.item)
    case "collection": CollectionView(collection: route.item)
    default: DetailView(item: route.item)
    }
}

/// Lays its views out in rows, each row centred (a few profiles sit in the middle, many wrap).
struct CenteredFlow: Layout {
    var spacing: CGFloat = 24

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = rows(for: subviews, width: proposal.width ?? .infinity)
        let height = rows.reduce(0) { $0 + $1.height } + spacing * CGFloat(max(rows.count - 1, 0))
        return CGSize(width: proposal.width ?? rows.map(\.width).max() ?? 0, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for row in rows(for: subviews, width: bounds.width) {
            var x = bounds.midX - row.width / 2
            for i in row.indices {
                let size = subviews[i].sizeThatFits(.unspecified)
                subviews[i].place(at: CGPoint(x: x, y: y), proposal: .unspecified)      // tops line up
                x += size.width + spacing
            }
            y += row.height + spacing
        }
    }

    private struct Row { var indices: [Int] = []; var width: CGFloat = 0; var height: CGFloat = 0 }

    private func rows(for subviews: Subviews, width: CGFloat) -> [Row] {
        var rows: [Row] = [Row()]
        for (i, view) in subviews.enumerated() {
            let size = view.sizeThatFits(.unspecified)
            var row = rows[rows.count - 1]
            if !row.indices.isEmpty && row.width + spacing + size.width > width {
                rows.append(Row())
                row = Row()
            }
            row.width = row.indices.isEmpty ? size.width : row.width + spacing + size.width
            row.height = max(row.height, size.height)
            row.indices.append(i)
            rows[rows.count - 1] = row
        }
        return rows.filter { !$0.indices.isEmpty }
    }
}

struct ErrorBox: View {
    let message: String
    var retry: (() -> Void)?
    var body: some View {
        ContentUnavailableView {
            Label("Something went wrong", systemImage: "exclamationmark.triangle")
        } description: {
            Text(message)
        } actions: {
            if let retry { Button("Try again", action: retry).buttonStyle(.borderedProminent) }
        }
    }
}
