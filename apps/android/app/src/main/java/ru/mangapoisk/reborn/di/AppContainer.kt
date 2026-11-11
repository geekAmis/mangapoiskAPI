package ru.mangapoisk.reborn.di

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import ru.mangapoisk.reborn.data.local.MangaDatabase
import ru.mangapoisk.reborn.data.local.SessionManager
import ru.mangapoisk.reborn.data.local.SettingsStore
import ru.mangapoisk.reborn.data.local.TokenStore
import ru.mangapoisk.reborn.data.remote.MangaApi
import ru.mangapoisk.reborn.data.remote.NetworkFactory
import ru.mangapoisk.reborn.data.repo.AuthRepository
import ru.mangapoisk.reborn.data.repo.CatalogRepository
import ru.mangapoisk.reborn.data.repo.DownloadRepository
import ru.mangapoisk.reborn.data.repo.LibraryRepository
import okhttp3.OkHttpClient

/**
 * Manual dependency container.  Deliberately small and explicit: no Hilt, no
 * annotation processing beyond Room, and no service locator hidden in a static.
 */
class AppContainer(context: Context) {
    private val appContext = context.applicationContext
    private val applicationScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    val json: Json = NetworkFactory.json()
    val settingsStore = SettingsStore(appContext)
    val tokenStore = TokenStore(appContext, json)
    val sessionManager = SessionManager(tokenStore)

    private val apiBundle = NetworkFactory.createApi(
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        sessionManager = sessionManager,
        json = json,
    )

    val api: MangaApi = apiBundle.api
    val downloadClient: OkHttpClient = apiBundle.downloadClient

    val database: MangaDatabase = MangaDatabase.get(appContext)

    val catalogRepository = CatalogRepository(api, settingsStore)
    val authRepository = AuthRepository(api, sessionManager, tokenStore)
    val libraryRepository = LibraryRepository(api, sessionManager, database)
    val downloadRepository = DownloadRepository(appContext, database, json)

    init {
        // Persisted settings may differ from the build-time default.  Keep the
        // interceptor's volatile copy in sync as soon as DataStore emits.
        applicationScope.launch {
            settingsStore.settings.collect { settings ->
                settingsStore.syncCurrentBaseUrl(settings)
            }
        }
    }
}
