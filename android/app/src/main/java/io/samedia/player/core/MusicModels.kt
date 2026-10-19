package io.samedia.player.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

// Music on the Samedia server, Spotify through it, and locked screens (admin).

@Serializable
data class Track(
    val id: String,
    val title: String = "",
    val artist: String? = null,
    val album: String? = null,
    @SerialName("album_id") val albumId: String? = null,
    @SerialName("artist_id") val artistId: String? = null,
    val track: Int? = null,
    val disc: Int? = null,
    val year: Int? = null,
    val duration: Double? = null,
    val codec: String? = null,
    val art: String? = null,
)

@Serializable
data class Album(
    val id: String,
    val title: String = "",
    val artist: String? = null,
    @SerialName("artist_id") val artistId: String? = null,
    val year: Int? = null,
    val genre: String? = null,
    @SerialName("track_count") val trackCount: Int = 0,
    val duration: Double? = null,
    val art: String? = null,
    val tracks: List<Track> = emptyList(),
)

@Serializable
data class Artist(
    val id: String,
    val name: String = "",
    @SerialName("album_count") val albumCount: Int = 0,
    @SerialName("track_count") val trackCount: Int = 0,
    val art: String? = null,
    val albums: List<Album> = emptyList(),
)

@Serializable
data class MusicShelf(val id: String, val title: String = "", val items: List<Album> = emptyList())

@Serializable
data class MusicStats(val tracks: Int = 0, val albums: Int = 0, val artists: Int = 0)

@Serializable
data class MusicHome(val shelves: List<MusicShelf> = emptyList(), val stats: MusicStats = MusicStats())

@Serializable
data class AlbumList(val albums: List<Album> = emptyList())

@Serializable
data class ArtistList(val artists: List<Artist> = emptyList())

@Serializable
data class TrackList(val tracks: List<Track> = emptyList())

@Serializable
data class MusicSearch(
    val artists: List<Artist> = emptyList(),
    val albums: List<Album> = emptyList(),
    val tracks: List<Track> = emptyList(),
)

// ── Spotify ──

@Serializable
data class SpotifyStatus(val connected: Boolean = false, val user: String? = null, val premium: Boolean = false)

@Serializable
data class SpotifyTrack(
    val id: String? = null,
    val uri: String? = null,
    val title: String? = null,
    val artist: String? = null,
    val album: String? = null,
    val duration: Double? = null,
    val image: String? = null,
)

@Serializable
data class SpotifyAlbum(val id: String? = null, val uri: String? = null, val title: String? = null,
                        val artist: String? = null, val image: String? = null)

@Serializable
data class SpotifyArtist(val id: String? = null, val uri: String? = null, val name: String? = null, val image: String? = null)

/** A playlist in a list (its track count). */
@Serializable
data class SpotifyPlaylist(
    val id: String,
    val uri: String? = null,
    val title: String = "",
    val owner: String? = null,
    val tracks: Int? = null,
    val image: String? = null,
)

/** A playlist opened (its tracks). */
@Serializable
data class SpotifyPlaylistDetail(
    val id: String,
    val uri: String? = null,
    val title: String = "",
    val owner: String? = null,
    val image: String? = null,
    val tracks: List<SpotifyTrack> = emptyList(),
)

@Serializable
data class SpotifyPlaylists(val playlists: List<SpotifyPlaylist> = emptyList())

@Serializable
data class SpotifyDevice(val id: String, val name: String = "", val type: String? = null, val active: Boolean = false)

@Serializable
data class SpotifyDevices(val devices: List<SpotifyDevice> = emptyList())

@Serializable
data class SpotifySearch(
    val tracks: List<SpotifyTrack> = emptyList(),
    val albums: List<SpotifyAlbum> = emptyList(),
    val artists: List<SpotifyArtist> = emptyList(),
    val playlists: List<SpotifyPlaylist> = emptyList(),
)

// ── locking screens (admin) ──

@Serializable
data class DeviceLock(
    val profile: String,
    @SerialName("music_only") val musicOnly: Boolean = true,
    val albums: List<String> = emptyList(),
    val artists: List<String> = emptyList(),
    val playlists: List<String> = emptyList(),
)

@Serializable
data class AdminDevice(
    val id: String,
    val name: String = "",
    val model: String? = null,
    val app: String? = null,
    val version: String? = null,
    val online: Boolean = false,
    val lock: DeviceLock? = null,
)

@Serializable
data class AdminDevices(val devices: List<AdminDevice> = emptyList())
