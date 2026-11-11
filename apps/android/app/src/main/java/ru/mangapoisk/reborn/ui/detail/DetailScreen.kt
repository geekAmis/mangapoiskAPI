package ru.mangapoisk.reborn.ui.detail

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Bookmark
import androidx.compose.material.icons.filled.BookmarkBorder
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import ru.mangapoisk.reborn.R
import ru.mangapoisk.reborn.data.local.entity.DownloadEntity
import ru.mangapoisk.reborn.data.local.entity.ProgressEntity
import ru.mangapoisk.reborn.data.model.Chapter
import ru.mangapoisk.reborn.data.model.DownloadStatus
import ru.mangapoisk.reborn.data.model.MangaDetail
import ru.mangapoisk.reborn.data.model.preferredTitle
import ru.mangapoisk.reborn.data.model.secondaryTitle
import ru.mangapoisk.reborn.ui.LocalAppContainer
import ru.mangapoisk.reborn.ui.components.AdultBadge
import ru.mangapoisk.reborn.ui.components.EmptyState
import ru.mangapoisk.reborn.ui.components.ErrorState
import ru.mangapoisk.reborn.ui.components.LoadingBox
import ru.mangapoisk.reborn.ui.components.PosterImage
import ru.mangapoisk.reborn.ui.theme.MangaTheme
import ru.mangapoisk.reborn.ui.util.chapterLabel
import ru.mangapoisk.reborn.ui.util.contentTypeLabel
import ru.mangapoisk.reborn.ui.util.formatDate
import ru.mangapoisk.reborn.ui.util.formatScore
import ru.mangapoisk.reborn.ui.util.statusLabel
import ru.mangapoisk.reborn.ui.util.stripHtml

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun DetailScreen(
    onBack: () -> Unit,
    onReadChapter: (
        chapterId: String,
        startPage: Int,
        mangaTitle: String,
        coverUrl: String?,
    ) -> Unit,
) {
    val container = LocalAppContainer.current
    val viewModel: DetailViewModel = viewModel(
        factory = remember(container) { DetailViewModel.factory(container) },
    )
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }
    val downloadQueued = stringResource(R.string.detail_download_started)
    val downloadFailed = stringResource(R.string.detail_download_failed)
    val bookmarkFailed = stringResource(R.string.detail_bookmark_error)

    LaunchedEffect(viewModel) {
        viewModel.events.collect { event ->
            val message = when (event) {
                DetailEvent.DownloadQueued -> downloadQueued
                DetailEvent.DownloadFailed -> downloadFailed
                DetailEvent.BookmarkFailed -> bookmarkFailed
            }
            snackbarHostState.showSnackbar(message)
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = state.manga?.manga?.preferredTitle()
                            ?.takeIf { it.isNotBlank() }
                            ?: stringResource(R.string.detail_title),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = stringResource(R.string.cd_back),
                        )
                    }
                },
                actions = {
                    if (state.manga != null) {
                        IconButton(onClick = viewModel::toggleBookmark) {
                            Icon(
                                imageVector = if (state.isBookmarked) {
                                    Icons.Default.Bookmark
                                } else {
                                    Icons.Default.BookmarkBorder
                                },
                                contentDescription = stringResource(
                                    if (state.isBookmarked) {
                                        R.string.cd_remove_bookmark
                                    } else {
                                        R.string.cd_add_bookmark
                                    },
                                ),
                                tint = if (state.isBookmarked) {
                                    MangaTheme.colors.accentText
                                } else {
                                    MaterialTheme.colorScheme.onSurfaceVariant
                                },
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
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .navigationBarsPadding(),
        ) {
            when {
                state.isLoading && state.manga == null -> LoadingBox()
                state.error != null && state.manga == null -> ErrorState(
                    error = state.error,
                    onRetry = viewModel::load,
                )
                state.manga == null -> EmptyState(
                    title = stringResource(R.string.detail_title),
                    text = stringResource(R.string.error_not_found),
                )
                else -> DetailContent(
                    detail = state.manga!!,
                    progress = state.progress,
                    isBookmarked = state.isBookmarked,
                    downloads = state.downloads,
                    onReadChapter = onReadChapter,
                    onToggleBookmark = viewModel::toggleBookmark,
                    onDownloadChapter = viewModel::downloadChapter,
                )
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun DetailContent(
    detail: MangaDetail,
    progress: ProgressEntity?,
    isBookmarked: Boolean,
    downloads: Map<String, DownloadEntity>,
    onReadChapter: (String, Int, String, String?) -> Unit,
    onToggleBookmark: () -> Unit,
    onDownloadChapter: (Chapter) -> Unit,
) {
    val manga = detail.manga
    val openChapter: (String, Int) -> Unit = { chapterId, startPage ->
        onReadChapter(chapterId, startPage, manga.preferredTitle(), manga.posterUrl)
    }
    val chapters = detail.chapters
    var descriptionExpanded by remember(manga.id) { mutableStateOf(false) }
    val description = stripHtml(manga.description)
    val statusText = statusLabel(manga.status)
    val contentType = contentTypeLabel(manga.contentType)
    val primaryChapterId = progress?.chapterId ?: chapters.lastOrNull()?.id
    val primaryStartPage = progress?.page?.coerceAtLeast(1) ?: 1
    val listState = rememberLazyListState()

    LaunchedEffect(manga.id) {
        listState.scrollToItem(0)
    }

    LazyColumn(
        state = listState,
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(bottom = 32.dp),
    ) {
        item(key = "header") {
            Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                Row {
                    Box {
                        PosterImage(
                            title = manga.title,
                            posterUrl = manga.posterUrl,
                            modifier = Modifier
                                .width(128.dp)
                                .height(192.dp),
                        )
                        if (manga.adult) {
                            AdultBadge(
                                modifier = Modifier
                                    .align(Alignment.TopStart)
                                    .padding(8.dp),
                            )
                        }
                    }
                    Spacer(Modifier.width(16.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = manga.preferredTitle()
                                .ifBlank { stringResource(R.string.untitled) },
                            style = MaterialTheme.typography.headlineSmall,
                            fontWeight = FontWeight.Bold,
                            maxLines = 3,
                            overflow = TextOverflow.Ellipsis,
                        )
                        val altTitle = manga.secondaryTitle()
                        if (!altTitle.isNullOrBlank()) {
                            Spacer(Modifier.height(4.dp))
                            Text(
                                text = altTitle,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 2,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                        Spacer(Modifier.height(10.dp))
                        val rating = formatScore(manga.rating)
                        if (rating != null) {
                            Text(
                                text = stringResource(
                                    R.string.rating_format,
                                    rating.toDoubleOrNull() ?: 0.0,
                                ),
                                style = MaterialTheme.typography.titleMedium,
                                color = MaterialTheme.colorScheme.tertiary,
                                fontWeight = FontWeight.Bold,
                            )
                            Spacer(Modifier.height(4.dp))
                        }
                        val meta = listOfNotNull(
                            manga.year?.toString(),
                            statusText,
                            contentType,
                        ).joinToString(" · ")
                        Text(
                            text = meta,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.height(4.dp))
                        Text(
                            text = pluralStringResource(
                                R.plurals.chapters_count,
                                chapters.size,
                                chapters.size,
                            ),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        if (manga.source.isNotBlank()) {
                            Spacer(Modifier.height(4.dp))
                            Text(
                                text = stringResource(R.string.detail_source, manga.source),
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.75f),
                            )
                        }
                    }
                }

                if (manga.genres.isNotEmpty()) {
                    Spacer(Modifier.height(14.dp))
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        manga.genres.forEach { genre ->
                            GenreTag(genre)
                        }
                    }
                }

                Spacer(Modifier.height(18.dp))
                Button(
                    onClick = {
                        primaryChapterId?.let { openChapter(it, primaryStartPage) }
                    },
                    enabled = primaryChapterId != null,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        stringResource(
                            if (progress != null) R.string.detail_continue else R.string.detail_read,
                        ),
                    )
                }
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(
                        onClick = onToggleBookmark,
                        modifier = Modifier.weight(1f),
                    ) {
                        Icon(
                            imageVector = if (isBookmarked) {
                                Icons.Default.Bookmark
                            } else {
                                Icons.Default.BookmarkBorder
                            },
                            contentDescription = null,
                            modifier = Modifier.size(18.dp),
                        )
                        Spacer(Modifier.width(6.dp))
                        Text(
                            stringResource(
                                if (isBookmarked) {
                                    R.string.detail_bookmark_remove
                                } else {
                                    R.string.detail_bookmark_add
                                },
                            ),
                            maxLines = 1,
                        )
                    }
                    if (progress != null) {
                        OutlinedButton(
                            onClick = { chapters.lastOrNull()?.let { openChapter(it.id, 1) } },
                            enabled = chapters.isNotEmpty(),
                        ) {
                            Text(stringResource(R.string.detail_read_from_start))
                        }
                    }
                }
                if (progress != null) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        text = stringResource(
                            R.string.detail_continue_at,
                            progress.chapterLabel.ifBlank { "—" },
                            progress.page,
                        ),
                        style = MaterialTheme.typography.labelMedium,
                        color = MangaTheme.colors.accentText,
                    )
                }
            }
        }

        item(key = "description") {
            Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
                Text(
                    text = stringResource(R.string.detail_description),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.height(6.dp))
                val text = description ?: stringResource(R.string.detail_no_description)
                Text(
                    text = text,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = if (descriptionExpanded) Int.MAX_VALUE else 5,
                    overflow = TextOverflow.Ellipsis,
                )
                if (description != null && description.length > 220) {
                    TextButton(
                        onClick = { descriptionExpanded = !descriptionExpanded },
                        contentPadding = androidx.compose.foundation.layout.PaddingValues(0.dp),
                    ) {
                        Text(
                            stringResource(
                                if (descriptionExpanded) {
                                    R.string.detail_collapse
                                } else {
                                    R.string.detail_expand
                                },
                            ),
                        )
                    }
                }
            }
        }

        item(key = "export") {
            Surface(
                shape = RoundedCornerShape(14.dp),
                color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 8.dp),
            ) {
                Row(modifier = Modifier.padding(14.dp)) {
                    Icon(
                        imageVector = Icons.Default.Info,
                        contentDescription = null,
                        tint = MangaTheme.colors.accentText,
                        modifier = Modifier.size(22.dp),
                    )
                    Spacer(Modifier.width(10.dp))
                    Column {
                        Text(
                            text = stringResource(R.string.detail_export_title),
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.SemiBold,
                        )
                        Spacer(Modifier.height(4.dp))
                        Text(
                            text = stringResource(R.string.detail_export_text),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }

        item(key = "chapters-header") {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = stringResource(R.string.detail_chapters),
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    text = chapters.size.toString(),
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        if (chapters.isEmpty()) {
            item(key = "chapters-empty") {
                Text(
                    text = stringResource(R.string.detail_no_chapters),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(16.dp),
                )
            }
        } else {
            items(chapters, key = { it.id }) { chapter ->
                val download = downloads[chapter.id]
                val startPage = if (progress?.chapterId == chapter.id) {
                    progress.page.coerceAtLeast(1)
                } else {
                    1
                }
                ChapterRow(
                    chapter = chapter,
                    download = download,
                    progress = progress?.takeIf { it.chapterId == chapter.id },
                    onClick = { openChapter(chapter.id, startPage) },
                    onDownload = { onDownloadChapter(chapter) },
                )
            }
        }
    }
}

@Composable
private fun GenreTag(genre: String) {
    Surface(
        shape = RoundedCornerShape(999.dp),
        color = MaterialTheme.colorScheme.surfaceVariant,
        contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
    ) {
        Text(
            text = genre,
            style = MaterialTheme.typography.labelMedium,
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
        )
    }
}

@Composable
private fun ChapterRow(
    chapter: Chapter,
    download: DownloadEntity?,
    progress: ProgressEntity?,
    onClick: () -> Unit,
    onDownload: () -> Unit,
) {
    val downloadStatus = download?.let { DownloadStatus.fromKey(it.status) }
    val isDownloading = downloadStatus == DownloadStatus.QUEUED ||
        downloadStatus == DownloadStatus.RUNNING
    val fraction = if (progress != null && progress.totalPages > 0) {
        (progress.page.toFloat() / progress.totalPages).coerceIn(0f, 1f)
    } else {
        0f
    }

    Surface(
        onClick = onClick,
        color = if (progress != null) {
            MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.22f)
        } else {
            MaterialTheme.colorScheme.surface
        },
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = chapterLabel(chapter.volume, chapter.number, chapter.title),
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Medium,
                )
                Spacer(Modifier.height(3.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (chapter.pageCount > 0) {
                        Text(
                            text = pluralStringResource(
                                R.plurals.pages_count,
                                chapter.pageCount,
                                chapter.pageCount,
                            ),
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    formatDate(chapter.publishedAt)?.let { date ->
                        Text(
                            text = if (chapter.pageCount > 0) " · $date" else date,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
                        )
                    }
                }
                if (progress != null) {
                    Spacer(Modifier.height(6.dp))
                    LinearProgressIndicator(
                        progress = fraction,
                        modifier = Modifier
                            .fillMaxWidth(0.7f)
                            .height(3.dp),
                    )
                }
                when (downloadStatus) {
                    DownloadStatus.QUEUED -> DownloadStatusText(
                        stringResource(R.string.detail_chapter_queued),
                    )
                    DownloadStatus.RUNNING -> DownloadStatusText(
                        stringResource(
                            R.string.detail_chapter_downloading,
                            download?.downloadedPages ?: 0,
                            download?.totalPages ?: 0,
                        ),
                    )
                    DownloadStatus.FAILED -> DownloadStatusText(
                        stringResource(R.string.detail_chapter_failed),
                        isError = true,
                    )
                    DownloadStatus.DONE -> DownloadStatusText(
                        stringResource(R.string.detail_chapter_downloaded),
                    )
                    null -> Unit
                }
            }

            IconButton(
                onClick = onDownload,
                enabled = !isDownloading && downloadStatus != DownloadStatus.DONE,
            ) {
                when (downloadStatus) {
                    DownloadStatus.QUEUED, DownloadStatus.RUNNING -> CircularProgressIndicator(
                        modifier = Modifier.size(18.dp),
                        strokeWidth = 2.dp,
                    )
                    DownloadStatus.DONE -> Icon(
                        imageVector = Icons.Default.Check,
                        contentDescription = stringResource(R.string.detail_chapter_downloaded),
                        tint = MangaTheme.colors.successText,
                    )
                    DownloadStatus.FAILED -> Icon(
                        imageVector = Icons.Default.ErrorOutline,
                        contentDescription = stringResource(R.string.detail_chapter_failed),
                        tint = MangaTheme.colors.dangerText,
                    )
                    null -> Icon(
                        imageVector = Icons.Default.Download,
                        contentDescription = stringResource(
                            R.string.cd_download_chapter,
                            chapter.shortLabel,
                        ),
                    )
                }
            }
        }
    }
}

@Composable
private fun DownloadStatusText(text: String, isError: Boolean = false) {
    Text(
        text = text,
        style = MaterialTheme.typography.labelSmall,
        color = if (isError) {
            MangaTheme.colors.dangerText
        } else {
            MangaTheme.colors.successText
        },
    )
}
