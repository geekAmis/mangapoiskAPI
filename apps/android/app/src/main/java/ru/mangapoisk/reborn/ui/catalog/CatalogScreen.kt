package ru.mangapoisk.reborn.ui.catalog

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items as gridItems
import androidx.compose.foundation.lazy.grid.rememberLazyGridState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.AssistChip
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import ru.mangapoisk.reborn.R
import ru.mangapoisk.reborn.data.model.Source
import ru.mangapoisk.reborn.ui.LocalAppContainer
import ru.mangapoisk.reborn.ui.components.EmptyState
import ru.mangapoisk.reborn.ui.components.ErrorState
import ru.mangapoisk.reborn.ui.components.MangaCard
import ru.mangapoisk.reborn.ui.components.SkeletonPoster
import ru.mangapoisk.reborn.ui.theme.MangaTheme
import ru.mangapoisk.reborn.ui.util.userMessage

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CatalogScreen(onMangaClick: (String) -> Unit) {
    val container = LocalAppContainer.current
    val viewModel: CatalogViewModel = viewModel(
        factory = remember(container) { CatalogViewModel.factory(container) },
    )
    val state by viewModel.state.collectAsStateWithLifecycle()
    val gridState = rememberLazyGridState()
    val focusManager = LocalFocusManager.current
    var sortMenuOpen by remember { mutableStateOf(false) }

    LaunchedEffect(gridState, state.items.size, state.hasNext) {
        snapshotFlow {
            gridState.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: -1
        }.collect { lastVisible ->
            if (state.hasNext && lastVisible >= state.items.size - 4) {
                viewModel.loadMore()
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.catalog_title)) },
                actions = {
                    IconButton(onClick = viewModel::reload) {
                        Icon(
                            imageVector = Icons.Default.Refresh,
                            contentDescription = stringResource(R.string.cd_refresh),
                        )
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            OutlinedTextField(
                value = state.query,
                onValueChange = viewModel::setQuery,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 6.dp),
                singleLine = true,
                placeholder = { Text(stringResource(R.string.catalog_search_hint)) },
                leadingIcon = {
                    Icon(
                        imageVector = Icons.Default.Search,
                        contentDescription = stringResource(R.string.cd_search),
                    )
                },
                trailingIcon = {
                    if (state.query.isNotEmpty()) {
                        IconButton(onClick = { viewModel.setQuery("") }) {
                            Icon(
                                imageVector = Icons.Default.Close,
                                contentDescription = stringResource(R.string.catalog_search_clear),
                            )
                        }
                    }
                },
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                keyboardActions = KeyboardActions(
                    onSearch = {
                        focusManager.clearFocus()
                        viewModel.submitSearch()
                    },
                ),
                shape = MaterialTheme.shapes.extraLarge,
            )

            LazyRow(
                contentPadding = PaddingValues(horizontal = 16.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                item(key = "all-sources") {
                    FilterChip(
                        selected = state.selectedSource == null,
                        onClick = { viewModel.setSource(null) },
                        label = { Text(stringResource(R.string.catalog_source_all)) },
                    )
                }
                items(state.sources, key = { it.code }) { source ->
                    SourceFilterChip(
                        source = source,
                        selected = state.selectedSource == source.code,
                        onClick = { viewModel.setSource(source.code) },
                    )
                }
            }

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = if (state.total > 0) {
                        stringResource(R.string.catalog_results_count, state.total)
                    } else {
                        ""
                    },
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.weight(1f),
                )
                Box {
                    AssistChip(
                        onClick = { sortMenuOpen = true },
                        label = { Text(sortLabel(state.sort)) },
                        trailingIcon = {
                            Icon(
                                imageVector = Icons.Default.ArrowDropDown,
                                contentDescription = stringResource(R.string.catalog_sort_label),
                            )
                        },
                    )
                    DropdownMenu(
                        expanded = sortMenuOpen,
                        onDismissRequest = { sortMenuOpen = false },
                    ) {
                        val options = listOf(
                            "popular" to R.string.catalog_sort_popular,
                            "rating" to R.string.catalog_sort_rating,
                            "updated" to R.string.catalog_sort_updated,
                            "title" to R.string.catalog_sort_title,
                        )
                        options.forEach { (key, labelRes) ->
                            DropdownMenuItem(
                                text = { Text(stringResource(labelRes)) },
                                onClick = {
                                    sortMenuOpen = false
                                    viewModel.setSort(key)
                                },
                            )
                        }
                    }
                }
            }

            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
            ) {
                when {
                    state.isLoading && state.items.isEmpty() -> {
                        SkeletonGrid()
                    }

                    state.error != null && state.items.isEmpty() -> {
                        ErrorState(
                            error = state.error,
                            onRetry = viewModel::reload,
                            modifier = Modifier.fillMaxSize(),
                        )
                    }

                    state.items.isEmpty() -> {
                        EmptyState(
                            title = stringResource(R.string.catalog_empty_title),
                            text = stringResource(R.string.catalog_empty_text),
                            icon = Icons.Default.Search,
                            actionLabel = stringResource(R.string.catalog_reset_filters),
                            onAction = viewModel::resetFilters,
                            modifier = Modifier.fillMaxSize(),
                        )
                    }

                    else -> {
                        LazyVerticalGrid(
                            columns = GridCells.Adaptive(minSize = 148.dp),
                            state = gridState,
                            modifier = Modifier.fillMaxSize(),
                            contentPadding = PaddingValues(16.dp),
                            horizontalArrangement = Arrangement.spacedBy(12.dp),
                            verticalArrangement = Arrangement.spacedBy(16.dp),
                        ) {
                            gridItems(state.items, key = { it.id }) { manga ->
                                MangaCard(
                                    manga = manga,
                                    onClick = { onMangaClick(manga.id) },
                                    modifier = Modifier.fillMaxWidth(),
                                )
                            }

                            item(span = { GridItemSpan(maxLineSpan) }) {
                                CatalogFooter(
                                    isLoadingMore = state.isLoadingMore,
                                    errorText = state.error?.userMessage(),
                                    hasNext = state.hasNext,
                                    onRetry = viewModel::loadMore,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun SourceFilterChip(
    source: Source,
    selected: Boolean,
    onClick: () -> Unit,
) {
    FilterChip(
        selected = selected,
        onClick = onClick,
        label = {
            Text(
                text = source.name,
                maxLines = 1,
            )
        },
    )
}

@Composable
private fun sortLabel(sort: String): String = stringResource(
    when (sort) {
        "rating" -> R.string.catalog_sort_rating
        "updated" -> R.string.catalog_sort_updated
        "title" -> R.string.catalog_sort_title
        else -> R.string.catalog_sort_popular
    },
)

@Composable
private fun SkeletonGrid() {
    LazyVerticalGrid(
        columns = GridCells.Adaptive(minSize = 148.dp),
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
        userScrollEnabled = false,
    ) {
        items(8) {
            SkeletonPoster(Modifier.fillMaxWidth())
        }
    }
}

@Composable
private fun CatalogFooter(
    isLoadingMore: Boolean,
    errorText: String?,
    hasNext: Boolean,
    onRetry: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        when {
            isLoadingMore -> {
                CircularProgressIndicator(
                    modifier = Modifier.size(22.dp),
                    strokeWidth = 2.dp,
                )
                Spacer(Modifier.height(6.dp))
                Text(
                    text = stringResource(R.string.catalog_loading_more),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            errorText != null -> {
                Text(
                    text = errorText,
                    style = MaterialTheme.typography.bodySmall,
                    color = MangaTheme.colors.dangerText,
                    textAlign = TextAlign.Center,
                )
                TextButton(onClick = onRetry) {
                    Text(stringResource(R.string.action_retry))
                }
            }

            !hasNext -> {
                Text(
                    text = stringResource(R.string.catalog_all_loaded),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
                )
            }
        }
    }
}
