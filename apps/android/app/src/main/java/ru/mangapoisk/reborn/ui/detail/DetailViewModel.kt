package ru.mangapoisk.reborn.ui.detail

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.createSavedStateHandle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import ru.mangapoisk.reborn.data.local.entity.DownloadEntity
import ru.mangapoisk.reborn.data.local.entity.ProgressEntity
import ru.mangapoisk.reborn.data.model.Chapter
import ru.mangapoisk.reborn.data.model.MangaDetail
import ru.mangapoisk.reborn.data.remote.AppError
import ru.mangapoisk.reborn.data.remote.toAppError
import ru.mangapoisk.reborn.data.repo.AuthRepository
import ru.mangapoisk.reborn.data.repo.CatalogRepository
import ru.mangapoisk.reborn.data.repo.DownloadRepository
import ru.mangapoisk.reborn.data.repo.LibraryRepository
import ru.mangapoisk.reborn.di.AppContainer

sealed interface DetailEvent {
    data object DownloadQueued : DetailEvent
    data object DownloadFailed : DetailEvent
    data object BookmarkFailed : DetailEvent
}

data class DetailUiState(
    val isLoading: Boolean = true,
    val manga: MangaDetail? = null,
    val isBookmarked: Boolean = false,
    val progress: ProgressEntity? = null,
    val downloads: Map<String, DownloadEntity> = emptyMap(),
    val error: AppError? = null,
)

class DetailViewModel(
    savedStateHandle: SavedStateHandle,
    private val catalogRepository: CatalogRepository,
    private val libraryRepository: LibraryRepository,
    private val downloadRepository: DownloadRepository,
    private val authRepository: AuthRepository,
) : ViewModel() {

    private val mangaId: String = checkNotNull(savedStateHandle["mangaId"])
    private val _state = MutableStateFlow(DetailUiState())
    val state = _state.asStateFlow()
    private val _events = MutableSharedFlow<DetailEvent>(extraBufferCapacity = 1)
    val events = _events.asSharedFlow()
    private var loadJob: Job? = null

    init {
        viewModelScope.launch {
            libraryRepository.bookmarks.collect { bookmarks ->
                _state.update { it.copy(isBookmarked = bookmarks.any { b -> b.mangaId == mangaId }) }
            }
        }
        viewModelScope.launch {
            libraryRepository.progress.collect { progress ->
                _state.update { it.copy(progress = progress.firstOrNull { p -> p.mangaId == mangaId }) }
            }
        }
        viewModelScope.launch {
            downloadRepository.observeForManga(mangaId).collect { downloads ->
                _state.update {
                    it.copy(downloads = downloads.associateBy { download -> download.chapterId })
                }
            }
        }
        load()
    }

    fun load() {
        if (loadJob?.isActive == true) return
        loadJob = viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            catalogRepository.detail(mangaId).fold(
                onSuccess = { detail ->
                    _state.update { it.copy(isLoading = false, manga = detail, error = null) }
                    if (authRepository.isLoggedIn) {
                        launch { runCatching { libraryRepository.syncRemote() } }
                    }
                },
                onFailure = { throwable ->
                    _state.update {
                        it.copy(isLoading = false, error = throwable.toAppError())
                    }
                },
            )
        }
    }

    fun toggleBookmark() {
        val manga = _state.value.manga?.manga ?: return
        viewModelScope.launch {
            libraryRepository.toggleBookmark(manga).onFailure {
                _events.tryEmit(DetailEvent.BookmarkFailed)
            }
        }
    }

    fun downloadChapter(chapter: Chapter) {
        val manga = _state.value.manga?.manga ?: return
        viewModelScope.launch {
            downloadRepository.enqueue(chapter, manga).fold(
                onSuccess = { _events.tryEmit(DetailEvent.DownloadQueued) },
                onFailure = { _events.tryEmit(DetailEvent.DownloadFailed) },
            )
        }
    }

    companion object {
        fun factory(container: AppContainer) = viewModelFactory {
            initializer {
                DetailViewModel(
                    savedStateHandle = createSavedStateHandle(),
                    catalogRepository = container.catalogRepository,
                    libraryRepository = container.libraryRepository,
                    downloadRepository = container.downloadRepository,
                    authRepository = container.authRepository,
                )
            }
        }
    }
}
