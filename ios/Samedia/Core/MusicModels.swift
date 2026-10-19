import Foundation

// Music on the Samedia server, Spotify through it, and locked screens (admin). Decoded leniently
// like the rest: every field but the id may be missing.

struct Track: Decodable, Identifiable, Hashable {
    let id: String
    let title: String
    let artist: String?
    let album: String?
    let albumID: String?
    let artistID: String?
    let track: Int?
    let duration: Double?
    let codec: String?
    let art: String?

    enum CodingKeys: String, CodingKey { case id, title, artist, album, album_id, artist_id, track, duration, codec, art }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = (try? c.decode(String.self, forKey: .title)) ?? ""
        artist = try? c.decode(String.self, forKey: .artist)
        album = try? c.decode(String.self, forKey: .album)
        albumID = try? c.decode(String.self, forKey: .album_id)
        artistID = try? c.decode(String.self, forKey: .artist_id)
        track = try? c.decode(Int.self, forKey: .track)
        duration = try? c.decode(Double.self, forKey: .duration)
        codec = try? c.decode(String.self, forKey: .codec)
        art = try? c.decode(String.self, forKey: .art)
    }
}

struct Album: Decodable, Identifiable, Hashable {
    let id: String
    let title: String
    let artist: String?
    let artistID: String?
    let year: Int?
    let genre: String?
    let trackCount: Int
    let duration: Double?
    let art: String?
    let tracks: [Track]

    enum CodingKeys: String, CodingKey { case id, title, artist, artist_id, year, genre, track_count, duration, art, tracks }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = (try? c.decode(String.self, forKey: .title)) ?? ""
        artist = try? c.decode(String.self, forKey: .artist)
        artistID = try? c.decode(String.self, forKey: .artist_id)
        year = try? c.decode(Int.self, forKey: .year)
        genre = try? c.decode(String.self, forKey: .genre)
        trackCount = (try? c.decode(Int.self, forKey: .track_count)) ?? 0
        duration = try? c.decode(Double.self, forKey: .duration)
        art = try? c.decode(String.self, forKey: .art)
        tracks = (try? c.decode([Track].self, forKey: .tracks)) ?? []
    }
}

struct Artist: Decodable, Identifiable, Hashable {
    let id: String
    let name: String
    let albumCount: Int
    let art: String?
    let albums: [Album]
    enum CodingKeys: String, CodingKey { case id, name, album_count, art, albums }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = (try? c.decode(String.self, forKey: .name)) ?? ""
        albumCount = (try? c.decode(Int.self, forKey: .album_count)) ?? 0
        art = try? c.decode(String.self, forKey: .art)
        albums = (try? c.decode([Album].self, forKey: .albums)) ?? []
    }
}

struct MusicShelf: Decodable, Identifiable { let id: String; let title: String; let items: [Album] }
struct MusicStats: Decodable { let albums: Int }
struct MusicHome: Decodable { let shelves: [MusicShelf]; let stats: MusicStats? }
struct AlbumList: Decodable { let albums: [Album] }
struct ArtistList: Decodable { let artists: [Artist] }
struct TrackList: Decodable { let tracks: [Track] }

struct MusicSearch: Decodable {
    let artists: [Artist]
    let albums: [Album]
    let tracks: [Track]
}

// ── Spotify ──

struct SpotifyStatus: Decodable {
    let connected: Bool
    let user: String?
    enum CodingKeys: String, CodingKey { case connected, user }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        connected = (try? c.decode(Bool.self, forKey: .connected)) ?? false
        user = try? c.decode(String.self, forKey: .user)
    }
}

struct SpotifyTrack: Decodable, Identifiable, Hashable {
    let id: String
    let uri: String?
    let title: String
    let artist: String?
    let duration: Double?
    let image: String?
    enum CodingKeys: String, CodingKey { case id, uri, title, artist, duration, image }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = (try? c.decode(String.self, forKey: .id)) ?? UUID().uuidString
        uri = try? c.decode(String.self, forKey: .uri)
        title = (try? c.decode(String.self, forKey: .title)) ?? ""
        artist = try? c.decode(String.self, forKey: .artist)
        duration = try? c.decode(Double.self, forKey: .duration)
        image = try? c.decode(String.self, forKey: .image)
    }
}

/// A playlist in a list ("tracks" is a count there) or opened ("tracks" are the songs).
struct SpotifyPlaylist: Decodable, Identifiable, Hashable {
    let id: String
    let uri: String?
    let title: String
    let owner: String?
    let image: String?
    let count: Int
    let tracks: [SpotifyTrack]
    enum CodingKeys: String, CodingKey { case id, uri, title, owner, image, tracks }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        uri = try? c.decode(String.self, forKey: .uri)
        title = (try? c.decode(String.self, forKey: .title)) ?? ""
        owner = try? c.decode(String.self, forKey: .owner)
        image = try? c.decode(String.self, forKey: .image)
        tracks = (try? c.decode([SpotifyTrack].self, forKey: .tracks)) ?? []
        count = (try? c.decode(Int.self, forKey: .tracks)) ?? tracks.count
    }
}

struct SpotifyPlaylists: Decodable { let playlists: [SpotifyPlaylist] }

struct SpotifyDevice: Decodable, Identifiable, Hashable {
    let id: String
    let name: String
    let type: String?
    let active: Bool?
}

struct SpotifyDevices: Decodable { let devices: [SpotifyDevice] }

struct SpotifySearch: Decodable {
    let tracks: [SpotifyTrack]
    let playlists: [SpotifyPlaylist]
    enum CodingKeys: String, CodingKey { case tracks, playlists }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        tracks = (try? c.decode([SpotifyTrack].self, forKey: .tracks)) ?? []
        playlists = (try? c.decode([SpotifyPlaylist].self, forKey: .playlists)) ?? []
    }
}

// ── locking screens ──

struct DeviceLock: Codable {
    var profile: String
    var musicOnly: Bool = true
    var albums: [String] = []
    var artists: [String] = []
    var playlists: [String] = []
    enum CodingKeys: String, CodingKey { case profile, music_only, albums, artists, playlists }
    init(profile: String) { self.profile = profile }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        profile = try c.decode(String.self, forKey: .profile)
        musicOnly = (try? c.decode(Bool.self, forKey: .music_only)) ?? true
        albums = (try? c.decode([String].self, forKey: .albums)) ?? []
        artists = (try? c.decode([String].self, forKey: .artists)) ?? []
        playlists = (try? c.decode([String].self, forKey: .playlists)) ?? []
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(profile, forKey: .profile); try c.encode(musicOnly, forKey: .music_only)
        try c.encode(albums, forKey: .albums); try c.encode(artists, forKey: .artists); try c.encode(playlists, forKey: .playlists)
    }
}

struct AdminDevice: Decodable { let id: String; let lock: DeviceLock? }
struct AdminDevices: Decodable { let devices: [AdminDevice] }
