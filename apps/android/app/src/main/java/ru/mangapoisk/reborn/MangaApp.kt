package ru.mangapoisk.reborn

import android.app.Application
import coil.ImageLoader
import coil.ImageLoaderFactory
import okhttp3.OkHttpClient
import ru.mangapoisk.reborn.data.remote.BrowserImageInterceptor
import ru.mangapoisk.reborn.di.AppContainer

class MangaApp : Application(), ImageLoaderFactory {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
    }

    override fun newImageLoader(): ImageLoader {
        val imageClient = OkHttpClient.Builder()
            .addInterceptor(BrowserImageInterceptor())
            .build()
        return ImageLoader.Builder(this)
            .okHttpClient(imageClient)
            .crossfade(true)
            .build()
    }
}
