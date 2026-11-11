package ru.mangapoisk.reborn.ui

import androidx.compose.runtime.staticCompositionLocalOf
import ru.mangapoisk.reborn.BuildConfig
import ru.mangapoisk.reborn.di.AppContainer
import ru.mangapoisk.reborn.ui.theme.ThemeId

val LocalAppContainer = staticCompositionLocalOf<AppContainer> {
    error("AppContainer is not provided")
}

val LocalBaseUrl = staticCompositionLocalOf { BuildConfig.DEFAULT_API_BASE_URL }

val LocalThemeId = staticCompositionLocalOf { ThemeId.MIDNIGHT }
