package io.samedia.player.core

import android.content.Context
import android.os.Build
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.net.URLEncoder
import java.util.UUID
import java.util.concurrent.TimeUnit

class ApiException(message: String, val code: Int = 0) : Exception(message)

/** Talks to one Samedia server as this device and the chosen profile. */
class Api(val base: HttpUrl, var token: String = "", var profileId: String? = null) {

    companion object {
        val json = Json {
            ignoreUnknownKeys = true
            coerceInputValues = true
            isLenient = true
            explicitNulls = false
        }

        val http: OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(8, TimeUnit.SECONDS)
            .readTimeout(20, TimeUnit.SECONDS)
            .build()

        /** This device's id for the server (its per-device profile rules). Random, kept on the phone. */
        lateinit var deviceId: String
            private set
        val deviceName: String get() = Build.MODEL?.takeIf { it.isNotBlank() } ?: "Android"

        fun init(context: Context) {
            val prefs = context.getSharedPreferences("samedia", Context.MODE_PRIVATE)
            deviceId = prefs.getString("deviceID", null) ?: ("android-" + UUID.randomUUID().toString()
                .replace("-", "").take(20)).also { prefs.edit().putString("deviceID", it).apply() }
        }

        /** "nasos.local", "192.168.1.20" or a full URL -> http://host:8097 */
        fun normalize(text: String): HttpUrl? {
            var s = text.trim()
            if (s.isEmpty()) return null
            if (!s.contains("://")) s = "http://$s"
            val url = s.toHttpUrlOrNull() ?: return null
            val port = if (Regex("^[a-z]+://[^/]+:\\d+").containsMatchIn(s)) url.port else 8097
            return url.newBuilder().port(port).encodedPath("/").query(null).build()
        }
    }

    /** Absolute URL for a server path; carries the token when the server has a PIN (for images
     *  and streams, which can't send headers). */
    fun url(path: String, query: Map<String, String> = emptyMap()): String {
        val b = base.newBuilder().encodedPath("/")
        val parts = path.split("?", limit = 2)
        b.addEncodedPathSegments(parts[0].trimStart('/'))
        if (parts.size > 1) {
            parts[1].split("&").filter { it.isNotEmpty() }.forEach {
                val kv = it.split("=", limit = 2)
                b.addEncodedQueryParameter(kv[0], kv.getOrElse(1) { "" })
            }
        }
        query.forEach { (k, v) -> b.addQueryParameter(k, v) }
        if (token.isNotEmpty()) b.addQueryParameter("t", token)
        return b.build().toString()
    }

    fun art(path: String?, width: Int): String? =
        path?.takeIf { it.isNotEmpty() }?.let { url(it, mapOf("w" to minOf(1920, width).toString())) }

    private fun request(path: String, method: String, body: JsonObject?): Request {
        val b = Request.Builder().url(url(path))
            .header("X-Samedia-Device", deviceId)
            .header("X-Samedia-Device-Name", URLEncoder.encode(deviceName, "UTF-8"))
        profileId?.let { b.header("X-Samedia-Profile", it) }
        if (token.isNotEmpty()) b.header("Authorization", "Bearer $token")
        val payload = body?.toString()?.toRequestBody("application/json".toMediaType())
        return b.method(method, payload).build()
    }

    suspend fun text(path: String, method: String = "GET", body: JsonObject? = null): String = withContext(Dispatchers.IO) {
        val response = try {
            http.newCall(request(path, method, body)).execute()
        } catch (e: IOException) {
            throw ApiException("Can't reach the server (${e.message ?: e.javaClass.simpleName})")
        }
        response.use {
            val text = it.body?.string() ?: ""
            if (!it.isSuccessful) {
                val detail = runCatching { json.parseToJsonElement(text).jsonObject["detail"]?.jsonPrimitive?.content }.getOrNull()
                throw ApiException(detail ?: "The server answered ${it.code}.", it.code)
            }
            text
        }
    }

    suspend inline fun <reified T> get(path: String): T = json.decodeFromString(text(path))

    suspend inline fun <reified T> post(path: String, body: JsonObject): T =
        json.decodeFromString(text(path, "POST", body))

    suspend fun postIgnoringReply(path: String, body: JsonObject) {
        text(path, "POST", body)
    }

    suspend fun item(id: String): ItemDetail {
        val text = text("/api/v1/items/$id")
        return ItemDetail(json.decodeFromString(text), json.decodeFromString(text))
    }

    suspend fun show(id: String): ShowDetail {
        val text = text("/api/v1/shows/$id")
        return ShowDetail(json.decodeFromString(text), json.decodeFromString(text))
    }

    suspend fun collection(id: String): Pair<MediaItem, List<MediaItem>> {
        val text = text("/api/v1/collections/$id")
        return json.decodeFromString<MediaItem>(text) to json.decodeFromString<CollectionExtras>(text).items
    }
}
