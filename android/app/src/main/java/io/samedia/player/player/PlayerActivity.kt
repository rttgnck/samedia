package io.samedia.player.player

import android.app.Activity
import android.app.PictureInPictureParams
import android.content.Context
import android.content.Intent
import android.content.res.Configuration
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.util.Rational
import android.view.View
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Cast
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaMetadata
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.TrackSelectionOverride
import androidx.media3.common.Tracks
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView
import io.samedia.player.SamediaApp
import io.samedia.player.core.Api
import io.samedia.player.core.Language
import io.samedia.player.core.MediaItem
import io.samedia.player.core.PlaybackDecision
import io.samedia.player.core.RemotePlayer
import io.samedia.player.ui.SamediaTheme
import io.samedia.player.ui.symbol
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import androidx.media3.common.MediaItem as ExoItem

/** The player that is open, for commands from other devices. */
interface PlayerController {
    fun command(action: String, msg: JsonObject)
    fun replace(item: MediaItem, start: Double?)
}

object PlayerHub {
    var current: PlayerController? = null
}

/**
 * Plays a movie or episode full screen and keeps the server up to date with where the profile
 * is in it (every 10 s, on pause and on close), so any device can pick up from there.
 */
class PlayerActivity : ComponentActivity(), PlayerController {
    companion object {
        fun open(context: Context, item: MediaItem, start: Double?) {
            val intent = Intent(context, PlayerActivity::class.java)
                .putExtra("item", Api.json.encodeToString(MediaItem.serializer(), item))
                .putExtra("start", start ?: -1.0)
            if (context !is Activity) intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(intent)
        }
    }

    private val model get() = (application as SamediaApp).model
    private lateinit var player: ExoPlayer
    private var item: MediaItem? = null
    private var decision: PlaybackDecision? = null
    private var autoSubtitle: String? = null
    private var subtitleChosen = false
    private var openJob: Job? = null
    private var ticker: Job? = null
    private var reported = false

    private var title by mutableStateOf("")
    private var controlsVisible by mutableStateOf(true)
    private var loading by mutableStateOf(true)
    private var error by mutableStateOf<String?>(null)
    private var sendTargets by mutableStateOf<List<RemotePlayer>?>(null)
    private var inPip by mutableStateOf(false)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        if (Build.VERSION.SDK_INT >= 28) {
            window.attributes.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
        }
        WindowInsetsControllerCompat(window, window.decorView).apply {
            systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            hide(WindowInsetsCompat.Type.systemBars())
        }
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        val http = DefaultHttpDataSource.Factory()
            .setUserAgent("Samedia-Android")
            .setConnectTimeoutMs(15_000)
            .setReadTimeoutMs(30_000)
        player = ExoPlayer.Builder(this)
            // Platform decoders first, the bundled ffmpeg ones for Dolby/DTS/TrueHD audio
            .setRenderersFactory(DefaultRenderersFactory(this)
                .setExtensionRendererMode(DefaultRenderersFactory.EXTENSION_RENDERER_MODE_ON)
                .setEnableDecoderFallback(true))
            .setMediaSourceFactory(DefaultMediaSourceFactory(http))
            .setSeekBackIncrementMs(10_000)
            .setSeekForwardIncrementMs(30_000)
            .setAudioAttributes(AudioAttributes.Builder().setUsage(C.USAGE_MEDIA)
                .setContentType(C.AUDIO_CONTENT_TYPE_MOVIE).build(), true)
            .setHandleAudioBecomingNoisy(true)
            .build()
        // Subtitles are chosen here (see onTracksChanged), not by the files' default flags
        player.trackSelectionParameters = player.trackSelectionParameters.buildUpon()
            .setIgnoredTextSelectionFlags(C.SELECTION_FLAG_DEFAULT or C.SELECTION_FLAG_FORCED)
            .setPreferredAudioLanguage(Language.device)
            .build()
        player.addListener(listener)
        PlayerHub.current = this

        setContent {
            SamediaTheme {
                androidx.compose.material3.Surface(color = Color.Black, contentColor = Color.White) { PlayerScreen() }
            }
        }
        start(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        report()
        start(intent)
    }

    private fun start(intent: Intent) {
        val item = intent.getStringExtra("item")?.let { runCatching { Api.json.decodeFromString(MediaItem.serializer(), it) }.getOrNull() }
            ?: return finish()
        open(item, intent.getDoubleExtra("start", -1.0).takeIf { it >= 0 })
    }

    private fun open(item: MediaItem, start: Double?) {
        val api = model.api ?: return finish()
        MusicController.pause()                     // one thing at a time
        openJob?.cancel()
        this.item = item
        decision = null
        title = item.fullTitle
        loading = true
        error = null
        subtitleChosen = false
        reported = false
        player.stop()
        player.trackSelectionParameters = player.trackSelectionParameters.buildUpon()
            .clearOverridesOfType(C.TRACK_TYPE_TEXT).setTrackTypeDisabled(C.TRACK_TYPE_TEXT, false).build()
        openJob = lifecycleScope.launch {
            try {
                val language = Language.device
                val session = "and-" + Api.deviceId.takeLast(8) + "-" + (System.currentTimeMillis() / 1000 % 100000)
                val d: PlaybackDecision = api.post("/api/v1/items/${item.id}/playback", buildJsonObject {
                    put("capabilities", DeviceCaps.capabilities)
                    put("start", start ?: 0.0)
                    put("session", session)
                    put("prefer_audio_lang", language)
                    put("subtitle_language", language)
                })
                decision = d
                val auto = d.automaticSubtitles(language)
                autoSubtitle = auto?.let { "samedia-${it.id}" }
                // Segments carry no subtitles, so every text track comes from the server; a file
                // played as it is has its own, plus the one that comes on by itself
                val sidecars = (if (d.mode == "direct") listOfNotNull(auto) else d.textTracks).map { t ->
                    ExoItem.SubtitleConfiguration.Builder(Uri.parse(api.url(t.url!!)))
                        .setId("samedia-${t.id}")
                        .setMimeType(MimeTypes.TEXT_VTT)
                        .setLanguage(t.language)
                        .setLabel(t.label)
                        .build()
                }
                val media = ExoItem.Builder()
                    .setUri(api.url(d.url))
                    .setMimeType(if (d.mode == "hls") MimeTypes.APPLICATION_M3U8 else null)
                    .setMediaMetadata(MediaMetadata.Builder().setTitle(item.title).setSubtitle(item.showTitle).build())
                    .setSubtitleConfigurations(sidecars)
                    .build()
                val at = ((start ?: 0.0) - d.startOffset).coerceAtLeast(0.0)
                player.setMediaItem(media, (at * 1000).toLong())
                player.prepare()
                player.playWhenReady = true
                startTicker()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                loading = false
                error = e.message ?: "Playback failed"
                reportError(error ?: "Playback failed")
            }
        }
    }

    // ── where we are ──

    private val offset get() = decision?.startOffset ?: 0.0
    private val position get() = player.currentPosition / 1000.0 + offset
    private val duration: Double
        get() = decision?.duration ?: item?.duration ?: (player.duration.takeIf { it > 0 }?.div(1000.0) ?: 0.0)

    /** Tell the server where we are (it marks the title watched near the end). */
    private fun report(ended: Boolean = false) {
        val item = item ?: return
        val api = model.api ?: return
        if (decision == null || reported) return
        val total = duration
        val at = if (ended && total > 0) total else position
        if (at <= 0) return
        if (ended) reported = true
        model.scope.launch {
            runCatching {
                api.postIgnoringReply("/api/v1/items/${item.id}/progress", buildJsonObject {
                    put("position", at)
                    put("duration", total)
                })
            }
        }
    }

    /** Tell the server, so a title that failed can be found later (admin page). */
    private fun reportError(message: String) {
        val item = item ?: return
        val api = model.api ?: return
        val d = decision
        model.scope.launch {
            runCatching {
                api.postIgnoringReply("/api/v1/events", buildJsonObject {
                    put("kind", "playback_error")
                    put("item_id", item.id)
                    d?.let { put("mode", it.mode) }
                    put("error", message.take(300))
                    put("position", position)
                })
            }
        }
    }

    private fun reportRemote() {
        val item = item ?: return
        if (decision == null) return
        model.remote.report(mapOf(
            "item_id" to item.id, "title" to item.fullTitle, "kind" to item.kind,
            "position" to position, "duration" to duration, "playing" to player.isPlaying,
            "profile_id" to (model.profile?.id ?: "default"),
        ))
    }

    private fun startTicker() {
        ticker?.cancel()
        ticker = lifecycleScope.launch {
            var n = 0
            while (isActive) {
                delay(1000)
                n++
                if (n % 5 == 0) reportRemote()
                if (n % 10 == 0 && player.isPlaying) report()
            }
        }
    }

    private val listener = object : Player.Listener {
        override fun onPlaybackStateChanged(state: Int) {
            when (state) {
                Player.STATE_READY -> loading = false
                Player.STATE_ENDED -> {
                    report(ended = true)
                    finish()
                }
            }
        }

        override fun onIsPlayingChanged(isPlaying: Boolean) {
            if (!isPlaying && player.playbackState == Player.STATE_READY) report()
            reportRemote()
        }

        override fun onPlayerError(e: PlaybackException) {
            loading = false
            error = e.cause?.message?.let { "${e.errorCodeName}: $it" } ?: e.errorCodeName
            reportError(error ?: e.errorCodeName)
        }

        override fun onTracksChanged(tracks: Tracks) {
            if (subtitleChosen) return
            val wanted = autoSubtitle ?: run { subtitleChosen = true; return }
            val group = tracks.groups.firstOrNull { g ->
                g.type == C.TRACK_TYPE_TEXT && (0 until g.length).any { g.getTrackFormat(it).id?.contains(wanted) == true }
            } ?: return
            subtitleChosen = true
            player.trackSelectionParameters = player.trackSelectionParameters.buildUpon()
                .setOverrideForType(TrackSelectionOverride(group.mediaTrackGroup, 0)).build()
        }
    }

    // ── other devices ──

    override fun command(action: String, msg: JsonObject) {
        fun seekTo(seconds: Double) = player.seekTo((seconds.coerceAtLeast(0.0) * 1000).toLong())
        when (action) {
            "pause" -> player.pause()
            "resume" -> player.play()
            "toggle" -> if (player.isPlaying) player.pause() else player.play()
            "seek" -> seekTo((msg["position"]?.jsonPrimitive?.doubleOrNull ?: 0.0) - offset)
            "skip" -> seekTo(player.currentPosition / 1000.0 + (msg["delta"]?.jsonPrimitive?.doubleOrNull ?: 0.0))
            "stop" -> finish()
        }
        reportRemote()
    }

    override fun replace(item: MediaItem, start: Double?) {
        report()
        open(item, start)
    }

    /** Hand over to another screen: it carries on from here, this one stops. */
    private fun sendTo(target: RemotePlayer) {
        val item = item ?: return
        val at = (position - 2).coerceAtLeast(0.0)
        sendTargets = null
        lifecycleScope.launch {
            if (model.playOn(target, item, at)) {
                report()
                finish()
            }
        }
    }

    // ── lifecycle ──

    override fun onUserLeaveHint() {
        super.onUserLeaveHint()
        // Home while playing: keep watching in a corner
        if (player.isPlaying && Build.VERSION.SDK_INT >= 26) {
            val size = player.videoSize
            val ratio = if (size.width > 0 && size.height > 0) Rational(size.width, size.height) else Rational(16, 9)
            val clamped = ratio.toFloat().let { if (it > 2.39f) Rational(239, 100) else if (it < 0.42f) Rational(42, 100) else ratio }
            runCatching { enterPictureInPictureMode(PictureInPictureParams.Builder().setAspectRatio(clamped).build()) }
        }
    }

    override fun onPictureInPictureModeChanged(isInPictureInPictureMode: Boolean, newConfig: Configuration) {
        super.onPictureInPictureModeChanged(isInPictureInPictureMode, newConfig)
        inPip = isInPictureInPictureMode
        // closed from the corner
        if (!isInPictureInPictureMode && !lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) finish()
    }

    override fun onPause() {
        super.onPause()
        report()
    }

    override fun onStop() {
        super.onStop()
        if (!inPip) player.pause()
        if (inPip && isFinishing.not() && !isInPictureInPictureMode) finish()
    }

    override fun onDestroy() {
        super.onDestroy()
        report()
        ticker?.cancel()
        if (PlayerHub.current === this) PlayerHub.current = null
        model.remote.report(null)
        player.removeListener(listener)
        player.release()
        // Let the server save the last position before the screens reload
        model.scope.launch {
            delay(400)
            model.refreshToken++
        }
    }

    // ── screen ──

    @Composable
    private fun PlayerScreen() {
        Box(Modifier.fillMaxSize().background(Color.Black)) {
            AndroidView(
                factory = { ctx ->
                    PlayerView(ctx).apply {
                        player = this@PlayerActivity.player
                        setShowNextButton(false)
                        setShowPreviousButton(false)
                        setShowSubtitleButton(true)
                        controllerShowTimeoutMs = 4000
                        resizeMode = AspectRatioFrameLayout.RESIZE_MODE_FIT
                        setShowBuffering(PlayerView.SHOW_BUFFERING_NEVER)
                        setControllerVisibilityListener(PlayerView.ControllerVisibilityListener { v ->
                            controlsVisible = v == View.VISIBLE
                        })
                    }
                },
                update = { it.useController = !inPip },
                modifier = Modifier.fillMaxSize(),
            )

            AnimatedVisibility(
                visible = controlsVisible && !inPip,
                enter = fadeIn(), exit = fadeOut(),
                modifier = Modifier.align(Alignment.TopStart).fillMaxWidth(),
            ) {
                Row(
                    Modifier
                        .background(Brush.verticalGradient(listOf(Color.Black.copy(alpha = 0.7f), Color.Transparent)))
                        .windowInsetsPadding(WindowInsets.safeDrawing)
                        .padding(horizontal = 8.dp, vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    IconButton(onClick = { finish() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, "Close", tint = Color.White)
                    }
                    Text(title, color = Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f).padding(horizontal = 6.dp))
                    if (model.hasRemote) {
                        FilledTonalButton(onClick = {
                            lifecycleScope.launch { sendTargets = model.players() }
                        }) {
                            Icon(Icons.Filled.Cast, null)
                            Spacer(Modifier.width(8.dp))
                            Text("Send to")
                        }
                    }
                }
            }

            if (loading && error == null) {
                CircularProgressIndicator(Modifier.align(Alignment.Center), color = Color.White)
            }

            error?.let { message ->
                AlertDialog(
                    onDismissRequest = { finish() },
                    title = { Text("Playback stopped") },
                    text = { Text(message) },
                    confirmButton = { TextButton(onClick = { finish() }) { Text("OK") } },
                )
            }

            sendTargets?.let { targets ->
                AlertDialog(
                    onDismissRequest = { sendTargets = null },
                    title = { Text("Send to") },
                    text = {
                        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            if (targets.isEmpty()) Text("No other Samedia screens are on.")
                            targets.forEach { p ->
                                ListItem(
                                    headlineContent = { Text(p.name) },
                                    supportingContent = {
                                        Text(p.nowPlaying?.let { (if (it.playing) "Playing " else "Paused · ") + (it.title ?: "") } ?: "Idle",
                                            maxLines = 1, overflow = TextOverflow.Ellipsis)
                                    },
                                    leadingContent = { Icon(p.symbol, null) },
                                    colors = ListItemDefaults.colors(containerColor = Color.Transparent),
                                    modifier = Modifier.clickable { sendTo(p) },
                                )
                            }
                        }
                    },
                    confirmButton = { TextButton(onClick = { sendTargets = null }) { Text("Cancel") } },
                )
            }
        }
    }
}
