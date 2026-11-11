package ru.mangapoisk.reborn.ui.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import ru.mangapoisk.reborn.data.local.entity.ProgressEntity
import ru.mangapoisk.reborn.data.model.Manga
import ru.mangapoisk.reborn.data.model.Source
import ru.mangapoisk.reborn.data.model.preferredTitle
import ru.mangapoisk.reborn.data.remote.AppError
import ru.mangapoisk.reborn.data.remote.toAppError
import ru.mangapoisk.reborn.data.repo.AuthRepository
import ru.mangapoisk.reborn.data.repo.CatalogRepository
import ru.mangapoisk.reborn.data.repo.LibraryRepository
import ru.mangapoisk.reborn.di.AppContainer

sealed interface HomeEvent {
    data class OpenReader(
        val chapterId: String,
        val startPage: Int,
        val mangaId: String,
        val title: String,
        val cover: String?,
    ) : HomeEvent

    data class OpenDetail(val mangaId: String) : HomeEvent
}

data class HomeUiState(
    val isLoading: Boolean = true,
    val isRefreshing: Boolean = false,
    val featured: Manga? = null,
    val popular: List<Manga> = emptyList(),
    val latest: List<Manga> = emptyList(),
    val continueReading: List<ProgressEntity> = emptyList(),
    val sources: List<Source> = emptyList(),
    val isFeaturedBookmarked: Boolean = false,
    val error: AppError? = null,
) {
    val hasContent: Boolean get() = popular.isNotEmpty() || latest.isNotEmpty() || featured != null
}

class HomeViewModel(
    private val catalogRepository: CatalogRepository,
    private val libraryRepository: LibraryRepository,
    private val authRepository: AuthRepository,
) : ViewModel() {

    private val _state = MutableStateFlow(HomeUiState())
    val state = _state.asStateFlow()
    private val _events = MutableSharedFlow<HomeEvent>(extraBufferCapacity = 1)
    val events = _events.asSharedFlow()
    private var loadJob: Job? = null
    private var bookmarkedIds: Set<String> = emptySet()

    init {
        viewModelScope.launch {
            libraryRepository.progress.collect { progress ->
                _state.update { it.copy(continueReading = progress) }
            }
        }
        viewModelScope.launch {
            libraryRepository.bookmarks.collect { bookmarks ->
                bookmarkedIds = bookmarks.mapTo(mutableSetOf()) { it.mangaId }
                _state.update { current ->
                    current.copy(
                        isFeaturedBookmarked = current.featured?.id in bookmarkedIds,
                    )
                }
            }
        }
        load()
    }

    fun load() {
        if (loadJob?.isActive == true) return
        _state.update {
            it.copy(
                isLoading = !it.hasContent,
                isRefreshing = it.hasContent,
                error = null,
            )
        }
        loadJob = viewModelScope.launch {
            val popularDeferred = async {
                catalogRepository.loadCatalog("", null, "popular", 1, 12)
            }
            val latestDeferred = async {
                catalogRepository.loadCatalog("", null, "updated", 1, 20)
            }
            val sourcesDeferred = async { catalogRepository.sources() }
            if (authRepository.isLoggedIn) {
                launch { runCatching { libraryRepository.syncRemote() } }
            }

            val popular = popularDeferred.await()
            val latest = latestDeferred.await()
            val sources = sourcesDeferred.await()

            val error = if (popular.isFailure && latest.isFailure) {
                popular.exceptionOrNull()?.toAppError()
            } else {
                null
            }
            val popularItems = popular.getOrNull()?.items.orEmpty()
            val latestItems = latest.getOrNull()?.items.orEmpty()
            val featured = popularItems.firstOrNull() ?: latestItems.firstOrNull()

            _state.update {
                it.copy(
                    isLoading = false,
                    isRefreshing = false,
                    popular = popularItems,
                    latest = latestItems,
                    featured = featured,
                    sources = sources.getOrDefault(emptyList()),
                    isFeaturedBookmarked = featured?.id in bookmarkedIds,
                    error = error,
                )
            }
        }
    }

    fun toggleFeaturedBookmark() {
        val manga = _state.value.featured ?: return
        viewModelScope.launch {
            libraryRepository.toggleBookmark(manga)
        }
    }

    fun openFeatured() {
        val manga = _state.value.featured ?: return
        viewModelScope.launch {
            val detail = catalogRepository.detail(manga.id).getOrNull()
            val firstChapter = detail?.chapters?.lastOrNull()
            if (firstChapter != null) {
                _events.emit(
                    HomeEvent.OpenReader(
                        chapterId = firstChapter.id,
                        startPage = 1,
                        mangaId = manga.id,
                        title = manga.preferredTitle(),
                        cover = manga.posterUrl,
                    ),
                )
            } else {
                _events.emit(HomeEvent.OpenDetail(manga.id))
            }
        }
    }

    fun refresh() = load()

    companion object {
        fun factory(container: AppContainer) = viewModelFactory {
            initializer {
                HomeViewModel(
                    catalogRepository = container.catalogRepository,
                    libraryRepository = container.libraryRepository,
                    authRepository = container.authRepository,
                )
            }
        }
    }
}
