package io.samedia.player.tv

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Color
import android.media.AudioManager
import android.net.ConnectivityManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.Gravity
import android.view.KeyEvent
import android.view.SurfaceView
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import androidx.activity.ComponentActivity
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.TrackSelectionOverride
import androidx.media3.common.VideoSize
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.webkit.WebViewAssetLoader
import io.samedia.player.core.Api
import io.samedia.player.player.DeviceCaps
import org.json.JSONObject
import java.net.Inet4Address
import java.util.UUID

/**
 * Samedia for Google TV: the same app as on the Samsung TV (bundled from tv/), in a transparent
 * WebView, over the app's own player. Like Samsung's AVPlay, the video sits behind the page,
 * which turns transparent while playing; the page drives it through window.SamediaNative
 * (see NativeBackend in tv/js/player/backends.js) and hears back through SamediaNativeEvent.
 */
class TvActivity : ComponentActivity() {
    private val main = Handler(Looper.getMainLooper())
    private lateinit var web: WebView
    private lateinit var frame: AspectRatioFrameLayout
    private lateinit var player: ExoPlayer
    private var loaded = false            // a title is open in the player
    private var readySent = false
    private var seekPending = false
    @Volatile private var state = "idle"

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        WindowInsetsControllerCompat(window, window.decorView).apply {
            systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            hide(WindowInsetsCompat.Type.systemBars())
        }

        val root = FrameLayout(this).apply { setBackgroundColor(Color.BLACK) }
        frame = AspectRatioFrameLayout(this).apply { resizeMode = AspectRatioFrameLayout.RESIZE_MODE_FIT }
        val surface = SurfaceView(this)
        frame.addView(surface, FrameLayout.LayoutParams(MATCH_PARENT, MATCH_PARENT))
        root.addView(frame, FrameLayout.LayoutParams(MATCH_PARENT, MATCH_PARENT, Gravity.CENTER))

        val assets = WebViewAssetLoader.Builder()
            .setDomain("appassets.androidplatform.net")
            .setHttpAllowed(true)            // the page talks to the server over plain http
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()
        // Inspectable over adb (chrome://inspect), which already has full access to the device
        WebView.setWebContentsDebuggingEnabled(true)
        web = WebView(this).apply {
            setBackgroundColor(Color.TRANSPARENT)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.mediaPlaybackRequiresUserGesture = false
            // The page is a fixed 1920×1080 canvas: one page pixel per screen pixel of the UI
            settings.useWideViewPort = true
            settings.loadWithOverviewMode = true
            settings.setSupportZoom(false)
            setInitialScale(resources.displayMetrics.widthPixels * 100 / 1920)
            isFocusable = true
            isFocusableInTouchMode = true
            webViewClient = object : WebViewClient() {
                override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
                    assets.shouldInterceptRequest(request.url)
            }
            addJavascriptInterface(Bridge(), "SamediaNative")
        }
        root.addView(web, FrameLayout.LayoutParams(MATCH_PARENT, MATCH_PARENT))
        setContentView(root)

        val http = DefaultHttpDataSource.Factory()
            .setUserAgent("Samedia-GoogleTV")
            .setConnectTimeoutMs(15_000)
            .setReadTimeoutMs(30_000)
        player = ExoPlayer.Builder(this)
            // Platform decoders first, the bundled ffmpeg ones for DTS/TrueHD
            .setRenderersFactory(DefaultRenderersFactory(this)
                .setExtensionRendererMode(DefaultRenderersFactory.EXTENSION_RENDERER_MODE_ON)
                .setEnableDecoderFallback(true))
            .setMediaSourceFactory(DefaultMediaSourceFactory(http))
            .setAudioAttributes(AudioAttributes.Builder().setUsage(C.USAGE_MEDIA)
                .setContentType(C.AUDIO_CONTENT_TYPE_MOVIE).build(), true)
            .build()
        // The page draws the subtitles
        player.trackSelectionParameters = player.trackSelectionParameters.buildUpon()
            .setTrackTypeDisabled(C.TRACK_TYPE_TEXT, true).build()
        player.setVideoSurfaceView(surface)
        player.addListener(listener)
        // Testing over adb without sound: am start -n io.samedia.player/.tv.TvActivity --ez muted true
        if (intent.getBooleanExtra("muted", false)) player.volume = 0f

        if (savedInstanceState != null) web.restoreState(savedInstanceState)
        else web.loadUrl("http://appassets.androidplatform.net/assets/tv/index.html")
        web.requestFocus()
    }

    // ── the player, as the page sees it ──

    private val listener = object : Player.Listener {
        override fun onPlaybackStateChanged(s: Int) {
            state = when (s) {
                Player.STATE_BUFFERING -> "buffering"
                Player.STATE_READY -> if (player.isPlaying) "playing" else "ready"
                Player.STATE_ENDED -> "ended"
                else -> "idle"
            }
            when (s) {
                Player.STATE_BUFFERING -> if (readySent) emit("buffering", true)
                Player.STATE_READY -> {
                    if (!readySent) {
                        readySent = true
                        emit("ready")
                    } else emit("buffering", false)
                    if (seekPending) {
                        seekPending = false
                        emit("seeked")
                    }
                }
                Player.STATE_ENDED -> emit("ended")
            }
        }

        override fun onPositionDiscontinuity(old: Player.PositionInfo, new: Player.PositionInfo, reason: Int) {
            if (reason != Player.DISCONTINUITY_REASON_SEEK) return
            emit("time", player.currentPosition / 1000.0)
            // A seek inside what is already loaded may never leave READY
            main.postDelayed({
                if (seekPending && player.playbackState == Player.STATE_READY) {
                    seekPending = false
                    emit("seeked")
                }
            }, 150)
        }

        override fun onIsPlayingChanged(isPlaying: Boolean) {
            if (player.playbackState == Player.STATE_READY) state = if (isPlaying) "playing" else "paused"
            emit("playing", isPlaying)
            if (isPlaying) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }

        override fun onVideoSizeChanged(size: VideoSize) {
            if (size.width > 0 && size.height > 0) {
                frame.setAspectRatio(size.width * size.pixelWidthHeightRatio / size.height)
            }
        }

        override fun onPlayerError(e: PlaybackException) {
            state = "error"
            emit("error", e.cause?.message?.let { "${e.errorCodeName}: $it" } ?: e.errorCodeName)
        }
    }

    private val ticker = object : Runnable {
        override fun run() {
            if (loaded && player.isPlaying) emit("time", player.currentPosition / 1000.0)
            main.postDelayed(this, 250)
        }
    }

    private fun emit(name: String, arg: Any? = null) {
        val value = when (arg) {
            null -> "null"
            is String -> JSONObject.quote(arg)
            else -> arg.toString()
        }
        web.evaluateJavascript("window.SamediaNativeEvent&&SamediaNativeEvent('$name',$value)", null)
    }

    private fun openMedia(url: String) {
        loaded = true
        readySent = false
        seekPending = false
        state = "opening"
        player.trackSelectionParameters = player.trackSelectionParameters.buildUpon()
            .clearOverridesOfType(C.TRACK_TYPE_AUDIO).build()
        val item = MediaItem.Builder().setUri(url)
            .setMimeType(if (url.substringBefore('?').endsWith(".m3u8")) MimeTypes.APPLICATION_M3U8 else null)
            .build()
        player.setMediaItem(item)
        player.prepare()
        // The page calls play() when it wants the picture moving
        player.playWhenReady = false
    }

    private fun stopMedia() {
        loaded = false
        state = "idle"
        player.stop()
        player.clearMediaItems()
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    /** The ordinal-th audio stream of the file (the server's audio_ordinal). */
    private fun chooseAudio(ordinal: Int) {
        val groups = player.currentTracks.groups.filter { it.type == C.TRACK_TYPE_AUDIO }
        val group = groups.getOrNull(ordinal) ?: return
        player.trackSelectionParameters = player.trackSelectionParameters.buildUpon()
            .setOverrideForType(TrackSelectionOverride(group.mediaTrackGroup, 0)).build()
    }

    // ── the page's window into Android (called on the WebView's bridge thread) ──

    private inner class Bridge {
        @JavascriptInterface fun deviceId(): String {
            val prefs = getSharedPreferences("samedia", Context.MODE_PRIVATE)
            return prefs.getString("tvDeviceID", null) ?: ("gtv-" + UUID.randomUUID().toString().replace("-", "").take(20))
                .also { prefs.edit().putString("tvDeviceID", it).apply() }
        }

        /** The name given to the device in its settings ("Living room TV"), else its model. */
        @JavascriptInterface fun deviceName(): String =
            Settings.Global.getString(contentResolver, "device_name")?.takeIf { it.isNotBlank() } ?: Build.MODEL

        @JavascriptInterface fun localIp(): String? {
            val cm = getSystemService(ConnectivityManager::class.java)
            return cm.getLinkProperties(cm.activeNetwork)?.linkAddresses
                ?.map { it.address }?.firstOrNull { it is Inet4Address && !it.isLoopbackAddress }?.hostAddress
        }

        @JavascriptInterface fun capabilities(): String = DeviceCaps.capabilities.toString()

        @JavascriptInterface fun appVersion(): String = Api.appVersion

        @JavascriptInterface fun open(url: String, opts: String) = main.post { openMedia(url) }.let { }
        @JavascriptInterface fun play() = main.post { player.play() }.let { }
        @JavascriptInterface fun pause() = main.post { player.pause() }.let { }
        @JavascriptInterface fun seek(ms: Long) = main.post {
            seekPending = true
            player.seekTo(ms.coerceAtLeast(0))
        }.let { }
        @JavascriptInterface fun stop() = main.post { stopMedia() }.let { }
        @JavascriptInterface fun state(): String = state
        @JavascriptInterface fun selectAudio(ordinal: Int): Boolean {
            main.post { chooseAudio(ordinal) }
            return true
        }
        @JavascriptInterface fun setDisplayMode(mode: String) = main.post {
            frame.resizeMode = when (mode) {
                "fill" -> AspectRatioFrameLayout.RESIZE_MODE_ZOOM
                "stretch" -> AspectRatioFrameLayout.RESIZE_MODE_FILL
                else -> AspectRatioFrameLayout.RESIZE_MODE_FIT
            }
        }.let { }

        /** Most Google TV devices hand volume to the TV over HDMI; fixed-volume ones can't. */
        @JavascriptInterface fun canVolume(): Boolean = !getSystemService(AudioManager::class.java).isVolumeFixed

        @JavascriptInterface fun volume(key: String): String {
            val am = getSystemService(AudioManager::class.java)
            val direction = when (key) {
                "up" -> AudioManager.ADJUST_RAISE
                "down" -> AudioManager.ADJUST_LOWER
                "mute" -> AudioManager.ADJUST_TOGGLE_MUTE
                else -> return ""
            }
            am.adjustStreamVolume(AudioManager.STREAM_MUSIC, direction, AudioManager.FLAG_SHOW_UI)
            return if (am.isStreamMute(AudioManager.STREAM_MUSIC)) "Muted"
            else "Volume ${am.getStreamVolume(AudioManager.STREAM_MUSIC)}"
        }

        @JavascriptInterface fun exit() = main.post { finish() }.let { }
    }

    // ── keys: arrows and OK go to the page as they are; Back and media keys become actions ──

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        val action = when (event.keyCode) {
            KeyEvent.KEYCODE_BACK, KeyEvent.KEYCODE_ESCAPE -> "back"
            KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE, KeyEvent.KEYCODE_HEADSETHOOK -> "playpause"
            KeyEvent.KEYCODE_MEDIA_PLAY -> "play"
            KeyEvent.KEYCODE_MEDIA_PAUSE -> "pause"
            KeyEvent.KEYCODE_MEDIA_STOP -> "stop"
            KeyEvent.KEYCODE_MEDIA_FAST_FORWARD -> "ff"
            KeyEvent.KEYCODE_MEDIA_REWIND -> "rw"
            KeyEvent.KEYCODE_CHANNEL_UP -> "chup"
            KeyEvent.KEYCODE_CHANNEL_DOWN -> "chdown"
            KeyEvent.KEYCODE_INFO, KeyEvent.KEYCODE_GUIDE -> "info"
            KeyEvent.KEYCODE_PROG_RED -> "red"
            KeyEvent.KEYCODE_PROG_GREEN -> "green"
            KeyEvent.KEYCODE_PROG_YELLOW -> "yellow"
            KeyEvent.KEYCODE_PROG_BLUE -> "blue"
            else -> return super.dispatchKeyEvent(event)
        }
        if (event.action == KeyEvent.ACTION_DOWN && event.repeatCount == 0) {
            web.evaluateJavascript("window.SM&&SM.app&&SM.app.press('$action')", null)
        }
        return true
    }

    // ── lifecycle ──

    override fun onResume() {
        super.onResume()
        web.onResume()
        main.post(ticker)
    }

    override fun onPause() {
        super.onPause()
        main.removeCallbacks(ticker)
        // The page sees itself hidden and pauses (its visibilitychange handler)
        web.onPause()
    }

    override fun onStop() {
        super.onStop()
        if (player.isPlaying) player.pause()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    override fun onDestroy() {
        main.removeCallbacksAndMessages(null)
        player.removeListener(listener)
        player.release()
        web.destroy()
        super.onDestroy()
    }
}
