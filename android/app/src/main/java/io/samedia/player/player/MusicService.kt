package io.samedia.player.player

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.audio.AudioSink
import androidx.media3.exoplayer.audio.DefaultAudioSink
import androidx.media3.exoplayer.audio.TeeAudioProcessor
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture
import io.samedia.player.MainActivity
import io.samedia.player.SamediaApp
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Music in the background: an ExoPlayer in a media session, so it keeps playing with the screen
 * off and shows in the notification and on the lock screen. The decoded sound also goes to the
 * visualizer (Spectrum). Tells the server what plays (remote control, "recently played").
 */
class MusicService : MediaSessionService() {
    private var session: MediaSession? = null
    private var ticker: Job? = null
    private var playedSent: String? = null
    private val model get() = (application as SamediaApp).model

    override fun onCreate() {
        super.onCreate()
        val tee = TeeAudioProcessor(Spectrum.sink)
        val renderers = object : DefaultRenderersFactory(this) {
            override fun buildAudioSink(context: Context, enableFloatOutput: Boolean,
                                        enableAudioTrackPlaybackParams: Boolean): AudioSink =
                DefaultAudioSink.Builder(context).setAudioProcessors(arrayOf(tee)).build()
        }.setExtensionRendererMode(DefaultRenderersFactory.EXTENSION_RENDERER_MODE_ON)
        val player = ExoPlayer.Builder(this, renderers)
            .setMediaSourceFactory(DefaultMediaSourceFactory(DefaultHttpDataSource.Factory().setUserAgent("Samedia-Android")))
            .setAudioAttributes(AudioAttributes.Builder().setUsage(C.USAGE_MEDIA).setContentType(C.AUDIO_CONTENT_TYPE_MUSIC).build(), true)
            .setHandleAudioBecomingNoisy(true)
            .setWakeMode(C.WAKE_MODE_NETWORK)
            .build()
        player.addListener(object : Player.Listener {
            override fun onMediaItemTransition(item: MediaItem?, reason: Int) = report()
            override fun onIsPlayingChanged(isPlaying: Boolean) = report()
        })
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP), PendingIntent.FLAG_IMMUTABLE)
        session = MediaSession.Builder(this, player)
            .setSessionActivity(open)
            .setCallback(object : MediaSession.Callback {
                // Items come from the app's controller without their address: it travels in requestMetadata
                override fun onAddMediaItems(s: MediaSession, c: MediaSession.ControllerInfo,
                                             items: MutableList<MediaItem>): ListenableFuture<MutableList<MediaItem>> =
                    Futures.immediateFuture(items.map { it.buildUpon().setUri(it.requestMetadata.mediaUri).build() }.toMutableList())
            })
            .build()
        ticker = model.scope.launch {
            while (isActive) {
                delay(5000)
                val p = session?.player ?: continue
                if (p.isPlaying) report()
                // counts as played after 30 s
                val id = p.currentMediaItem?.mediaId
                if (id != null && id != playedSent && p.currentPosition > 30_000) {
                    playedSent = id
                    runCatching { model.api?.postIgnoringReply("/api/v1/music/played", buildJsonObject { put("track_id", id) }) }
                }
            }
        }
    }

    private fun report() {
        val p = session?.player ?: return
        val item = p.currentMediaItem
        val track = item?.let { MusicController.trackFor(it.mediaId) }
        if (item == null || track == null) {
            model.remote.report(null)
            return
        }
        model.remote.report(mapOf(
            "item_id" to track.id, "title" to track.title, "artist" to track.artist, "kind" to "track", "art" to track.art,
            "position" to p.currentPosition / 1000.0, "duration" to (track.duration ?: (p.duration / 1000.0)),
            "playing" to p.isPlaying, "profile_id" to (model.profile?.id ?: "default"),
        ))
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? = session

    override fun onTaskRemoved(rootIntent: Intent?) {
        val p = session?.player
        if (p == null || !p.playWhenReady || p.mediaItemCount == 0) stopSelf()
    }

    override fun onDestroy() {
        ticker?.cancel()
        session?.run {
            player.release()
            release()
        }
        session = null
        super.onDestroy()
    }
}
