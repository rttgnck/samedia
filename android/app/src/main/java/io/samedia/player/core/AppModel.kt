package io.samedia.player.core

import android.app.Application
import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import io.samedia.player.player.PlayerActivity
import io.samedia.player.player.PlayerHub
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

/** App state: which server, which profile, and what the screens show. */
class AppModel(private val app: Application) {
    enum class Stage { Connect, Profiles, Main }

    var stage by mutableStateOf(Stage.Connect)
    var api by mutableStateOf<Api?>(null)
        private set
    var info by mutableStateOf<ServerInfo?>(null)
        private set
    var profiles by mutableStateOf(listOf<Profile>())
        private set
    var profile by mutableStateOf<Profile?>(null)
        private set
    var needsPin by mutableStateOf(false)
    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
    /** Bumped when what the screens show may have changed (after playback, watched marks...). */
    var refreshToken by mutableIntStateOf(0)
    /** A short message shown at the bottom of the screen. */
    var toast by mutableStateOf<String?>(null)
        private set
    /** The app is on screen (it can then open the player for a remote "play"). */
    var foreground = false

    val scope = MainScope()
    val remote = RemoteLink(this)
    private val prefs = app.getSharedPreferences("samedia", Context.MODE_PRIVATE)

    val hasAvatars get() = info?.features?.contains("avatars") == true
    val hasRemote get() = info?.features?.contains("remote") == true

    init {
        prefs.getString("server", null)?.toHttpUrlOrNull()?.let { url ->
            api = Api(url, prefs.getString("token", "") ?: "")
            profile = prefs.getString("profile", null)?.let { runCatching { Api.json.decodeFromString<Profile>(it) }.getOrNull() }
            api?.profileId = profile?.id
            stage = Stage.Profiles
            scope.launch { reconnect() }
        }
    }

    /** Back to a saved server on launch: straight to the last profile when it is still offered. */
    suspend fun reconnect() {
        val api = api ?: run { stage = Stage.Connect; return }
        busy = true
        try {
            info = api.get("/api/v1/info")
            loadProfiles()
            val current = profiles.firstOrNull { it.id == profile?.id }
            when {
                current != null -> select(current)
                profiles.size == 1 -> select(profiles[0])
                else -> stage = Stage.Profiles
            }
        } catch (e: Exception) {
            error = e.message
            stage = Stage.Connect
        } finally {
            busy = false
        }
    }

    fun connect(url: HttpUrl) = scope.launch {
        busy = true
        error = null
        try {
            val client = Api(url)
            val info: ServerInfo = client.get("/api/v1/info")
            this@AppModel.info = info
            api = client
            prefs.edit().putString("server", url.toString()).remove("token").remove("profile").apply()
            profile = null
            if (info.pinRequired) {
                needsPin = true
                return@launch
            }
            loadProfiles()
            if (profiles.size == 1) select(profiles[0]) else stage = Stage.Profiles
        } catch (e: Exception) {
            error = "That doesn't look like a Samedia server: ${e.message}"
        } finally {
            busy = false
        }
    }

    fun pair(pin: String) = scope.launch {
        val api = api ?: return@launch
        busy = true
        error = null
        try {
            val reply: PairReply = api.post("/api/v1/auth", buildJsonObject { put("pin", pin) })
            api.token = reply.token
            prefs.edit().putString("token", reply.token).apply()
            needsPin = false
            loadProfiles()
            if (profiles.size == 1) select(profiles[0]) else stage = Stage.Profiles
        } catch (e: Exception) {
            error = e.message
        } finally {
            busy = false
        }
    }

    suspend fun loadProfiles() {
        val api = api ?: return
        profiles = api.get<ProfilesResponse>("/api/v1/profiles").profiles
    }

    fun select(p: Profile) {
        profile = p
        api?.profileId = p.id
        prefs.edit().putString("profile", Api.json.encodeToString(Profile.serializer(), p)).apply()
        stage = Stage.Main
        refreshToken++
        if (foreground) remote.start()
    }

    fun switchProfile() {
        stage = Stage.Profiles
        scope.launch { runCatching { loadProfiles() } }
    }

    fun forgetServer() {
        remote.stop()
        prefs.edit().remove("server").remove("token").remove("profile").apply()
        api = null
        info = null
        profile = null
        profiles = emptyList()
        stage = Stage.Connect
    }

    fun setAvatar(avatar: String, p: Profile) = scope.launch {
        val api = api ?: return@launch
        try {
            val updated: Profile = api.post("/api/v1/profiles/${p.id}/avatar", buildJsonObject { put("avatar", avatar) })
            profiles = profiles.map { if (it.id == p.id) updated else it }
            if (profile?.id == p.id) profile = updated
        } catch (e: Exception) {
            show(e.message ?: "Couldn't change the picture")
        }
    }

    fun avatarUrl(p: Profile): String? = p.avatar?.takeIf { it.isNotEmpty() }?.let { api?.url("/avatars/$it.svg") }

    fun play(context: Context, item: MediaItem, start: Double?) = PlayerActivity.open(context, item, start)

    fun setWatched(item: MediaItem, watched: Boolean) = scope.launch {
        val api = api ?: return@launch
        val path = if (item.kind == "show") "/api/v1/shows/${item.id}/watched" else "/api/v1/items/${item.id}/watched"
        runCatching { api.postIgnoringReply(path, buildJsonObject { put("watched", watched) }) }
        refreshToken++
    }

    fun show(message: String) {
        toast = message
        scope.launch {
            delay(3000)
            if (toast == message) toast = null
        }
    }

    // ── remote control ──

    /** The other screens that are on. */
    suspend fun players(): List<RemotePlayer> =
        runCatching { api?.get<RemotePlayers>("/api/v1/remote/players")?.players }.getOrNull() ?: emptyList()

    suspend fun command(player: RemotePlayer, body: JsonObject) {
        val api = api ?: return
        api.postIgnoringReply("/api/v1/remote/players/${player.id}/command", body)
    }

    /** Fire-and-forget command with errors shown as a toast. */
    fun send(player: RemotePlayer, body: JsonObject) = scope.launch {
        try {
            command(player, body)
        } catch (e: Exception) {
            show(e.message ?: "That screen didn't answer")
        }
    }

    /** Start a title on another screen, as this profile, from a position. */
    suspend fun playOn(player: RemotePlayer, item: MediaItem, at: Double?): Boolean = try {
        command(player, buildJsonObject {
            put("action", "play")
            put("item_id", item.id)
            put("position", at ?: 0.0)
            profile?.let { put("profile_id", it.id) }
        })
        show("Playing on ${player.name}")
        true
    } catch (e: Exception) {
        show(e.message ?: "That screen didn't answer")
        false
    }

    /** A command from another device. */
    fun remoteCommand(msg: JsonObject) {
        val action = msg["action"]?.jsonPrimitive?.content ?: return
        if (action != "play") {
            PlayerHub.current?.command(action, msg)
            return
        }
        val itemId = msg["item_id"]?.jsonPrimitive?.content ?: return
        val position = msg["position"]?.jsonPrimitive?.doubleOrNull
        val api = api ?: return
        scope.launch {
            val pid = (msg["profile_id"] as? JsonPrimitive)?.content
            if (pid != null && pid != profile?.id) {
                runCatching { loadProfiles() }
                profiles.firstOrNull { it.id == pid }?.let { select(it) }
            }
            val item = runCatching { api.item(itemId).item }.getOrNull() ?: return@launch
            val current = PlayerHub.current
            when {
                current != null -> current.replace(item, position)
                foreground -> PlayerActivity.open(app, item, position)
            }
        }
    }
}
