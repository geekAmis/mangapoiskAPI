package ru.mangapoisk.reborn.ui.library

import androidx.lifecycle.ViewModel
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
import ru.mangapoisk.reborn.data.local.entity.BookmarkEntity
import ru.mangapoisk.reborn.data.local.entity.DownloadEntity
import ru.mangapoisk.reborn.data.local.entity.ProgressEntity
import ru.mangapoisk.reborn.data.repo.DownloadRepository
import ru.mangapoisk.reborn.data.repo.LibraryRepository
import ru.mangapoisk.reborn.di.AppContainer

sealed interface LibraryEvent {
    data object SyncFailed : LibraryEvent
}

data class LibraryUiState(
    val bookmarks: List<BookmarkEntity> = emptyList(),
    val progress: List<ProgressEntity> = emptyList(),
    val downloads: List<DownloadEntity> = emptyList(),
    val isSyncing: Boolean = false,
)

class LibraryViewModel(
    private val libraryRepository: LibraryRepository,
    private val downloadRepository: DownloadRepository,
) : ViewModel() {

    private val _state = MutableStateFlow(LibraryUiState())
    val state = _state.asStateFlow()
    private val _events = MutableSharedFlow<LibraryEvent>(extraBufferCapacity = 1)
    val events = _events.asSharedFlow()
    private var syncJob: Job? = null

    init {
        viewModelScope.launch {
            libraryRepository.bookmarks.collect { bookmarks ->
                _state.update { it.copy(bookmarks = bookmarks) }
            }
        }
        viewModelScope.launch {
            libraryRepository.progress.collect { progress ->
                _state.update { it.copy(progress = progress) }
            }
        }
        viewModelScope.launch {
            libraryRepository.downloads.collect { downloads ->
                _state.update { it.copy(downloads = downloads) }
            }
        }
        sync()
    }

    fun sync() {
        if (syncJob?.isActive == true) return
        syncJob = viewModelScope.launch {
            _state.update { it.copy(isSyncing = true) }
            libraryRepository.syncRemote().onFailure {
                _events.tryEmit(LibraryEvent.SyncFailed)
            }
            _state.update { it.copy(isSyncing = false) }
        }
    }

    fun removeHistory(mangaId: String) {
        viewModelScope.launch {
            libraryRepository.removeHistory(mangaId)
        }
    }

    fun deleteDownload(chapterId: String) {
        viewModelScope.launch {
            downloadRepository.delete(chapterId)
        }
    }

    fun retryDownload(download: DownloadEntity) {
        viewModelScope.launch {
            downloadRepository.retry(download)
        }
    }

    companion object {
        fun factory(container: AppContainer) = viewModelFactory {
            initializer {
                LibraryViewModel(
                    libraryRepository = container.libraryRepository,
                    downloadRepository = container.downloadRepository,
                )
            }
        }
    }
}
