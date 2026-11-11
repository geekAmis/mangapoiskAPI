package ru.mangapoisk.reborn

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import ru.mangapoisk.reborn.ui.LocalAppContainer
import ru.mangapoisk.reborn.ui.LocalBaseUrl
import ru.mangapoisk.reborn.ui.LocalThemeId
import ru.mangapoisk.reborn.ui.navigation.AppRoot
import ru.mangapoisk.reborn.ui.theme.MangaPoiskTheme
import ru.mangapoisk.reborn.ui.theme.ThemeId

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val container = (application as MangaApp).container
        setContent {
            val settings by container.settingsStore.settings.collectAsStateWithLifecycle(
                initialValue = container.settingsStore.initial,
            )
            MangaPoiskTheme(themeKey = settings.themeId) {
                CompositionLocalProvider(
                    LocalAppContainer provides container,
                    LocalBaseUrl provides settings.baseUrl,
                    LocalThemeId provides ThemeId.fromKey(settings.themeId),
                ) {
                    AppRoot()
                }
            }
        }
    }
}
