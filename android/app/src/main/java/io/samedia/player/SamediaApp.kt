package io.samedia.player

import android.app.Application
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import coil3.ImageLoader
import coil3.PlatformContext
import coil3.SingletonImageLoader
import coil3.disk.DiskCache
import coil3.disk.directory
import coil3.network.okhttp.OkHttpNetworkFetcherFactory
import coil3.request.crossfade
import coil3.svg.SvgDecoder
import io.samedia.player.core.Api
import io.samedia.player.core.AppModel

class SamediaApp : Application(), SingletonImageLoader.Factory {
    lateinit var model: AppModel
        private set

    override fun onCreate() {
        super.onCreate()
        Api.init(this)
        model = AppModel(this)
        // Reachable for remote commands while the app is open (or playing picture-in-picture)
        ProcessLifecycleOwner.get().lifecycle.addObserver(object : DefaultLifecycleObserver {
            override fun onStart(owner: LifecycleOwner) {
                model.foreground = true
                model.remote.start()
            }

            override fun onStop(owner: LifecycleOwner) {
                model.foreground = false
                model.remote.stop()
            }
        })
    }

    override fun newImageLoader(context: PlatformContext): ImageLoader = ImageLoader.Builder(context)
        .components {
            add(OkHttpNetworkFetcherFactory(callFactory = { Api.http }))
            add(SvgDecoder.Factory())
        }
        .diskCache { DiskCache.Builder().directory(cacheDir.resolve("art")).maxSizeBytes(256L shl 20).build() }
        .crossfade(true)
        .build()
}
