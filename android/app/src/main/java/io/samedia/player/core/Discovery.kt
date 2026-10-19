package io.samedia.player.core

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import okhttp3.HttpUrl
import java.net.Inet4Address

/**
 * Finds Samedia servers on the home network: nasOS advertises them as _samedia._tcp, and the
 * usual name (nasos.local) is tried directly as well.
 */
class Discovery(context: Context) {
    data class Found(val id: String, val name: String, val url: HttpUrl)

    val servers = mutableStateListOf<Found>()
    var searching by mutableStateOf(false)
        private set

    private val nsd = context.getSystemService(NsdManager::class.java)
    private val main = Handler(Looper.getMainLooper())
    private var listener: NsdManager.DiscoveryListener? = null
    private val queue = ArrayDeque<NsdServiceInfo>()
    private var resolving = false
    private var jobs = listOf<Job>()

    fun start(scope: CoroutineScope) {
        stop()
        searching = true
        val l = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(serviceType: String) = log("browsing")
            override fun onDiscoveryStopped(serviceType: String) = log("stopped")
            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) = log("start failed $errorCode")
            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) = Unit
            override fun onServiceFound(info: NsdServiceInfo) = main.post { enqueue(info) }.let { }
            override fun onServiceLost(info: NsdServiceInfo) = Unit
        }
        listener = l
        runCatching { nsd.discoverServices("_samedia._tcp.", NsdManager.PROTOCOL_DNS_SD, l) }
            .onFailure { log("discovery unavailable: ${it.message}") }
        jobs = listOf(
            scope.launch { probeLikelyNames() },
            scope.launch { delay(8000); searching = false },
        )
    }

    fun stop() {
        listener?.let { runCatching { nsd.stopServiceDiscovery(it) } }
        listener = null
        jobs.forEach { it.cancel() }
        queue.clear()
        resolving = false
    }

    // Older Androids resolve one service at a time
    private fun enqueue(info: NsdServiceInfo) {
        if (servers.any { it.id == info.serviceName } || queue.any { it.serviceName == info.serviceName }) return
        queue.addLast(info)
        resolveNext()
    }

    @Suppress("DEPRECATION")
    private fun resolveNext() {
        if (resolving) return
        val info = queue.removeFirstOrNull() ?: return
        resolving = true
        nsd.resolveService(info, object : NsdManager.ResolveListener {
            override fun onResolveFailed(info: NsdServiceInfo, errorCode: Int) = main.post {
                log("resolve ${info.serviceName} failed: $errorCode")
                resolving = false
                resolveNext()
            }.let { }

            override fun onServiceResolved(info: NsdServiceInfo) = main.post {
                resolving = false
                val host = if (Build.VERSION.SDK_INT >= 34) {
                    info.hostAddresses.firstOrNull { it is Inet4Address } ?: info.hostAddresses.firstOrNull()
                } else info.host
                val address = host?.hostAddress?.substringBefore('%')
                val url = address?.let { Api.normalize(if (':' in it) "[$it]:${info.port}" else "$it:${info.port}") }
                if (url != null) add(info.serviceName, info.serviceName.removePrefix("Samedia on "), url)
                resolveNext()
            }.let { }
        })
    }

    /** nasOS's usual host name, asked directly (works where browsing doesn't). */
    private suspend fun probeLikelyNames() {
        for (host in listOf("nasos.local")) {
            val url = Api.normalize(host) ?: continue
            try {
                val info: ServerInfo = Api(url).get("/api/v1/info")
                add("direct-$host", info.name, url)
            } catch (e: Exception) {
                log("no answer from $host")
            }
        }
    }

    private fun add(id: String, name: String, url: HttpUrl) {
        // Same server found both ways: keep the first
        if (servers.any { it.url == url || it.name == name }) return
        servers.add(Found(id, name, url))
    }

    private fun log(text: String) = Log.i("Samedia", "discovery: $text").let { }
}
