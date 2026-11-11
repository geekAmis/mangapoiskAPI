package ru.mangapoisk.reborn.ui.home

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Bookmark
import androidx.compose.material.icons.filled.BookmarkBorder
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.AsyncImage
import ru.mangapoisk.reborn.R
import ru.mangapoisk.reborn.data.local.entity.ProgressEntity
import ru.mangapoisk.reborn.data.model.Manga
import ru.mangapoisk.reborn.data.model.Source
import ru.mangapoisk.reborn.data.model.preferredTitle
import ru.mangapoisk.reborn.data.model.secondaryTitle
import ru.mangapoisk.reborn.ui.LocalAppContainer
import ru.mangapoisk.reborn.ui.LocalThemeId
import ru.mangapoisk.reborn.ui.components.ErrorState
import ru.mangapoisk.reborn.ui.components.MangaCard
import ru.mangapoisk.reborn.ui.components.PosterImage
import ru.mangapoisk.reborn.ui.components.SectionHeader
import ru.mangapoisk.reborn.ui.components.SkeletonPoster
import ru.mangapoisk.reborn.ui.theme.MangaTheme
import ru.mangapoisk.reborn.ui.util.formatDate
import ru.mangapoisk.reborn.ui.util.formatScore
import ru.mangapoisk.reborn.ui.util.statusLabel
import ru.mangapoisk.reborn.ui.util.stripHtml

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    onMangaClick: (String) -> Unit,
    onContinueReading: (ProgressEntity) -> Unit,
    onOpenReader: (chapterId: String, startPage: Int, mangaId: String, title: String, cover: String?) -> Unit,
    onSourceClick: (String) -> Unit,
    onAllSources: () -> Unit,
    onCatalogSort: (String) -> Unit,
) {
    val container = LocalAppContainer.current
    val viewModel: HomeViewModel = viewModel(
        factory = remember(container) { HomeViewModel.factory(container) },
    )
    val state by viewModel.state.collectAsStateWithLifecycle()
    val theme = LocalThemeId.current

    LaunchedEffect(viewModel) {
        viewModel.events.collect { event ->
            when (event) {
                is HomeEvent.OpenReader -> onOpenReader(
                    event.chapterId,
                    event.startPage,
                    event.mangaId,
                    event.title,
                    event.cover,
                )
                is HomeEvent.OpenDetail -> onMangaClick(event.mangaId)
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(
                            text = stringResource(R.string.home_title),
                            style = MaterialTheme.typography.titleLarge,
                            fontWeight = FontWeight.Bold,
                        )
                        Text(
                            text = stringResource(R.string.home_reborn),
                            style = MaterialTheme.typography.labelSmall,
                            color = MangaTheme.colors.accentText,
                        )
                    }
                },
                actions = {
                    IconButton(
                        onClick = viewModel::refresh,
                        enabled = !state.isRefreshing && !state.isLoading,
                    ) {
                        if (state.isRefreshing) {
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
    ) { padding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
            contentAlignment = Alignment.TopCenter,
        ) {
            if (state.error != null && !state.hasContent) {
                ErrorState(
                    error = state.error,
                    onRetry = viewModel::load,
                )
                return@Box
            }

            LazyColumn(
                modifier = Modifier
                    .widthIn(max = 1200.dp)
                    .fillMaxWidth(),
                contentPadding = PaddingValues(bottom = 28.dp),
            ) {
                item(key = "hero") {
                    HomeHero(
                        featured = state.featured,
                        backgroundRes = theme.backgroundRes,
                        isLoading = state.isLoading,
                        isBookmarked = state.isFeaturedBookmarked,
                        onOpen = { viewModel.openFeatured() },
                        onToggleBookmark = viewModel::toggleFeaturedBookmark,
                    )
                }

                if (state.error != null && state.hasContent) {
                    item(key = "error-banner") {
                        Surface(
                            color = MaterialTheme.colorScheme.errorContainer,
                            contentColor = MaterialTheme.colorScheme.onErrorContainer,
                            shape = MaterialTheme.shapes.medium,
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 16.dp, vertical = 8.dp),
                        ) {
                            Row(
                                modifier = Modifier.padding(12.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    text = stringResource(R.string.error_network),
                                    style = MaterialTheme.typography.bodySmall,
                                    modifier = Modifier.weight(1f),
                                )
                                TextButton(onClick = viewModel::load) {
                                    Text(stringResource(R.string.action_retry))
                                }
                            }
                        }
                    }
                }

                if (state.continueReading.isNotEmpty()) {
                    item(key = "continue") {
                        SectionHeader(title = stringResource(R.string.home_continue))
                        LazyRow(
                            contentPadding = PaddingValues(horizontal = 16.dp),
                            horizontalArrangement = Arrangement.spacedBy(12.dp),
                        ) {
                            items(state.continueReading, key = { it.mangaId }) { progress ->
                                ContinueReadingCard(
                                    progress = progress,
                                    onClick = { onContinueReading(progress) },
                                )
                            }
                        }
                    }
                }

                if (state.isLoading && state.popular.isEmpty()) {
                    item(key = "popular-skeleton") {
                        SectionHeader(title = stringResource(R.string.home_popular))
                        Row(
                            modifier = Modifier.padding(horizontal = 16.dp),
                            horizontalArrangement = Arrangement.spacedBy(12.dp),
                        ) {
                            repeat(2) {
                                SkeletonPoster(Modifier.weight(1f))
                            }
                        }
                    }
                } else {
                    item(key = "popular") {
                        HomePopularSection(
                            mangas = state.popular.take(6),
                            onMangaClick = { onMangaClick(it.id) },
                            onSeeAll = { onCatalogSort("popular") },
                        )
                    }
                }

                item(key = "latest") {
                    HomeUpdatesSection(
                        mangas = state.latest.take(6),
                        onMangaClick = { onMangaClick(it.id) },
                        onSeeAll = { onCatalogSort("updated") },
                    )
                }

                if (state.sources.isNotEmpty()) {
                    item(key = "sources") {
                        SourceChips(
                            sources = state.sources,
                            onSourceClick = onSourceClick,
                            onAllSources = onAllSources,
                        )
                    }
                }

                if (!state.isLoading && !state.hasContent) {
                    item(key = "empty") {
                        Text(
                            text = stringResource(R.string.home_empty),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(24.dp),
                        )
                    }
                }

                item(key = "legal") {
                    Text(
                        text = stringResource(R.string.home_legal),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 20.dp, vertical = 24.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun HomeHero(
    featured: Manga?,
    backgroundRes: Int,
    isLoading: Boolean,
    isBookmarked: Boolean,
    onOpen: (Manga) -> Unit,
    onToggleBookmark: () -> Unit,
) {
    BoxWithConstraints(modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
        val wide = maxWidth >= 600.dp
        val shape = RoundedCornerShape(22.dp)
        Surface(
            shape = shape,
            color = MaterialTheme.colorScheme.surface,
            border = BorderStroke(1.dp, MangaTheme.colors.border),
            modifier = Modifier
                .fillMaxWidth()
                .clip(shape),
        ) {
            if (wide) {
                Row(modifier = Modifier.height(480.dp)) {
                    HeroCopy(
                        featured = featured,
                        isLoading = isLoading,
                        isBookmarked = isBookmarked,
                        onOpen = onOpen,
                        onToggleBookmark = onToggleBookmark,
                        wide = true,
                        modifier = Modifier
                            .weight(1f)
                            .fillMaxHeight()
                            .padding(28.dp),
                    )
                    HeroArt(
                        backgroundRes = backgroundRes,
                        wide = true,
                        modifier = Modifier
                            .weight(0.78f)
                            .fillMaxHeight(),
                    )
                }
            } else {
                Column {
                    HeroArt(
                        backgroundRes = backgroundRes,
                        wide = false,
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(240.dp),
                    )
                    HeroCopy(
                        featured = featured,
                        isLoading = isLoading,
                        isBookmarked = isBookmarked,
                        onOpen = onOpen,
                        onToggleBookmark = onToggleBookmark,
                        wide = false,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(20.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun HeroArt(
    backgroundRes: Int,
    wide: Boolean,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .background(MangaTheme.colors.surface2)
            .clip(RoundedCornerShape(if (wide) 0.dp else 0.dp)),
    ) {
        AsyncImage(
            model = backgroundRes,
            contentDescription = null,
            contentScale = ContentScale.Crop,
            modifier = Modifier.fillMaxSize(),
        )
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(
                    if (wide) {
                        Brush.horizontalGradient(
                            0f to MaterialTheme.colorScheme.surface.copy(alpha = 0.98f),
                            0.20f to Color.Transparent,
                        )
                    } else {
                        Brush.verticalGradient(
                            0f to Color.Transparent,
                            0.78f to Color.Transparent,
                            1f to MaterialTheme.colorScheme.surface,
                        )
                    },
                ),
        )
        if (!wide) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(Color.Black.copy(alpha = 0.06f)),
            )
        }
    }
}

@Composable
private fun HeroCopy(
    featured: Manga?,
    isLoading: Boolean,
    isBookmarked: Boolean,
    onOpen: (Manga) -> Unit,
    onToggleBookmark: () -> Unit,
    wide: Boolean,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier) {
        if (featured == null) {
            Text(
                text = stringResource(R.string.home_greeting),
                style = if (wide) {
                    MaterialTheme.typography.headlineLarge
                } else {
                    MaterialTheme.typography.headlineMedium
                },
                fontWeight = FontWeight.Bold,
            )
            Spacer(Modifier.height(8.dp))
            Text(
                text = stringResource(R.string.home_subtitle),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (isLoading) {
                Spacer(Modifier.height(18.dp))
                CircularProgressIndicator(
                    modifier = Modifier.size(22.dp),
                    strokeWidth = 2.dp,
                )
            }
            return
        }

        val status = statusLabel(featured.status)
        val displayTitle = featured.preferredTitle()
        val altTitle = featured.secondaryTitle()
        val description = stripHtml(featured.description)
        val rating = formatScore(featured.rating)

        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                modifier = Modifier
                    .width(28.dp)
                    .height(2.dp)
                    .background(MangaTheme.colors.accent),
            )
            Spacer(Modifier.width(8.dp))
            Text(
                text = stringResource(R.string.home_hero_tag).uppercase(),
                style = MaterialTheme.typography.labelSmall,
                color = MangaTheme.colors.accentText,
                fontWeight = FontWeight.Bold,
            )
        }
        Spacer(Modifier.height(10.dp))
        Text(
            text = displayTitle.ifBlank { stringResource(R.string.untitled) },
            style = if (wide) {
                MaterialTheme.typography.displayMedium
            } else {
                MaterialTheme.typography.displaySmall
            },
            maxLines = 3,
            overflow = TextOverflow.Ellipsis,
        )
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
        Spacer(Modifier.height(8.dp))
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (rating != null) {
                Text(
                    text = stringResource(
                        R.string.rating_format,
                        rating.toDoubleOrNull() ?: 0.0,
                    ),
                    style = MaterialTheme.typography.labelLarge,
                    color = MangaTheme.colors.accent2,
                    fontWeight = FontWeight.Bold,
                )
                MetaDot()
            }
            featured.year?.let {
                Text(
                    text = it.toString(),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                MetaDot()
            }
            Text(
                text = status,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (featured.chaptersCount > 0) {
                MetaDot()
                Text(
                    text = stringResource(
                        R.string.chapters_count_short,
                        featured.chaptersCount,
                    ),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        if (description != null) {
            Spacer(Modifier.height(10.dp))
            Text(
                text = description,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = if (wide) 4 else 3,
                overflow = TextOverflow.Ellipsis,
            )
        }
        if (featured.genres.isNotEmpty()) {
            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                featured.genres.take(3).forEach { genre ->
                    Surface(
                        shape = RoundedCornerShape(999.dp),
                        color = MangaTheme.colors.surface2,
                        border = BorderStroke(1.dp, MangaTheme.colors.border),
                    ) {
                        Text(
                            text = genre,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                        )
                    }
                }
            }
        }
        Spacer(Modifier.height(16.dp))
        if (wide) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                HeroReadButton(
                    onClick = { onOpen(featured) },
                    modifier = Modifier.weight(1f),
                )
                HeroBookmarkButton(
                    isBookmarked = isBookmarked,
                    onClick = onToggleBookmark,
                    modifier = Modifier.weight(1f),
                )
            }
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                HeroReadButton(
                    onClick = { onOpen(featured) },
                    modifier = Modifier.fillMaxWidth(),
                )
                HeroBookmarkButton(
                    isBookmarked = isBookmarked,
                    onClick = onToggleBookmark,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
    }
}

@Composable
private fun HeroReadButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Button(
        onClick = onClick,
        modifier = modifier.heightIn(min = 48.dp),
    ) {
        Icon(
            imageVector = Icons.Default.PlayArrow,
            contentDescription = null,
            modifier = Modifier.size(18.dp),
        )
        Spacer(Modifier.width(6.dp))
        Text(stringResource(R.string.action_read), maxLines = 1)
    }
}

@Composable
private fun HeroBookmarkButton(
    isBookmarked: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    OutlinedButton(
        onClick = onClick,
        modifier = modifier.heightIn(min = 48.dp),
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
            text = stringResource(
                if (isBookmarked) {
                    R.string.detail_bookmark_remove
                } else {
                    R.string.detail_bookmark_add
                },
            ),
            maxLines = 1,
        )
    }
}

@Composable
private fun MetaDot() {
    Box(
        modifier = Modifier
            .size(3.dp)
            .background(MangaTheme.colors.borderStrong, CircleShape),
    )
}

@Composable
private fun HomePopularSection(
    mangas: List<Manga>,
    onMangaClick: (Manga) -> Unit,
    onSeeAll: () -> Unit,
) {
    val screenWidth = LocalConfiguration.current.screenWidthDp
    val columns = when {
        screenWidth >= 720 -> 4
        screenWidth >= 480 -> 3
        else -> 2
    }
    SectionHeader(
        title = stringResource(R.string.home_popular),
        onSeeAll = onSeeAll,
    )
    if (mangas.isEmpty()) return
    Column(
        modifier = Modifier.padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        mangas.chunked(columns).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                row.forEach { manga ->
                    MangaCard(
                        manga = manga,
                        onClick = { onMangaClick(manga) },
                        modifier = Modifier.weight(1f),
                    )
                }
                repeat(columns - row.size) {
                    Spacer(Modifier.weight(1f))
                }
            }
        }
    }
}

@Composable
private fun HomeUpdatesSection(
    mangas: List<Manga>,
    onMangaClick: (Manga) -> Unit,
    onSeeAll: () -> Unit,
) {
    SectionHeader(
        title = stringResource(R.string.home_latest),
        onSeeAll = onSeeAll,
    )
    if (mangas.isEmpty()) return
    Column(modifier = Modifier.padding(horizontal = 16.dp)) {
        mangas.forEachIndexed { index, manga ->
            UpdateRow(
                manga = manga,
                onClick = { onMangaClick(manga) },
            )
            if (index != mangas.lastIndex) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(1.dp)
                        .background(MangaTheme.colors.border.copy(alpha = 0.7f)),
                )
            }
        }
    }
}

@Composable
private fun UpdateRow(manga: Manga, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        PosterImage(
            title = manga.title,
            posterUrl = manga.posterUrl,
            modifier = Modifier
                .width(56.dp)
                .aspectRatio(3f / 4f),
        )
        Spacer(Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = manga.preferredTitle().ifBlank { stringResource(R.string.untitled) },
                style = MaterialTheme.typography.titleSmall,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(3.dp))
            Text(
                text = listOfNotNull(
                    manga.year?.toString(),
                    statusLabel(manga.status),
                ).joinToString(" · "),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            formatDate(manga.lastChapterAt)?.let { date ->
                Spacer(Modifier.height(2.dp))
                Text(
                    text = stringResource(R.string.home_updated_at, date),
                    style = MaterialTheme.typography.labelSmall,
                    color = MangaTheme.colors.accentText,
                )
            }
        }
        Icon(
            imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun ContinueReadingCard(
    progress: ProgressEntity,
    onClick: () -> Unit,
) {
    val total = progress.totalPages.coerceAtLeast(1)
    val fraction = (progress.page.toFloat() / total).coerceIn(0f, 1f)
    Surface(
        onClick = onClick,
        shape = MaterialTheme.shapes.large,
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.55f),
        modifier = Modifier.width(296.dp),
    ) {
        Row(
            modifier = Modifier.padding(10.dp),
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
                        R.string.home_continue_page,
                        progress.chapterLabel.ifBlank { "—" },
                        progress.page,
                    ),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                )
                Spacer(Modifier.height(8.dp))
                LinearProgressIndicator(
                    progress = fraction,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
    }
}

@Composable
private fun SourceChips(
    sources: List<Source>,
    onSourceClick: (String) -> Unit,
    onAllSources: () -> Unit,
) {
    SectionHeader(
        title = stringResource(R.string.home_sources),
        onSeeAll = onAllSources,
    )
    LazyRow(
        contentPadding = PaddingValues(horizontal = 16.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(sources, key = { it.code }) { source ->
            AssistChip(
                onClick = { onSourceClick(source.code) },
                label = { Text(source.name) },
            )
        }
    }
}
