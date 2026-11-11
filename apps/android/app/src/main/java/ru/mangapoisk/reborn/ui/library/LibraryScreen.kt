package ru.mangapoisk.reborn.ui.library

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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items as gridItems
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.BookmarkBorder
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Replay
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import ru.mangapoisk.reborn.R
import ru.mangapoisk.reborn.data.local.entity.BookmarkEntity
import ru.mangapoisk.reborn.data.local.entity.DownloadEntity
import ru.mangapoisk.reborn.data.local.entity.ProgressEntity
import ru.mangapoisk.reborn.data.model.DownloadStatus
import ru.mangapoisk.reborn.data.model.Manga
import ru.mangapoisk.reborn.ui.LocalAppContainer
import ru.mangapoisk.reborn.ui.components.EmptyState
import ru.mangapoisk.reborn.ui.components.MangaCard
import ru.mangapoisk.reborn.ui.components.PosterImage
import ru.mangapoisk.reborn.ui.theme.MangaTheme

private enum class LibraryTab { CONTINUE, BOOKMARKS, HISTORY, DOWNLOADS }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LibraryScreen(
    onMangaClick: (String) -> Unit,
    onOpenReader: (chapterId: String, startPage: Int, mangaId: String, title: String, cover: String?) -> Unit,
    onBrowseCatalog: () -> Unit,
) {
    val container = LocalAppContainer.current
    val viewModel: LibraryViewModel = viewModel(
        factory = remember(container) { LibraryViewModel.factory(container) },
    )
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }
    val syncError = stringResource(R.string.library_sync_error)
    var selectedTab by rememberSaveable { mutableIntStateOf(0) }

    LaunchedEffect(viewModel) {
        viewModel.events.collect { event ->
            when (event) {
                LibraryEvent.SyncFailed -> snackbarHostState.showSnackbar(syncError)
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.library_title)) },
                actions = {
                    IconButton(onClick = viewModel::sync, enabled = !state.isSyncing) {
                        if (state.isSyncing) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(20.dp),
                                strokeWidth = 2.dp,
                            )
                        } else {
                            Icon(
                                imageVector = Icons.Default.Refresh,
                                contentDescription = stringResource(R.string.cd_refresh),
                            )
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
            )
        },
        snackbarHost = { SnackbarHost(snackbarHostState) },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            TabRow(selectedTabIndex = selectedTab) {
                Tab(
                    selected = selectedTab == LibraryTab.CONTINUE.ordinal,
                    onClick = { selectedTab = LibraryTab.CONTINUE.ordinal },
                    text = { Text(stringResource(R.string.library_tab_continue)) },
                )
                Tab(
                    selected = selectedTab == LibraryTab.BOOKMARKS.ordinal,
                    onClick = { selectedTab = LibraryTab.BOOKMARKS.ordinal },
                    text = { Text(stringResource(R.string.library_tab_bookmarks)) },
                )
                Tab(
                    selected = selectedTab == LibraryTab.HISTORY.ordinal,
                    onClick = { selectedTab = LibraryTab.HISTORY.ordinal },
                    text = { Text(stringResource(R.string.library_tab_history)) },
                )
                Tab(
                    selected = selectedTab == LibraryTab.DOWNLOADS.ordinal,
                    onClick = { selectedTab = LibraryTab.DOWNLOADS.ordinal },
                    text = { Text(stringResource(R.string.library_tab_downloads)) },
                )
            }

            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
            ) {
                when (LibraryTab.entries[selectedTab]) {
                    LibraryTab.CONTINUE -> HistoryTab(
                        progress = state.progress,
                        onOpen = { progress ->
                            onOpenReader(
                                progress.chapterId,
                                progress.page.coerceAtLeast(1),
                                progress.mangaId,
                                progress.mangaTitle,
                                progress.posterUrl,
                            )
                        },
                        onRemove = { viewModel.removeHistory(it.mangaId) },
                        onBrowseCatalog = onBrowseCatalog,
                    )

                    LibraryTab.BOOKMARKS -> BookmarksTab(
                        bookmarks = state.bookmarks,
                        onMangaClick = onMangaClick,
                        onBrowseCatalog = onBrowseCatalog,
                    )

                    LibraryTab.HISTORY -> HistoryTab(
                        progress = state.progress,
                        onOpen = { progress ->
                            onOpenReader(
                                progress.chapterId,
                                progress.page.coerceAtLeast(1),
                                progress.mangaId,
                                progress.mangaTitle,
                                progress.posterUrl,
                            )
                        },
                        onRemove = { viewModel.removeHistory(it.mangaId) },
                        onBrowseCatalog = onBrowseCatalog,
                    )

                    LibraryTab.DOWNLOADS -> DownloadsTab(
                        downloads = state.downloads,
                        onOpen = { download ->
                            onOpenReader(
                                download.chapterId,
                                1,
                                download.mangaId,
                                download.mangaTitle,
                                download.coverUrl,
                            )
                        },
                        onDelete = { viewModel.deleteDownload(it.chapterId) },
                        onRetry = viewModel::retryDownload,
                        onBrowseCatalog = onBrowseCatalog,
                    )
                }
            }
        }
    }
}

@Composable
private fun BookmarksTab(
    bookmarks: List<BookmarkEntity>,
    onMangaClick: (String) -> Unit,
    onBrowseCatalog: () -> Unit,
) {
    if (bookmarks.isEmpty()) {
        EmptyState(
            title = stringResource(R.string.library_bookmarks_empty),
            text = stringResource(R.string.library_bookmarks_empty_text),
            icon = Icons.Default.BookmarkBorder,
            actionLabel = stringResource(R.string.library_go_catalog),
            onAction = onBrowseCatalog,
            modifier = Modifier.fillMaxSize(),
        )
        return
    }
    LazyVerticalGrid(
        columns = GridCells.Adaptive(minSize = 148.dp),
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        gridItems(bookmarks, key = { it.mangaId }) { bookmark ->
            val manga = remember(bookmark) {
                Manga(
                    id = bookmark.mangaId,
                    source = bookmark.source,
                    title = bookmark.title,
                    posterUrl = bookmark.posterUrl,
                    adult = bookmark.adult,
                    rating = bookmark.rating,
                )
            }
            MangaCard(
                manga = manga,
                onClick = { onMangaClick(bookmark.mangaId) },
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

@Composable
private fun HistoryTab(
    progress: List<ProgressEntity>,
    onOpen: (ProgressEntity) -> Unit,
    onRemove: (ProgressEntity) -> Unit,
    onBrowseCatalog: () -> Unit,
) {
    if (progress.isEmpty()) {
        EmptyState(
            title = stringResource(R.string.library_history_empty),
            text = stringResource(R.string.library_history_empty_text),
            icon = Icons.Default.History,
            actionLabel = stringResource(R.string.library_go_catalog),
            onAction = onBrowseCatalog,
            modifier = Modifier.fillMaxSize(),
        )
        return
    }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        items(progress, key = { it.mangaId }) { item ->
            HistoryCard(
                progress = item,
                onClick = { onOpen(item) },
                onRemove = { onRemove(item) },
            )
        }
    }
}

@Composable
private fun HistoryCard(
    progress: ProgressEntity,
    onClick: () -> Unit,
    onRemove: () -> Unit,
) {
    val total = progress.totalPages.coerceAtLeast(1)
    val fraction = (progress.page.toFloat() / total).coerceIn(0f, 1f)
    Surface(
        onClick = onClick,
        shape = MaterialTheme.shapes.large,
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            PosterImage(
                title = progress.mangaTitle,
                posterUrl = progress.posterUrl,
                modifier = Modifier
                    .width(64.dp)
                    .height(96.dp),
            )
            Spacer(Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = progress.mangaTitle.ifBlank { stringResource(R.string.untitled) },
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    text = stringResource(
                        R.string.library_history_progress,
                        progress.chapterLabel.ifBlank { "—" },
                        progress.page,
                        progress.totalPages,
                    ),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Spacer(Modifier.height(8.dp))
                LinearProgressIndicator(
                    progress = fraction,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            IconButton(onClick = onRemove) {
                Icon(
                    imageVector = Icons.Default.Delete,
                    contentDescription = stringResource(R.string.library_remove_history),
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun DownloadsTab(
    downloads: List<DownloadEntity>,
    onOpen: (DownloadEntity) -> Unit,
    onDelete: (DownloadEntity) -> Unit,
    onRetry: (DownloadEntity) -> Unit,
    onBrowseCatalog: () -> Unit,
) {
    if (downloads.isEmpty()) {
        EmptyState(
            title = stringResource(R.string.library_downloads_empty),
            text = stringResource(R.string.library_downloads_empty_text),
            icon = Icons.Default.Download,
            actionLabel = stringResource(R.string.library_go_catalog),
            onAction = onBrowseCatalog,
            modifier = Modifier.fillMaxSize(),
        )
        return
    }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        items(downloads, key = { it.chapterId }) { download ->
            DownloadCard(
                download = download,
                onOpen = { onOpen(download) },
                onDelete = { onDelete(download) },
                onRetry = { onRetry(download) },
            )
        }
    }
}

@Composable
private fun DownloadCard(
    download: DownloadEntity,
    onOpen: () -> Unit,
    onDelete: () -> Unit,
    onRetry: () -> Unit,
) {
    val status = DownloadStatus.fromKey(download.status)
    val total = download.totalPages.coerceAtLeast(1)
    val fraction = (download.downloadedPages.toFloat() / total).coerceIn(0f, 1f)

    Surface(
        onClick = { if (status == DownloadStatus.DONE) onOpen() },
        shape = MaterialTheme.shapes.large,
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            PosterImage(
                title = download.mangaTitle,
                posterUrl = download.coverUrl,
                modifier = Modifier
                    .width(58.dp)
                    .height(87.dp),
            )
            Spacer(Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = download.mangaTitle.ifBlank { stringResource(R.string.untitled) },
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                Spacer(Modifier.height(3.dp))
                Text(
                    text = stringResource(
                        R.string.library_download_chapter,
                        download.chapterLabel.ifBlank { "—" },
                    ),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(5.dp))
                Text(
                    text = when (status) {
                        DownloadStatus.QUEUED -> stringResource(R.string.library_download_status_queued)
                        DownloadStatus.RUNNING -> if (download.totalPages > 0) {
                            stringResource(
                                R.string.library_download_status_running,
                                download.downloadedPages,
                                download.totalPages,
                            )
                        } else {
                            stringResource(R.string.state_loading)
                        }
                        DownloadStatus.DONE -> stringResource(R.string.library_download_status_done)
                        DownloadStatus.FAILED -> stringResource(R.string.library_download_status_failed)
                    },
                    style = MaterialTheme.typography.labelSmall,
                    color = when (status) {
                        DownloadStatus.FAILED -> MangaTheme.colors.dangerText
                        DownloadStatus.DONE -> MangaTheme.colors.successText
                        else -> MaterialTheme.colorScheme.onSurfaceVariant
                    },
                )
                if (status == DownloadStatus.RUNNING || status == DownloadStatus.QUEUED) {
                    Spacer(Modifier.height(6.dp))
                    LinearProgressIndicator(
                        progress = if (status == DownloadStatus.QUEUED) 0f else fraction,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
            if (status == DownloadStatus.FAILED) {
                IconButton(onClick = onRetry) {
                    Icon(
                        imageVector = Icons.Default.Replay,
                        contentDescription = stringResource(R.string.library_download_retry),
                        tint = MangaTheme.colors.accentText,
                    )
                }
            }
            IconButton(onClick = onDelete) {
                Icon(
                    imageVector = Icons.Default.Delete,
                    contentDescription = stringResource(
                        if (status == DownloadStatus.QUEUED || status == DownloadStatus.RUNNING) {
                            R.string.cd_cancel_download
                        } else {
                            R.string.cd_delete_download
                        },
                    ),
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}
