package ru.mangapoisk.reborn.ui.reader

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.createSavedStateHandle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import ru.mangapoisk.reborn.data.model.ChapterDetail
import ru.mangapoisk.reborn.data.model.Manga
import ru.mangapoisk.reborn.data.remote.AppError
import ru.mangapoisk.reborn.data.remote.toAppError
import ru.mangapoisk.reborn.data.repo.CatalogRepository
import ru.mangapoisk.reborn.data.repo.DownloadRepository
import ru.mangapoisk.reborn.data.repo.LibraryRepository
import ru.mangapoisk.reborn.di.AppContainer
import java.io.File

data class ReaderPage(
    val number: Int,
    val url: String,
    val width: Int?,
    val height: Int?,
    val localFile: File?,
)

data class ReaderUiState(
    val isLoading: Boolean = true,
    val chapterId: String = "",
    val mangaId: String = "",
    val mangaTitle: String = "",
    val coverUrl: String? = null,
    val volume: String? = null,
    val number: String? = null,
    val chapterTitle: String? = null,
    val localLabel: String? = null,
    val pages: List<ReaderPage> = emptyList(),
    val currentPage: Int = 1,
    val prevChapterId: String? = null,
    val nextChapterId: String? = null,
    val isLocal: Boolean = false,
    val isBookmarked: Boolean = false,
    val pendingResumePage: Int? = null,
    val error: AppError? = null,
)

class ReaderViewModel(
    savedStateHandle: SavedStateHandle,
    private val catalogRepository: CatalogRepository,
    private val libraryRepository: LibraryRepository,
    private val downloadRepository: DownloadRepository,
) : ViewModel() {

    private val initialChapterId: String = checkNotNull(savedStateHandle["chapterId"])
    private val initialMangaId: String = savedStateHandle.get<String>("mangaId").orEmpty()
    private val initialMangaTitle: String = savedStateHandle.get<String>("title").orEmpty()
    private val initialCoverUrl: String? = savedStateHandle.get<String>("cover")
        ?.takeIf { it.isNotBlank() }
    private val initialStartPage: Int = savedStateHandle.get<Int>("startPage") ?: 1

    private val _state = MutableStateFlow(
        ReaderUiState(
            chapterId = initialChapterId,
            mangaId = initialMangaId,
            mangaTitle = initialMangaTitle,
            coverUrl = initialCoverUrl,
            currentPage = 1,
            pendingResumePage = initialStartPage.takeIf { it > 1 },
        ),
    )
    val state = _state.asStateFlow()

    private var loadJob: Job? = null
    private var progressJob: Job? = null

    init {
        viewModelScope.launch {
            libraryRepository.bookmarks.collect { bookmarks ->
                _state.update {
                    it.copy(isBookmarked = bookmarks.any { b -> b.mangaId == it.mangaId })
                }
            }
        }
        loadChapter(initialChapterId, initialStartPage, showResumePrompt = true)
    }

    fun toggleBookmark() {
        val snapshot = _state.value
        if (snapshot.mangaId.isBlank()) return
        val manga = Manga(
            id = snapshot.mangaId,
            title = snapshot.mangaTitle,
            posterUrl = snapshot.coverUrl,
            source = "",
        )
        viewModelScope.launch {
            libraryRepository.toggleBookmark(manga)
        }
    }

    fun onPageChanged(page: Int) {
        val snapshot = _state.value
        if (snapshot.pages.isEmpty()) return
        val clamped = page.coerceIn(1, snapshot.pages.size)
        if (clamped == snapshot.currentPage) return
        _state.update { it.copy(currentPage = clamped) }
        scheduleProgressWrite()
    }

    fun continueFromResume() {
        val page = _state.value.pendingResumePage ?: return
        _state.update {
            it.copy(
                pendingResumePage = null,
                currentPage = page.coerceIn(1, it.pages.size.coerceAtLeast(1)),
            )
        }
        scheduleProgressWrite()
    }

    fun restartChapter() {
        _state.update {
            it.copy(
                pendingResumePage = null,
                currentPage = 1,
            )
        }
        scheduleProgressWrite()
    }

    fun previousChapter() {
        val id = _state.value.prevChapterId ?: return
        loadChapter(id, 1, showResumePrompt = false)
    }

    fun nextChapter() {
        val id = _state.value.nextChapterId ?: return
        loadChapter(id, 1, showResumePrompt = false)
    }

    fun retry() {
        loadChapter(
            chapterId = _state.value.chapterId,
            startPage = _state.value.pendingResumePage ?: _state.value.currentPage,
            showResumePrompt = _state.value.pendingResumePage != null,
        )
    }

    fun flushProgress() {
        progressJob?.cancel()
        if (_state.value.pages.isEmpty()) return
        if (_state.value.pendingResumePage != null) return
        viewModelScope.launch { saveProgressNow() }
    }

    private fun loadChapter(
        chapterId: String,
        startPage: Int,
        showResumePrompt: Boolean,
    ) {
        loadJob?.cancel()
        progressJob?.cancel()
        _state.update {
            it.copy(
                isLoading = true,
                error = null,
                chapterId = chapterId,
                pages = emptyList(),
                currentPage = 1,
                pendingResumePage = if (showResumePrompt && startPage > 1) startPage else null,
                volume = null,
                number = null,
                chapterTitle = null,
                localLabel = null,
                prevChapterId = null,
                nextChapterId = null,
                isLocal = false,
            )
        }

        loadJob = viewModelScope.launch {
            val localDeferred = async { downloadRepository.getLocalChapter(chapterId) }
            val remoteResult = catalogRepository.chapter(chapterId)
            val local = localDeferred.await()

            remoteResult.fold(
                onSuccess = { detail ->
                    applyRemoteChapter(detail, local, startPage)
                },
                onFailure = { throwable ->
                    if (local != null) {
                        applyLocalChapter(local, startPage)
                    } else {
                        _state.update {
                            it.copy(
                                isLoading = false,
                                error = throwable.toAppError(),
                            )
                        }
                    }
                },
            )
        }
    }

    private fun applyRemoteChapter(
        detail: ChapterDetail,
        local: ru.mangapoisk.reborn.data.repo.LocalChapter?,
        startPage: Int,
    ) {
        val localPages = local?.pages?.associateBy { it.number } ?: emptyMap()
        val pages = detail.pages.mapIndexed { index, page ->
            val number = if (page.number > 0) page.number else index + 1
            ReaderPage(
                number = number,
                url = page.url,
                width = page.width,
                height = page.height,
                localFile = localPages[number]?.file,
            )
        }
        val hasResumePrompt = _state.value.pendingResumePage != null
        val page = if (hasResumePrompt) {
            1
        } else {
            startPage.coerceIn(1, pages.size.coerceAtLeast(1))
        }

        _state.update {
            it.copy(
                isLoading = false,
                error = null,
                chapterId = detail.id,
                mangaId = detail.mangaId.ifBlank { it.mangaId },
                mangaTitle = it.mangaTitle.ifBlank { local?.mangaTitle.orEmpty() },
                coverUrl = it.coverUrl ?: local?.coverUrl,
                volume = detail.volume,
                number = detail.number,
                chapterTitle = detail.title,
                localLabel = null,
                pages = pages,
                currentPage = page,
                prevChapterId = detail.prevChapterId,
                nextChapterId = detail.nextChapterId,
                isLocal = local != null,
            )
        }
        if (!hasResumePrompt) {
            scheduleProgressWrite()
        }
    }

    private fun applyLocalChapter(
        local: ru.mangapoisk.reborn.data.repo.LocalChapter,
        startPage: Int,
    ) {
        val pages = local.pages.sortedBy { it.number }.map { page ->
            ReaderPage(
                number = page.number,
                url = "",
                width = page.width,
                height = page.height,
                localFile = page.file,
            )
        }
        val hasResumePrompt = _state.value.pendingResumePage != null
        val page = if (hasResumePrompt) {
            1
        } else {
            startPage.coerceIn(1, pages.size.coerceAtLeast(1))
        }
        _state.update {
            it.copy(
                isLoading = false,
                error = null,
                chapterId = local.chapterId,
                mangaId = local.mangaId.ifBlank { it.mangaId },
                mangaTitle = it.mangaTitle.ifBlank { local.mangaTitle },
                coverUrl = it.coverUrl ?: local.coverUrl,
                volume = null,
                number = null,
                chapterTitle = null,
                localLabel = local.chapterLabel.ifBlank { null },
                pages = pages,
                currentPage = page,
                prevChapterId = null,
                nextChapterId = null,
                isLocal = true,
            )
        }
        if (!hasResumePrompt) {
            scheduleProgressWrite()
        }
    }

    private fun scheduleProgressWrite() {
        if (_state.value.pendingResumePage != null) return
        progressJob?.cancel()
        progressJob = viewModelScope.launch {
            delay(800)
            saveProgressNow()
        }
    }

    private suspend fun saveProgressNow() {
        val snapshot = _state.value
        if (snapshot.pages.isEmpty() || snapshot.mangaId.isBlank()) return
        val label = snapshot.number
            ?: snapshot.chapterTitle
            ?: snapshot.localLabel
            ?: "—"
        libraryRepository.saveProgressRaw(
            mangaId = snapshot.mangaId,
            mangaTitle = snapshot.mangaTitle,
            posterUrl = snapshot.coverUrl,
            chapterId = snapshot.chapterId,
            chapterLabel = label,
            page = snapshot.currentPage,
            totalPages = snapshot.pages.size,
        )
    }

    companion object {
        fun factory(container: AppContainer) = viewModelFactory {
            initializer {
                ReaderViewModel(
                    savedStateHandle = createSavedStateHandle(),
                    catalogRepository = container.catalogRepository,
                    libraryRepository = container.libraryRepository,
                    downloadRepository = container.downloadRepository,
                )
            }
        }
    }
}
