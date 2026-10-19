package io.samedia.player.player

import android.media.MediaCodecList
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

/** What this phone plays, for the server's playback decision. */
object DeviceCaps {
    private val decoders by lazy {
        MediaCodecList(MediaCodecList.REGULAR_CODECS).codecInfos.filter { !it.isEncoder }
    }

    private fun has(mime: String) = decoders.any { c -> c.supportedTypes.any { it.equals(mime, ignoreCase = true) } }

    private fun plays4k(mime: String) = decoders.any { c ->
        c.supportedTypes.any { it.equals(mime, ignoreCase = true) } &&
            runCatching { c.getCapabilitiesForType(mime).videoCapabilities?.isSizeSupported(3840, 2160) == true }.getOrDefault(false)
    }

    val capabilities: JsonObject by lazy {
        val video = buildList {
            if (has("video/avc")) add("h264")
            if (has("video/hevc")) add("hevc")
            if (has("video/x-vnd.on2.vp9")) add("vp9")
            if (has("video/av01")) add("av1")
            if (has("video/mpeg2")) add("mpeg2video")
            if (has("video/mp4v-es")) add("mpeg4")
        }.ifEmpty { listOf("h264") }
        val segmentVideo = video.filter { it == "h264" || it == "hevc" }
        buildJsonObject {
            // The player reads these files itself and seeks in them; anything else comes as HLS
            put("containers", strings("mkv", "mp4", "mov", "m4v", "webm", "ts"))
            put("video", strings(*video.toTypedArray()))
            // Platform decoders plus the bundled ffmpeg ones (Dolby Digital, DTS, TrueHD)
            put("audio", strings("aac", "mp3", "ac3", "eac3", "dts", "truehd", "flac", "alac", "opus", "vorbis",
                "pcm_s16le", "pcm_s24le"))
            put("hls_video", strings(*segmentVideo.toTypedArray()))
            put("ts_video", strings(*segmentVideo.toTypedArray()))
            put("prefer_hls", JsonPrimitive(true))
            put("max_width", JsonPrimitive(if (plays4k("video/hevc") || plays4k("video/avc")) 3840 else 1920))
            put("dolby_vision", JsonPrimitive(has("video/dolby-vision")))
        }
    }

    private fun strings(vararg s: String) = JsonArray(s.map { JsonPrimitive(it) })
}
