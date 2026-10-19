package io.samedia.player.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import java.util.Locale
import kotlin.math.max
import kotlin.math.roundToInt

// What the Samedia server sends. Every field has a default: the server adds fields over time
// and older servers leave some out (the JSON reader ignores what it doesn't know).

@Serializable
data class ServerInfo(
    val name: String = "Samedia",
    val version: String? = null,
    @SerialName("pin_required") val pinRequired: Boolean = false,
    val features: List<String> = emptyList(),
)

@Serializable
data class Profile(
    val id: String,
    val name: String = "",
    val color: String? = null,
    val kids: Boolean = false,
    val avatar: String? = null,
)

@Serializable
data class ProfilesResponse(val profiles: List<Profile> = emptyList())

@Serializable
data class CastMember(val name: String = "", val role: String? = null)

/** A movie, episode, show or collection as it appears in lists. */
@Serializable
data class MediaItem(
    val id: String,
    val kind: String = "movie",
    val title: String = "",
    val year: Int? = null,
    val duration: Double? = null,
    val rating: Double? = null,
    val plot: String? = null,
    val genres: List<String> = emptyList(),
    val poster: String? = null,
    val backdrop: String? = null,
    val thumb: String? = null,
    /** Title card: a scene other than the backdrop, and the title's logo. */
    val scene: String? = null,
    val logo: String? = null,
    val position: Double? = null,
    val watched: Boolean = false,
    val badges: List<String> = emptyList(),
    val certification: String? = null,
    // shows and collections
    @SerialName("episode_count") val episodeCount: Int? = null,
    val unwatched: Int? = null,
    @SerialName("item_count") val itemCount: Int? = null,
    val years: String? = null,
    // episodes
    val season: Int? = null,
    val episode: Int? = null,
    @SerialName("show_id") val showId: String? = null,
    @SerialName("show_title") val showTitle: String? = null,
) {
    val isPlayable get() = kind == "movie" || kind == "episode"

    /** Seconds to resume from, or null to start at the beginning (same rule as the TV app and server). */
    val resumeAt: Double?
        get() {
            val p = position ?: return null
            if (watched || p < 20) return null
            if (duration != null && p > duration * 0.95) return null
            return p
        }

    val episodeLabel: String? get() = if (season != null && episode != null) "S$season · E$episode" else null

    /** "Show · Episode" for episodes, the title otherwise. */
    val fullTitle: String get() = showTitle?.let { "$it · $title" } ?: title
}

@Serializable
data class Shelf(val id: String, val title: String = "", val items: List<MediaItem> = emptyList())

@Serializable
data class Home(val shelves: List<Shelf> = emptyList())

@Serializable
data class ItemList(val items: List<MediaItem> = emptyList(), val genres: List<String> = emptyList())

@Serializable
data class SearchResults(
    val movies: List<MediaItem> = emptyList(),
    val shows: List<MediaItem> = emptyList(),
    val episodes: List<MediaItem> = emptyList(),
)

/** The detail-screen extras of a movie or episode (the item itself is read from the same reply). */
@Serializable
data class ItemExtras(
    val tagline: String? = null,
    val director: String? = null,
    val cast: List<CastMember> = emptyList(),
    val next: MediaItem? = null,
)

class ItemDetail(val item: MediaItem, val extras: ItemExtras)

@Serializable
data class Season(
    val season: Int = 0,
    @SerialName("episode_count") val episodeCount: Int? = null,
    val unwatched: Int? = null,
)

@Serializable
data class ShowExtras(
    val seasons: List<Season> = emptyList(),
    val episodes: List<MediaItem> = emptyList(),
    @SerialName("next_up") val nextUp: MediaItem? = null,
)

class ShowDetail(val show: MediaItem, val extras: ShowExtras)

@Serializable
data class CollectionExtras(val items: List<MediaItem> = emptyList())

@Serializable
data class AudioTrack(
    val index: Int = 0,
    val language: String? = null,
    val label: String? = null,
    val codec: String? = null,
)

@Serializable
data class SubtitleTrack(
    val id: String,
    val format: String = "text",
    val label: String = "",
    val language: String? = null,
    val forced: Boolean = false,
    val supported: Boolean = false,
    val url: String? = null,
)

@Serializable
data class PlaybackDecision(
    val mode: String,
    val url: String,
    @SerialName("start_offset") val startOffset: Double = 0.0,
    val seekable: Boolean = false,
    val duration: Double? = null,
    val session: String? = null,
    val warnings: List<String> = emptyList(),
    @SerialName("audio_index") val audioIndex: Int? = null,
    @SerialName("audio_tracks") val audioTracks: List<AudioTrack> = emptyList(),
    @SerialName("subtitle_tracks") val subtitleTracks: List<SubtitleTrack> = emptyList(),
) {
    /** Text subtitles the phone can load next to the video. */
    val textTracks get() = subtitleTracks.filter { it.supported && it.format == "text" && it.url != null }

    /**
     * Subtitles to show by themselves: full ones when the audio isn't in the viewer's language,
     * otherwise only those for the foreign-language parts (same rule as the TV and iPad).
     */
    fun automaticSubtitles(language: String): SubtitleTrack? {
        val usable = textTracks.filter { it.language == null || Language.same(it.language, language) }
        val spoken = audioTracks.firstOrNull { it.index == audioIndex }?.language
        if (spoken != null && !Language.same(spoken, language)) {
            return usable.firstOrNull { !it.forced } ?: usable.firstOrNull { it.forced }
        }
        return usable.firstOrNull { it.forced }
    }
}

@Serializable
data class NowPlaying(
    @SerialName("item_id") val itemId: String,
    val title: String? = null,
    val position: Double? = null,
    val duration: Double? = null,
    val playing: Boolean = false,
    val kind: String? = null,
    val art: String? = null,
    val artist: String? = null,
)

/** Another Samedia screen that is on (TV, phone, tablet), with what it plays. */
@Serializable
data class RemotePlayer(
    val id: String,
    val name: String = "Screen",
    val kind: String = "tv",
    @SerialName("now_playing") val nowPlaying: NowPlaying? = null,
    /** Extra controls it takes: "keys" (arrows/OK/back for its menus), "volume". */
    val can: List<String> = emptyList(),
)

@Serializable
data class RemotePlayers(val players: List<RemotePlayer> = emptyList())

@Serializable
data class PairReply(val token: String)

object Language {
    private val twoLetter = mapOf(
        "eng" to "en", "fre" to "fr", "fra" to "fr", "ger" to "de", "deu" to "de", "spa" to "es",
        "ita" to "it", "jpn" to "ja", "kor" to "ko", "chi" to "zh", "zho" to "zh", "por" to "pt",
        "rus" to "ru", "dut" to "nl", "nld" to "nl", "swe" to "sv", "nor" to "no", "dan" to "da",
        "fin" to "fi", "pol" to "pl", "hin" to "hi", "ara" to "ar", "tur" to "tr",
    )

    fun code(s: String?): String? {
        val c = s?.lowercase()?.split("-")?.firstOrNull()?.takeIf { it.isNotEmpty() } ?: return null
        return twoLetter[c] ?: c
    }

    fun same(a: String?, b: String?) = code(a) != null && code(a) == code(b)

    val device: String get() = Locale.getDefault().language.ifEmpty { "en" }
}

/** Formatting shared by the screens. */
object Format {
    /** 3725 -> "1:02:05", 65 -> "1:05" */
    fun clock(seconds: Double): String {
        val s = max(0, seconds.toInt())
        val h = s / 3600
        val m = (s % 3600) / 60
        val sec = s % 60
        return if (h > 0) "%d:%02d:%02d".format(h, m, sec) else "%d:%02d".format(m, sec)
    }

    /** 6300 -> "1h 45m" */
    fun runtime(seconds: Double?): String? {
        if (seconds == null || seconds <= 0) return null
        val m = (seconds / 60).roundToInt()
        if (m < 60) return "${m}m"
        return if (m % 60 == 0) "${m / 60}h" else "${m / 60}h ${m % 60}m"
    }

    fun meta(item: MediaItem): String {
        val bits = mutableListOf<String>()
        item.year?.let { bits += it.toString() }
        item.certification?.takeIf { it.isNotEmpty() }?.let { bits += it }
        when {
            item.kind == "show" && item.episodeCount != null -> bits += "${item.episodeCount} episodes"
            item.kind == "collection" && item.itemCount != null -> bits += "${item.itemCount} movies"
            else -> runtime(item.duration)?.let { bits += it }
        }
        item.rating?.takeIf { it > 0 }?.let { bits += "★ %.1f".format(it) }
        return bits.joinToString("  ·  ")
    }

    /** "47:12 of 1:35:42 · 48m left" */
    fun progress(item: MediaItem): String? {
        val at = item.resumeAt ?: return null
        val d = item.duration ?: return null
        return "${clock(at)} of ${clock(d)}  ·  ${runtime(d - at) ?: ""} left"
    }
}
