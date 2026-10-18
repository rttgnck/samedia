import Foundation

// What the Samedia server sends. Fields are optional and decoded leniently: the server adds
// fields over time and older servers leave some out.

struct ServerInfo: Decodable {
    let name: String
    let version: String?
    let pinRequired: Bool
    let features: [String]

    enum CodingKeys: String, CodingKey { case name, version, pin_required, features }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = (try? c.decode(String.self, forKey: .name)) ?? "Samedia"
        version = try? c.decode(String.self, forKey: .version)
        pinRequired = (try? c.decode(Bool.self, forKey: .pin_required)) ?? false
        features = (try? c.decode([String].self, forKey: .features)) ?? []
    }
}

struct Profile: Codable, Identifiable, Hashable {
    let id: String
    var name: String
    var color: String?
    var kids: Bool?
    var avatar: String?
}

struct ProfilesResponse: Decodable { let profiles: [Profile] }

struct CastMember: Decodable, Hashable {
    let name: String
    let role: String?
}

/// A movie, episode, show or collection as it appears in lists.
struct MediaItem: Decodable, Identifiable, Hashable {
    let id: String
    let kind: String
    let title: String
    let year: Int?
    let duration: Double?
    let rating: Double?
    let plot: String?
    let genres: [String]
    let poster: String?
    let backdrop: String?
    let thumb: String?
    var position: Double?
    var watched: Bool
    let badges: [String]
    let certification: String?
    // shows and collections
    let episodeCount: Int?
    let unwatched: Int?
    let itemCount: Int?
    let years: String?
    // episodes
    let season: Int?
    let episode: Int?
    let showID: String?
    let showTitle: String?

    enum CodingKeys: String, CodingKey {
        case id, kind, title, year, duration, rating, plot, genres, poster, backdrop, thumb, position, watched,
             badges, certification, episode_count, unwatched, item_count, years, season, episode, show_id, show_title
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        kind = (try? c.decode(String.self, forKey: .kind)) ?? "movie"
        title = (try? c.decode(String.self, forKey: .title)) ?? ""
        year = try? c.decode(Int.self, forKey: .year)
        duration = try? c.decode(Double.self, forKey: .duration)
        rating = try? c.decode(Double.self, forKey: .rating)
        plot = try? c.decode(String.self, forKey: .plot)
        genres = (try? c.decode([String].self, forKey: .genres)) ?? []
        poster = try? c.decode(String.self, forKey: .poster)
        backdrop = try? c.decode(String.self, forKey: .backdrop)
        thumb = try? c.decode(String.self, forKey: .thumb)
        position = try? c.decode(Double.self, forKey: .position)
        watched = (try? c.decode(Bool.self, forKey: .watched)) ?? false
        badges = (try? c.decode([String].self, forKey: .badges)) ?? []
        certification = try? c.decode(String.self, forKey: .certification)
        episodeCount = try? c.decode(Int.self, forKey: .episode_count)
        unwatched = try? c.decode(Int.self, forKey: .unwatched)
        itemCount = try? c.decode(Int.self, forKey: .item_count)
        years = (try? c.decode(String.self, forKey: .years)) ?? (try? c.decode(Int.self, forKey: .years)).map(String.init)
        season = try? c.decode(Int.self, forKey: .season)
        episode = try? c.decode(Int.self, forKey: .episode)
        showID = try? c.decode(String.self, forKey: .show_id)
        showTitle = try? c.decode(String.self, forKey: .show_title)
    }

    var isPlayable: Bool { kind == "movie" || kind == "episode" }

    /// Seconds to resume from, or nil to start at the beginning (matches the TV app and server).
    var resumeAt: Double? {
        guard !watched, let p = position, p >= 20 else { return nil }
        if let d = duration, p > d * 0.95 { return nil }
        return p
    }

    var episodeLabel: String? {
        guard let s = season, let e = episode else { return nil }
        return "S\(s) · E\(e)"
    }
}

struct Shelf: Decodable, Identifiable {
    let id: String
    let title: String
    let items: [MediaItem]
}

struct Home: Decodable {
    let shelves: [Shelf]
}

struct ItemList: Decodable {
    let items: [MediaItem]
    let genres: [String]?
}

struct SearchResults: Decodable {
    let movies: [MediaItem]
    let shows: [MediaItem]
    let episodes: [MediaItem]

    enum CodingKeys: String, CodingKey { case movies, shows, episodes }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        movies = (try? c.decode([MediaItem].self, forKey: .movies)) ?? []
        shows = (try? c.decode([MediaItem].self, forKey: .shows)) ?? []
        episodes = (try? c.decode([MediaItem].self, forKey: .episodes)) ?? []
    }
}

/// One movie or episode with everything the detail screen shows.
struct ItemDetail: Decodable {
    let item: MediaItem
    let tagline: String?
    let director: String?
    let cast: [CastMember]
    let next: MediaItem?

    enum CodingKeys: String, CodingKey { case tagline, director, cast, next }
    init(from decoder: Decoder) throws {
        item = try MediaItem(from: decoder)
        let c = try decoder.container(keyedBy: CodingKeys.self)
        tagline = try? c.decode(String.self, forKey: .tagline)
        director = try? c.decode(String.self, forKey: .director)
        cast = (try? c.decode([CastMember].self, forKey: .cast)) ?? []
        next = try? c.decode(MediaItem.self, forKey: .next)
    }
}

struct Season: Decodable, Hashable {
    let season: Int
    let episodeCount: Int?
    let unwatched: Int?
    enum CodingKeys: String, CodingKey { case season, episode_count, unwatched }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        season = (try? c.decode(Int.self, forKey: .season)) ?? 0
        episodeCount = try? c.decode(Int.self, forKey: .episode_count)
        unwatched = try? c.decode(Int.self, forKey: .unwatched)
    }
}

struct ShowDetail: Decodable {
    let show: MediaItem
    let seasons: [Season]
    let episodes: [MediaItem]
    let nextUp: MediaItem?
    enum CodingKeys: String, CodingKey { case seasons, episodes, next_up }
    init(from decoder: Decoder) throws {
        show = try MediaItem(from: decoder)
        let c = try decoder.container(keyedBy: CodingKeys.self)
        seasons = (try? c.decode([Season].self, forKey: .seasons)) ?? []
        episodes = (try? c.decode([MediaItem].self, forKey: .episodes)) ?? []
        nextUp = try? c.decode(MediaItem.self, forKey: .next_up)
    }
}

struct CollectionDetail: Decodable {
    let collection: MediaItem
    let items: [MediaItem]
    enum CodingKeys: String, CodingKey { case items }
    init(from decoder: Decoder) throws {
        collection = try MediaItem(from: decoder)
        let c = try decoder.container(keyedBy: CodingKeys.self)
        items = (try? c.decode([MediaItem].self, forKey: .items)) ?? []
    }
}

struct PlaybackDecision: Decodable {
    let mode: String
    let url: String
    let startOffset: Double
    let seekable: Bool
    let duration: Double?
    let session: String?
    let warnings: [String]
    enum CodingKeys: String, CodingKey { case mode, url, start_offset, seekable, duration, session, warnings }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        mode = try c.decode(String.self, forKey: .mode)
        url = try c.decode(String.self, forKey: .url)
        startOffset = (try? c.decode(Double.self, forKey: .start_offset)) ?? 0
        seekable = (try? c.decode(Bool.self, forKey: .seekable)) ?? false
        duration = try? c.decode(Double.self, forKey: .duration)
        session = try? c.decode(String.self, forKey: .session)
        warnings = (try? c.decode([String].self, forKey: .warnings)) ?? []
    }
}

struct ProgressReply: Decodable {
    let position: Double?
    let watched: Bool?
}

/// Formatting shared by the screens.
enum Format {
    /// 3725 -> "1:02:05", 65 -> "1:05"
    static func clock(_ seconds: Double) -> String {
        let s = max(0, Int(seconds))
        let h = s / 3600, m = (s % 3600) / 60, sec = s % 60
        return h > 0 ? String(format: "%d:%02d:%02d", h, m, sec) : String(format: "%d:%02d", m, sec)
    }

    /// 6300 -> "1h 45m"
    static func runtime(_ seconds: Double?) -> String? {
        guard let seconds, seconds > 0 else { return nil }
        let m = Int((seconds / 60).rounded())
        if m < 60 { return "\(m)m" }
        return m % 60 == 0 ? "\(m / 60)h" : "\(m / 60)h \(m % 60)m"
    }

    static func meta(_ item: MediaItem) -> String {
        var bits: [String] = []
        if let y = item.year { bits.append(String(y)) }
        if let c = item.certification, !c.isEmpty { bits.append(c) }
        if item.kind == "show", let n = item.episodeCount { bits.append("\(n) episodes") }
        else if item.kind == "collection", let n = item.itemCount { bits.append("\(n) movies") }
        else if let r = runtime(item.duration) { bits.append(r) }
        if let r = item.rating, r > 0 { bits.append(String(format: "★ %.1f", r)) }
        return bits.joined(separator: "  ·  ")
    }

    /// "47:12 of 1:35:42 · 48m left"
    static func progress(_ item: MediaItem) -> String? {
        guard let at = item.resumeAt, let d = item.duration else { return nil }
        return "\(clock(at)) of \(clock(d))  ·  \(runtime(d - at) ?? "") left"
    }
}
