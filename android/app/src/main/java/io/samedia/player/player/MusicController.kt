package io.samedia.player.player

import android.content.ComponentName
import android.content.Context
import android.net.Uri
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.Player
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import io.samedia.player.core.Api
import io.samedia.player.core.Track

/** The app's side of the music player (MusicService): what plays, and the buttons. */
object MusicController {
    // what ExoPlayer on the phone plays as it is (with the ffmpeg decoders); the rest comes as MP3
    private val PLAYS = setOf("mp3", "aac", "flac", "alac", "vorbis", "opus", "pcm_s16le", "pcm_s24le", "ac3", "eac3")

    private var controller: MediaController? = null
    private var connecting = false
    private val waiting = mutableListOf<(MediaController) -> Unit>()
    private val tracks = mutableMapOf<String, Track>()

    var current by mutableStateOf<Track?>(null)
        private set
    var playing by mutableStateOf(false)
        private set
    var shuffle by mutableStateOf(false)
        private set
    /** Bumped every second while playing, for the progress bar. */
    var tick by mutableLongStateOf(0L)
        private set

    val position: Double get() = (controller?.currentPosition ?: 0L) / 1000.0
    val duration: Double get() = current?.duration ?: ((controller?.duration ?: 0L).coerceAtLeast(0L) / 1000.0)
    val queue: List<Track>
        get() {
            val c = controller ?: return emptyList()
            return (0 until c.mediaItemCount).mapNotNull { tracks[c.getMediaItemAt(it).mediaId] }
        }
    val index: Int get() = controller?.currentMediaItemIndex ?: 0

    fun trackFor(id: String?): Track? = id?.let { tracks[it] }

    private val listener = object : Player.Listener {
        override fun onEvents(player: Player, events: Player.Events) = sync()
    }

    private fun sync() {
        val c = controller ?: return
        current = tracks[c.currentMediaItem?.mediaId]
        playing = c.isPlaying
        shuffle = c.shuffleModeEnabled
        tick = System.currentTimeMillis()
    }

    private fun withController(context: Context, block: (MediaController) -> Unit) {
        controller?.let { return block(it) }
        waiting += block
        if (connecting) return
        connecting = true
        val token = SessionToken(context, ComponentName(context, MusicService::class.java))
        val future = MediaController.Builder(context.applicationContext, token).buildAsync()
        future.addListener({
            connecting = false
            val c = runCatching { future.get() }.getOrNull() ?: return@addListener
            controller = c
            c.addListener(listener)
            sync()
            waiting.toList().forEach { it(c) }
            waiting.clear()
        }, ContextCompat.getMainExecutor(context))
    }

    /** Play these tracks here, from tracks[start] (shuffled: a random order, start first). */
    fun play(context: Context, api: Api, list: List<Track>, start: Int = 0, shuffled: Boolean = false) {
        if (list.isEmpty()) return
        PlayerHub.current?.command("pause", kotlinx.serialization.json.JsonObject(emptyMap()))   // one thing at a time
        list.forEach { tracks[it.id] = it }
        val items = list.map { t ->
            val url = api.url("/api/v1/music/stream/${t.id}", if (t.codec in PLAYS) emptyMap() else mapOf("format" to "mp3"))
            MediaItem.Builder()
                .setMediaId(t.id)
                .setRequestMetadata(MediaItem.RequestMetadata.Builder().setMediaUri(Uri.parse(url)).build())
                .setMediaMetadata(MediaMetadata.Builder().setTitle(t.title).setArtist(t.artist).setAlbumTitle(t.album)
                    .setArtworkUri(api.art(t.art, 512)?.let(Uri::parse)).build())
                .build()
        }
        withController(context) { c ->
            c.setMediaItems(items, start.coerceIn(0, items.size - 1), 0)
            c.shuffleModeEnabled = shuffled
            c.prepare()
            c.play()
        }
    }

    fun toggle() = controller?.let { if (it.isPlaying) it.pause() else it.play() }
    fun pause() = controller?.pause()
    fun resume() = controller?.play()
    fun next() = controller?.seekToNextMediaItem()
    fun previous() = controller?.let { if (it.currentPosition > 4000) it.seekTo(0) else it.seekToPreviousMediaItem() }
    fun seek(seconds: Double) = controller?.seekTo((seconds * 1000).toLong().coerceAtLeast(0))
    fun shuffleOn(on: Boolean) { controller?.shuffleModeEnabled = on }
    fun stop() = controller?.let { it.stop(); it.clearMediaItems() }

    /** A command from another device; true when it was about music. */
    fun command(action: String, msg: kotlinx.serialization.json.JsonObject): Boolean {
        if (controller?.currentMediaItem == null) return false
        val num = { k: String -> (msg[k] as? kotlinx.serialization.json.JsonPrimitive)?.content?.toDoubleOrNull() ?: 0.0 }
        when (action) {
            "toggle" -> toggle()
            "pause" -> pause()
            "resume" -> resume()
            "next" -> next()
            "previous" -> previous()
            "seek" -> seek(num("position"))
            "skip" -> seek(position + num("delta"))
            "stop" -> stop()
            else -> return false
        }
        return true
    }
}
