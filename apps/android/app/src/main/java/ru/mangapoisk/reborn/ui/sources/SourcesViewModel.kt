package ru.mangapoisk.reborn.ui.sources

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import ru.mangapoisk.reborn.data.model.Source
import ru.mangapoisk.reborn.data.remote.AppError
import ru.mangapoisk.reborn.data.remote.toAppError
import ru.mangapoisk.reborn.data.repo.CatalogRepository
import ru.mangapoisk.reborn.di.AppContainer

data class SourcesUiState(
    val isLoading: Boolean = true,
    val sources: List<Source> = emptyList(),
    val error: AppError? = null,
)

class SourcesViewModel(
    private val catalogRepository: CatalogRepository,
) : ViewModel() {
    private val _state = MutableStateFlow(SourcesUiState())
    val state = _state.asStateFlow()

    init {
        load()
    }

    fun load() {
        _state.update { it.copy(isLoading = true, error = null) }
        viewModelScope.launch {
            catalogRepository.sources(includeDisabled = true).fold(
                onSuccess = { sources ->
                    _state.update {
                        it.copy(isLoading = false, sources = sources, error = null)
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

    companion object {
        fun factory(container: AppContainer) = viewModelFactory {
            initializer {
                SourcesViewModel(catalogRepository = container.catalogRepository)
            }
        }
    }
}
