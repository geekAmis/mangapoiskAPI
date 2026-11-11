package ru.mangapoisk.reborn.ui.catalog

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.createSavedStateHandle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import ru.mangapoisk.reborn.data.model.Manga
import ru.mangapoisk.reborn.data.model.Source
import ru.mangapoisk.reborn.data.remote.AppError
import ru.mangapoisk.reborn.data.remote.toAppError
import ru.mangapoisk.reborn.data.repo.CatalogRepository
import ru.mangapoisk.reborn.di.AppContainer

data class CatalogUiState(
    val query: String = "",
    val selectedSource: String? = null,
    val sort: String = "popular",
    val items: List<Manga> = emptyList(),
    val sources: List<Source> = emptyList(),
    val total: Int = 0,
    val page: Int = 1,
    val hasNext: Boolean = false,
    val isLoading: Boolean = true,
    val isLoadingMore: Boolean = false,
    val error: AppError? = null,
)

class CatalogViewModel(
    savedStateHandle: SavedStateHandle,
    private val catalogRepository: CatalogRepository,
) : ViewModel() {

    private val _state = MutableStateFlow(
        CatalogUiState(
            selectedSource = savedStateHandle.get<String>("source")?.takeIf { it.isNotBlank() },
            sort = savedStateHandle.get<String>("sort")?.takeIf { it.isNotBlank() } ?: "popular",
        ),
    )
    val state = _state.asStateFlow()

    private var loadJob: Job? = null
    private var loadMoreJob: Job? = null
    private var queryJob: Job? = null

    init {
        loadSources()
        reload()
    }

    fun setQuery(value: String) {
        _state.update { it.copy(query = value) }
        queryJob?.cancel()
        queryJob = viewModelScope.launch {
            delay(350)
            reload()
        }
    }

    fun submitSearch() {
        queryJob?.cancel()
        reload()
    }

    fun setSource(code: String?) {
        if (_state.value.selectedSource == code) return
        _state.update { it.copy(selectedSource = code) }
        reload()
    }

    fun setSort(sort: String) {
        if (_state.value.sort == sort) return
        _state.update { it.copy(sort = sort) }
        reload()
    }

    fun resetFilters() {
        queryJob?.cancel()
        _state.update {
            it.copy(query = "", selectedSource = null, sort = "popular")
        }
        reload()
    }

    fun loadMore() {
        val snapshot = _state.value
        if (!snapshot.hasNext || snapshot.isLoading || snapshot.isLoadingMore) return
        if (loadMoreJob?.isActive == true) return

        loadMoreJob = viewModelScope.launch {
            _state.update { it.copy(isLoadingMore = true, error = null) }
            val nextPage = snapshot.page + 1
            val result = catalogRepository.loadCatalog(
                query = snapshot.query,
                source = snapshot.selectedSource,
                sort = snapshot.sort,
                page = nextPage,
            )
            result.fold(
                onSuccess = { page ->
                    _state.update { current ->
                        val existingIds = current.items.mapTo(mutableSetOf()) { it.id }
                        val newItems = page.items.filter { existingIds.add(it.id) }
                        current.copy(
                            items = current.items + newItems,
                            page = page.page,
                            total = page.total,
                            hasNext = page.hasNext,
                            isLoadingMore = false,
                            error = null,
                        )
                    }
                },
                onFailure = { throwable ->
                    _state.update {
                        it.copy(
                            isLoadingMore = false,
                            error = throwable.toAppError(),
                        )
                    }
                },
            )
        }
    }

    fun reload() {
        loadJob?.cancel()
        loadMoreJob?.cancel()
        val snapshot = _state.value
        loadJob = viewModelScope.launch {
            _state.update {
                it.copy(
                    isLoading = true,
                    isLoadingMore = false,
                    error = null,
                    page = 1,
                )
            }
            val result = catalogRepository.loadCatalog(
                query = snapshot.query,
                source = snapshot.selectedSource,
                sort = snapshot.sort,
                page = 1,
            )
            result.fold(
                onSuccess = { page ->
                    _state.update {
                        it.copy(
                            items = page.items,
                            total = page.total,
                            page = page.page,
                            hasNext = page.hasNext,
                            isLoading = false,
                            error = null,
                        )
                    }
                },
                onFailure = { throwable ->
                    _state.update {
                        it.copy(
                            items = emptyList(),
                            total = 0,
                            hasNext = false,
                            isLoading = false,
                            error = throwable.toAppError(),
                        )
                    }
                },
            )
        }
    }

    private fun loadSources() {
        viewModelScope.launch {
            catalogRepository.sources().onSuccess { sources ->
                _state.update { it.copy(sources = sources) }
            }
        }
    }

    companion object {
        fun factory(container: AppContainer) = viewModelFactory {
            initializer {
                CatalogViewModel(
                    savedStateHandle = createSavedStateHandle(),
                    catalogRepository = container.catalogRepository,
                )
            }
        }
    }
}
