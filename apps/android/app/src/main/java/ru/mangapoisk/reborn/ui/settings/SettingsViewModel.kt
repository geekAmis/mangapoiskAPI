package ru.mangapoisk.reborn.ui.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import ru.mangapoisk.reborn.BuildConfig
import ru.mangapoisk.reborn.data.local.AppSettings
import ru.mangapoisk.reborn.data.local.SettingsStore
import ru.mangapoisk.reborn.data.model.AuthUser
import ru.mangapoisk.reborn.data.repo.AuthRepository
import ru.mangapoisk.reborn.data.repo.DownloadRepository
import ru.mangapoisk.reborn.data.repo.LibraryRepository
import ru.mangapoisk.reborn.di.AppContainer

sealed interface SettingsEvent {
    data object InvalidUrl : SettingsEvent
    data object InsecureUrl : SettingsEvent
    data class BaseUrlSaved(val loggedOut: Boolean) : SettingsEvent
    data object LoggedOut : SettingsEvent
    data object DownloadsCleared : SettingsEvent
    data object HistoryCleared : SettingsEvent
}

data class SettingsUiState(
    val settings: AppSettings = AppSettings(),
    val baseUrlInput: String = BuildConfig.DEFAULT_API_BASE_URL,
    val user: AuthUser? = null,
)

class SettingsViewModel(
    private val settingsStore: SettingsStore,
    private val authRepository: AuthRepository,
    private val downloadRepository: DownloadRepository,
    private val libraryRepository: LibraryRepository,
) : ViewModel() {

    private val _state = MutableStateFlow(
        SettingsUiState(
            settings = settingsStore.initial,
            baseUrlInput = settingsStore.initial.baseUrl,
            user = authRepository.user.value,
        ),
    )
    val state = _state.asStateFlow()
    private val _events = MutableSharedFlow<SettingsEvent>(extraBufferCapacity = 2)
    val events = _events.asSharedFlow()
    private var baseUrlEditing = false

    init {
        viewModelScope.launch {
            settingsStore.settings.collect { settings ->
                _state.update { current ->
                    current.copy(
                        settings = settings,
                        baseUrlInput = if (baseUrlEditing) current.baseUrlInput else settings.baseUrl,
                    )
                }
            }
        }
        viewModelScope.launch {
            authRepository.user.collect { user ->
                _state.update { it.copy(user = user) }
            }
        }
        viewModelScope.launch {
            if (authRepository.isLoggedIn) {
                runCatching { authRepository.refreshProfile() }
            }
        }
    }

    fun onBaseUrlChange(value: String) {
        baseUrlEditing = true
        _state.update { it.copy(baseUrlInput = value) }
    }

    fun saveBaseUrl() {
        val input = _state.value.baseUrlInput.trim()
        if (!settingsStore.isValidBaseUrl(input)) {
            _events.tryEmit(SettingsEvent.InvalidUrl)
            return
        }
        if (!BuildConfig.DEBUG && input.startsWith("http://", ignoreCase = true)) {
            _events.tryEmit(SettingsEvent.InsecureUrl)
            return
        }
        val normalized = settingsStore.normalizeBaseUrl(input)
        val changed = normalized != _state.value.settings.baseUrl
        val wasLoggedIn = _state.value.user != null
        viewModelScope.launch {
            settingsStore.updateBaseUrl(normalized)
            if (changed && wasLoggedIn) {
                authRepository.localLogout()
            }
            baseUrlEditing = false
            _state.update { it.copy(baseUrlInput = normalized) }
            _events.tryEmit(SettingsEvent.BaseUrlSaved(changed && wasLoggedIn))
        }
    }

    fun resetBaseUrl() {
        baseUrlEditing = false
        _state.update { it.copy(baseUrlInput = BuildConfig.DEFAULT_API_BASE_URL) }
        saveBaseUrl()
    }

    fun setTheme(themeKey: String) {
        viewModelScope.launch { settingsStore.updateTheme(themeKey) }
    }

    fun setReaderMode(mode: String) {
        viewModelScope.launch { settingsStore.updateReaderMode(mode) }
    }

    fun setPageFit(fit: String) {
        viewModelScope.launch { settingsStore.updatePageFit(fit) }
    }

    fun setAutoScrollSpeed(speed: Int) {
        viewModelScope.launch { settingsStore.updateAutoScrollSpeed(speed) }
    }

    fun setKeepScreenOn(enabled: Boolean) {
        viewModelScope.launch { settingsStore.updateKeepScreenOn(enabled) }
    }

    fun logout() {
        viewModelScope.launch {
            authRepository.logout()
            _events.tryEmit(SettingsEvent.LoggedOut)
        }
    }

    fun clearDownloads() {
        viewModelScope.launch {
            downloadRepository.clearAll()
            _events.tryEmit(SettingsEvent.DownloadsCleared)
        }
    }

    fun clearHistory() {
        viewModelScope.launch {
            libraryRepository.clearHistory()
            _events.tryEmit(SettingsEvent.HistoryCleared)
        }
    }

    companion object {
        fun factory(container: AppContainer) = viewModelFactory {
            initializer {
                SettingsViewModel(
                    settingsStore = container.settingsStore,
                    authRepository = container.authRepository,
                    downloadRepository = container.downloadRepository,
                    libraryRepository = container.libraryRepository,
                )
            }
        }
    }
}
