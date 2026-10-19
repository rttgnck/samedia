package io.samedia.player.core

import android.os.Handler
import android.os.Looper
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.concurrent.TimeUnit

/** Keeps this phone reachable for remote commands and tells the server what it is playing. */
class RemoteLink(private val model: AppModel) {
    private val main = Handler(Looper.getMainLooper())
    private val client = Api.http.newBuilder().pingInterval(20, TimeUnit.SECONDS).readTimeout(0, TimeUnit.SECONDS).build()
    private var socket: WebSocket? = null
    private var generation = 0
    private var retryMs = 1000L
    private var wanted = false
    private var lastState: JsonObject = state(null)

    fun start() {
        val api = model.api ?: return
        if (!model.hasRemote || model.profile == null) return
        close()
        wanted = true
        val mine = ++generation
        // OkHttp takes the http(s) URL and speaks WebSocket on it
        val url = api.url("/api/v1/remote/ws", mapOf("device" to Api.deviceId, "name" to Api.deviceName, "kind" to "android",
            "app" to "android/${Api.appVersion}"))
        socket = client.newWebSocket(Request.Builder().url(url).build(), object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) = on(mine) {
                retryMs = 1000
                webSocket.send(lastState.toString())
            }

            override fun onMessage(webSocket: WebSocket, text: String) = on(mine) {
                val msg = runCatching { Api.json.parseToJsonElement(text).jsonObject }.getOrNull() ?: return@on
                if (msg["type"]?.jsonPrimitive?.content == "command") model.remoteCommand(msg)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = on(mine) { reconnectLater() }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = on(mine) { reconnectLater() }
        })
    }

    fun stop() {
        wanted = false
        close()
    }

    private fun close() {
        generation++
        socket?.close(1001, null)
        socket = null
    }

    /** What this phone plays now (null when stopped). */
    fun report(now: Map<String, Any?>?) {
        lastState = state(now)
        socket?.send(lastState.toString())
    }

    private fun state(now: Map<String, Any?>?) = buildJsonObject {
        put("type", JsonPrimitive("state"))
        put("item_id", JsonNull)
        now?.forEach { (k, v) ->
            put(k, when (v) {
                null -> JsonNull
                is Number -> JsonPrimitive(v)
                is Boolean -> JsonPrimitive(v)
                else -> JsonPrimitive(v.toString())
            })
        }
    }

    private fun on(mine: Int, block: () -> Unit) {
        main.post { if (mine == generation) block() }
    }

    private fun reconnectLater() {
        socket = null
        if (!wanted) return
        val delay = retryMs
        retryMs = minOf(retryMs * 2, 30_000)
        val mine = generation
        main.postDelayed({ if (wanted && mine == generation && socket == null) start() }, delay)
    }
}
