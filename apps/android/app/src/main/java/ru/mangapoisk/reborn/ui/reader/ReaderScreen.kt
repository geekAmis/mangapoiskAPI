package ru.mangapoisk.reborn.ui.reader

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.view.WindowManager
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.filled.Bookmark
import androidx.compose.material.icons.filled.BookmarkBorder
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.SwapHoriz
import androidx.compose.material.icons.filled.SwapVert
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Divider
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.AsyncImage
import coil.imageLoader
import coil.request.ImageRequest
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import ru.mangapoisk.reborn.R
import ru.mangapoisk.reborn.data.model.PageFit
import ru.mangapoisk.reborn.data.model.ReaderMode
import ru.mangapoisk.reborn.data.remote.MediaUrlResolver
import ru.mangapoisk.reborn.ui.LocalAppContainer
import ru.mangapoisk.reborn.ui.LocalBaseUrl
import ru.mangapoisk.reborn.ui.LocalThemeId
import ru.mangapoisk.reborn.ui.theme.MangaTheme
import ru.mangapoisk.reborn.ui.theme.ThemeMode
import ru.mangapoisk.reborn.ui.util.chapterLabel
import ru.mangapoisk.reborn.ui.util.userMessage
import java.io.File
import kotlin.math.roundToInt

private val ReaderBlack = Color(0xFF050506)

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun ReaderScreen(onBack: () -> Unit) {
    val container = LocalAppContainer.current
    val viewModel: ReaderViewModel = viewModel(
        factory = remember(container) { ReaderViewModel.factory(container) },
    )
    val state by viewModel.state.collectAsStateWithLifecycle()
    val settings by container.settingsStore.settings.collectAsStateWithLifecycle(
        initialValue = container.settingsStore.initial,
    )
    val scope = rememberCoroutineScope()
    val baseUrl = LocalBaseUrl.current

    var modeOverride by rememberSaveable { mutableStateOf<String?>(null) }
    var fitOverride by rememberSaveable { mutableStateOf<String?>(null) }
    var keepScreenOverride by rememberSaveable { mutableStateOf<Boolean?>(null) }
    var speedOverride by rememberSaveable { mutableStateOf<Int?>(null) }
    var gapOverride by rememberSaveable { mutableStateOf<Int?>(null) }
    var autoScroll by rememberSaveable { mutableStateOf(false) }
    var chromeVisible by rememberSaveable { mutableStateOf(true) }
    var showSettings by rememberSaveable { mutableStateOf(false) }

    val mode = ReaderMode.fromKey(modeOverride ?: settings.readerMode)
    val fit = PageFit.fromKey(fitOverride ?: settings.pageFit)
    val keepScreenOn = keepScreenOverride ?: settings.keepScreenOn
    val speed = speedOverride ?: settings.autoScrollSpeed
    val gap = gapOverride ?: settings.readerGap
    val currentTheme = LocalThemeId.current

    val listState = rememberLazyListState()
    val pagerState = rememberPagerState(pageCount = { state.pages.size })

    LaunchedEffect(state.chapterId, state.pages.size, mode, state.pendingResumePage) {
        if (state.pages.isEmpty()) return@LaunchedEffect
        val targetPage = if (state.pendingResumePage != null) 1 else state.currentPage
        val index = (targetPage - 1).coerceIn(0, state.pages.lastIndex)
        if (mode == ReaderMode.VERTICAL) {
            listState.scrollToItem(index)
        } else {
            pagerState.scrollToPage(index)
        }
    }

    LaunchedEffect(listState, mode) {
        if (mode != ReaderMode.VERTICAL) return@LaunchedEffect
        snapshotFlow { listState.firstVisibleItemIndex }
            .distinctUntilChanged()
            .collect { index -> viewModel.onPageChanged(index + 1) }
    }

    LaunchedEffect(pagerState, mode) {
        if (mode != ReaderMode.HORIZONTAL) return@LaunchedEffect
        snapshotFlow { pagerState.currentPage }
            .distinctUntilChanged()
            .collect { index -> viewModel.onPageChanged(index + 1) }
    }

    val density = LocalDensity.current
    LaunchedEffect(autoScroll, mode, speed, state.chapterId, showSettings) {
        if (!autoScroll || showSettings || mode != ReaderMode.VERTICAL ||
            state.pages.isEmpty()
        ) {
            return@LaunchedEffect
        }
        val stepPx = with(density) { (speed / 10f).dp.toPx() }
        while (isActive) {
            delay(50)
            val info = listState.layoutInfo
            val last = info.visibleItemsInfo.lastOrNull()
            val atEnd = last != null &&
                last.index == info.totalItemsCount - 1 &&
                last.offset + last.size <= info.viewportEndOffset
            if (atEnd) {
                autoScroll = false
                break
            }
            listState.scrollBy(stepPx)
        }
    }

    DisposableEffect(viewModel) {
        onDispose { viewModel.flushProgress() }
    }
    LifecycleEventEffect(Lifecycle.Event.ON_STOP) {
        viewModel.flushProgress()
    }

    val localContext = LocalContext.current
    val activity = remember(localContext) { localContext.findActivity() }
    DisposableEffect(activity, keepScreenOn) {
        val window = activity?.window
        if (window != null) {
            if (keepScreenOn) {
                window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            } else {
                window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            }
        }
        onDispose {
            window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
    }
    DisposableEffect(activity) {
        val window = activity?.window
        val controller = window?.let {
            WindowCompat.getInsetsController(it, it.decorView)
        }
        controller?.apply {
            systemBarsBehavior =
                WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            hide(WindowInsetsCompat.Type.systemBars())
        }
        onDispose {
            controller?.show(WindowInsetsCompat.Type.systemBars())
        }
    }

    val context = LocalContext.current
    LaunchedEffect(state.chapterId, state.currentPage, state.pages.size) {
        state.pages.drop(state.currentPage).take(2).forEach { page ->
            val data = page.localFile ?: MediaUrlResolver.resolve(page.url, baseUrl) ?: return@forEach
            context.imageLoader.enqueue(
                ImageRequest.Builder(context)
                    .data(data)
                    .build(),
            )
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(ReaderBlack)
            .pointerInput(mode) {
                if (mode == ReaderMode.VERTICAL) {
                    detectTapGestures { offset ->
                        if (autoScroll) autoScroll = false
                        val fraction = offset.x / size.width.coerceAtLeast(1)
                        if (fraction in 0.3f..0.7f) {
                            chromeVisible = !chromeVisible
                        }
                    }
                }
            },
    ) {
        when {
            state.isLoading -> {
                ReaderLoading()
                ReaderBackButton(onBack = onBack, modifier = Modifier.align(Alignment.TopStart))
            }

            state.error != null -> {
                ReaderError(
                    message = state.error!!.userMessage(),
                    onRetry = viewModel::retry,
                    onBack = onBack,
                )
            }

            state.pages.isEmpty() -> {
                ReaderError(
                    message = stringResource(R.string.reader_no_pages),
                    onRetry = viewModel::retry,
                    onBack = onBack,
                )
            }

            else -> {
                if (mode == ReaderMode.VERTICAL) {
                    Box(
                        modifier = Modifier.fillMaxSize(),
                        contentAlignment = Alignment.TopCenter,
                    ) {
                        LazyColumn(
                            state = listState,
                            modifier = Modifier
                                .widthIn(max = 780.dp)
                                .fillMaxSize(),
                            contentPadding = PaddingValues(bottom = 72.dp),
                            verticalArrangement = Arrangement.spacedBy(gap.dp),
                        ) {
                            items(state.pages, key = { it.number }) { page ->
                                VerticalPage(page = page, baseUrl = baseUrl)
                            }
                        }
                    }
                } else {
                    Box(
                        modifier = Modifier.fillMaxSize(),
                        contentAlignment = Alignment.Center,
                    ) {
                        HorizontalPager(
                            state = pagerState,
                            modifier = Modifier
                                .widthIn(max = 780.dp)
                                .fillMaxSize(),
                            beyondBoundsPageCount = 1,
                            key = { index -> state.pages[index].number },
                        ) { index ->
                            ZoomablePage(
                                page = state.pages[index],
                                baseUrl = baseUrl,
                                fit = fit,
                                isActive = pagerState.currentPage == index,
                                onTapZone = { fraction ->
                                    when {
                                        fraction < 0.3f && pagerState.currentPage > 0 -> {
                                            scope.launch {
                                                pagerState.animateScrollToPage(
                                                    pagerState.currentPage - 1,
                                                )
                                            }
                                        }

                                        fraction > 0.7f &&
                                            pagerState.currentPage < state.pages.lastIndex -> {
                                            scope.launch {
                                                pagerState.animateScrollToPage(
                                                    pagerState.currentPage + 1,
                                                )
                                            }
                                        }

                                        else -> chromeVisible = !chromeVisible
                                    }
                                },
                            )
                        }
                    }
                }

                val resumePage = state.pendingResumePage
                if (resumePage != null) {
                    ReaderResumeBanner(
                        page = resumePage,
                        onContinue = viewModel::continueFromResume,
                        onStartOver = viewModel::restartChapter,
                        modifier = Modifier
                            .align(Alignment.TopCenter)
                            .statusBarsPadding()
                            .padding(top = 62.dp, start = 12.dp, end = 12.dp),
                    )
                }

                AnimatedVisibility(
                    visible = chromeVisible,
                    enter = fadeIn(),
                    exit = fadeOut(),
                    modifier = Modifier.align(Alignment.TopCenter),
                ) {
                    ReaderTopBar(
                        state = state,
                        mode = mode,
                        onBack = onBack,
                        onToggleBookmark = viewModel::toggleBookmark,
                        onToggleMode = {
                            val next = if (mode == ReaderMode.VERTICAL) {
                                ReaderMode.HORIZONTAL
                            } else {
                                ReaderMode.VERTICAL
                            }
                            if (next == ReaderMode.HORIZONTAL) autoScroll = false
                            modeOverride = next.key
                            scope.launch {
                                container.settingsStore.updateReaderMode(next.key)
                            }
                        },
                        onSettings = { showSettings = true },
                    )
                }

                AnimatedVisibility(
                    visible = chromeVisible,
                    enter = fadeIn(),
                    exit = fadeOut(),
                    modifier = Modifier.align(Alignment.BottomCenter),
                ) {
                    ReaderBottomBar(
                        state = state,
                        onPrevious = viewModel::previousChapter,
                        onNext = viewModel::nextChapter,
                    )
                }
            }
        }
    }

    if (showSettings) {
        ReaderSettingsSheet(
            mode = mode,
            fit = fit,
            gap = gap,
            autoScroll = autoScroll,
            speed = speed,
            keepScreenOn = keepScreenOn,
            theme = currentTheme,
            onDismiss = { showSettings = false },
            onModeChange = { newMode ->
                if (newMode == ReaderMode.HORIZONTAL) autoScroll = false
                modeOverride = newMode.key
                scope.launch { container.settingsStore.updateReaderMode(newMode.key) }
            },
            onFitChange = { newFit ->
                fitOverride = newFit.key
                scope.launch { container.settingsStore.updatePageFit(newFit.key) }
            },
            onGapChange = { gapOverride = it },
            onGapCommit = {
                scope.launch { container.settingsStore.updateReaderGap(gap) }
            },
            onAutoScrollChange = { autoScroll = it },
            onSpeedChange = { speedOverride = it },
            onSpeedCommit = {
                val value = speedOverride ?: settings.autoScrollSpeed
                scope.launch { container.settingsStore.updateAutoScrollSpeed(value) }
            },
            onKeepScreenChange = { enabled ->
                keepScreenOverride = enabled
                scope.launch { container.settingsStore.updateKeepScreenOn(enabled) }
            },
            onThemeChange = { theme ->
                scope.launch { container.settingsStore.updateTheme(theme.key) }
            },
        )
    }
}

@Composable
private fun ReaderLoading() {
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center,
    ) {
        CircularProgressIndicator(color = MaterialTheme.colorScheme.primary)
    }
}

@Composable
private fun ReaderBackButton(
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        shape = RoundedCornerShape(999.dp),
        color = Color.Black.copy(alpha = 0.45f),
        contentColor = Color.White,
        modifier = modifier
            .statusBarsPadding()
            .padding(8.dp),
    ) {
        IconButton(onClick = onBack) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                contentDescription = stringResource(R.string.cd_reader_back),
            )
        }
    }
}

@Composable
private fun ReaderError(
    message: String,
    onRetry: () -> Unit,
    onBack: () -> Unit,
) {
    Box(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .align(Alignment.Center)
                .padding(32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                text = stringResource(R.string.reader_error),
                style = MaterialTheme.typography.titleLarge,
                color = Color.White,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.height(8.dp))
            Text(
                text = message,
                style = MaterialTheme.typography.bodyMedium,
                color = Color.White.copy(alpha = 0.72f),
            )
            Spacer(Modifier.height(18.dp))
            Button(onClick = onRetry) {
                Text(stringResource(R.string.action_retry))
            }
            TextButton(onClick = onBack) {
                Text(stringResource(R.string.action_back), color = Color.White)
            }
        }
        ReaderBackButton(onBack = onBack, modifier = Modifier.align(Alignment.TopStart))
    }
}

@Composable
private fun ReaderTopBar(
    state: ReaderUiState,
    mode: ReaderMode,
    onBack: () -> Unit,
    onToggleBookmark: () -> Unit,
    onToggleMode: () -> Unit,
    onSettings: () -> Unit,
) {
    val chapter = chapterLabel(
        volume = state.volume,
        number = state.number,
        title = state.chapterTitle ?: state.localLabel,
    )
    val total = state.pages.size.coerceAtLeast(1)
    val fraction = (state.currentPage.toFloat() / total).coerceIn(0f, 1f)

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(ReaderBlack.copy(alpha = 0.82f)),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .statusBarsPadding()
                .padding(horizontal = 4.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(
                    imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                    contentDescription = stringResource(R.string.cd_reader_back),
                    tint = Color.White,
                )
            }
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = state.mangaTitle.ifBlank { stringResource(R.string.reader_title) },
                    style = MaterialTheme.typography.titleSmall,
                    color = Color.White,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = chapter,
                        style = MaterialTheme.typography.labelSmall,
                        color = Color.White.copy(alpha = 0.48f),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    if (state.isLocal) {
                        Spacer(Modifier.width(6.dp))
                        Surface(
                            shape = RoundedCornerShape(999.dp),
                            color = MangaTheme.colors.accent.copy(alpha = 0.22f),
                            contentColor = MangaTheme.colors.accentText,
                        ) {
                            Text(
                                text = stringResource(R.string.reader_local_badge),
                                style = MaterialTheme.typography.labelSmall,
                                modifier = Modifier.padding(horizontal = 7.dp, vertical = 1.dp),
                            )
                        }
                    }
                }
            }
            IconButton(onClick = onToggleBookmark) {
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
                        Color.White
                    },
                )
            }
            IconButton(onClick = onToggleMode) {
                Icon(
                    imageVector = if (mode == ReaderMode.VERTICAL) {
                        Icons.Default.SwapHoriz
                    } else {
                        Icons.Default.SwapVert
                    },
                    contentDescription = stringResource(R.string.cd_toggle_mode),
                    tint = Color.White,
                )
            }
            IconButton(onClick = onSettings) {
                Icon(
                    imageVector = Icons.Default.Settings,
                    contentDescription = stringResource(R.string.cd_reader_settings),
                    tint = Color.White,
                )
            }
        }
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(1.dp)
                .background(Color.White.copy(alpha = 0.09f)),
        )
        LinearProgressIndicator(
            progress = fraction,
            modifier = Modifier
                .fillMaxWidth()
                .height(2.dp),
            color = MaterialTheme.colorScheme.primary,
            trackColor = Color.White.copy(alpha = 0.08f),
        )
    }
}

@Composable
private fun ReaderBottomBar(
    state: ReaderUiState,
    onPrevious: () -> Unit,
    onNext: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(
                Brush.verticalGradient(
                    listOf(Color.Transparent, ReaderBlack.copy(alpha = 0.94f)),
                ),
            )
            .navigationBarsPadding()
            .padding(top = 34.dp, bottom = 4.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(
                onClick = onPrevious,
                enabled = state.prevChapterId != null,
            ) {
                Icon(
                    imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                    contentDescription = stringResource(R.string.cd_prev_chapter),
                    tint = if (state.prevChapterId != null) {
                        Color.White
                    } else {
                        Color.White.copy(alpha = 0.3f)
                    },
                )
            }
            Text(
                text = stringResource(
                    R.string.reader_page_short,
                    state.currentPage,
                    state.pages.size,
                ),
                style = MaterialTheme.typography.labelMedium,
                color = Color.White,
                modifier = Modifier.weight(1f),
                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            )
            IconButton(
                onClick = onNext,
                enabled = state.nextChapterId != null,
            ) {
                Icon(
                    imageVector = Icons.AutoMirrored.Filled.ArrowForward,
                    contentDescription = stringResource(R.string.cd_next_chapter),
                    tint = if (state.nextChapterId != null) {
                        Color.White
                    } else {
                        Color.White.copy(alpha = 0.3f)
                    },
                )
            }
        }
    }
}

@Composable
private fun ReaderResumeBanner(
    page: Int,
    onContinue: () -> Unit,
    onStartOver: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        shape = RoundedCornerShape(10.dp),
        color = ReaderBlack.copy(alpha = 0.88f),
        border = BorderStroke(1.dp, Color.White.copy(alpha = 0.14f)),
        modifier = modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
            Text(
                text = stringResource(R.string.reader_resume_title, page),
                style = MaterialTheme.typography.labelMedium,
                color = Color.White.copy(alpha = 0.82f),
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                TextButton(onClick = onStartOver) {
                    Text(
                        text = stringResource(R.string.reader_resume_start),
                        color = Color.White.copy(alpha = 0.72f),
                    )
                }
                TextButton(onClick = onContinue) {
                    Text(
                        text = stringResource(R.string.reader_resume_continue),
                        color = MangaTheme.colors.accentText,
                        fontWeight = FontWeight.SemiBold,
                    )
                }
            }
        }
    }
}

@Composable
private fun VerticalPage(page: ReaderPage, baseUrl: String) {
    val ratio = pageAspect(page)
    val contentDescription = stringResource(
        R.string.reader_page_content_description,
        page.number,
    )
    if (ratio != null) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .aspectRatio(ratio)
                .background(Color.Black),
        ) {
            ReaderImage(
                page = page,
                baseUrl = baseUrl,
                contentScale = ContentScale.FillWidth,
                contentDescription = contentDescription,
                modifier = Modifier.fillMaxSize(),
            )
        }
    } else {
        ReaderImage(
            page = page,
            baseUrl = baseUrl,
            contentScale = ContentScale.FillWidth,
            contentDescription = contentDescription,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun ZoomablePage(
    page: ReaderPage,
    baseUrl: String,
    fit: PageFit,
    isActive: Boolean,
    onTapZone: (Float) -> Unit,
) {
    val contentDescription = stringResource(
        R.string.reader_page_content_description,
        page.number,
    )
    var scale by remember(page.number) { mutableStateOf(1f) }
    var offset by remember(page.number) { mutableStateOf(Offset.Zero) }
    var boxSize by remember { mutableStateOf(IntSize.Zero) }

    LaunchedEffect(isActive) {
        if (!isActive) {
            scale = 1f
            offset = Offset.Zero
        }
    }

    val contentScale = when (fit) {
        PageFit.WIDTH -> ContentScale.FillWidth
        PageFit.HEIGHT -> ContentScale.FillHeight
        PageFit.SCREEN -> ContentScale.Fit
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
            .onSizeChanged { boxSize = it }
            .pointerInput(scale > 1f) {
                if (scale > 1f) {
                    detectTransformGestures { _, pan, zoom, _ ->
                        val newScale = (scale * zoom).coerceIn(1f, 5f)
                        val maxX = (boxSize.width * (newScale - 1f)) / 2f
                        val maxY = (boxSize.height * (newScale - 1f)) / 2f
                        val newOffset = if (newScale <= 1f) {
                            Offset.Zero
                        } else {
                            Offset(
                                x = (offset.x + pan.x).coerceIn(-maxX, maxX),
                                y = (offset.y + pan.y).coerceIn(-maxY, maxY),
                            )
                        }
                        scale = newScale
                        offset = newOffset
                    }
                }
            }
            .pointerInput(Unit) {
                // Horizontal reader tap zones: left 30% previous page, centre 40%
                // toggles chrome, right 30% next page. Double tap zooms.
                detectTapGestures(
                    onTap = { tapOffset ->
                        if (scale > 1f) {
                            scale = 1f
                            offset = Offset.Zero
                        } else if (boxSize.width > 0) {
                            onTapZone(tapOffset.x / boxSize.width)
                        }
                    },
                    onDoubleTap = {
                        if (scale > 1f) {
                            scale = 1f
                            offset = Offset.Zero
                        } else {
                            scale = 2.5f
                            offset = Offset.Zero
                        }
                    },
                )
            },
    ) {
        ReaderImage(
            page = page,
            baseUrl = baseUrl,
            contentScale = contentScale,
            contentDescription = contentDescription,
            modifier = Modifier
                .fillMaxSize()
                .graphicsLayer {
                    scaleX = scale
                    scaleY = scale
                    translationX = offset.x
                    translationY = offset.y
                },
        )
    }
}

@Composable
private fun ReaderImage(
    page: ReaderPage,
    baseUrl: String,
    contentScale: ContentScale,
    contentDescription: String,
    modifier: Modifier = Modifier,
) {
    val data: Any? = page.localFile
        ?: MediaUrlResolver.resolve(page.url, baseUrl)
    AsyncImage(
        model = data,
        contentDescription = contentDescription,
        contentScale = contentScale,
        placeholder = painterResource(R.drawable.placeholder_poster),
        error = painterResource(R.drawable.placeholder_poster),
        fallback = painterResource(R.drawable.placeholder_poster),
        modifier = modifier,
    )
}

private fun pageAspect(page: ReaderPage): Float? {
    val width = page.width ?: return null
    val height = page.height ?: return null
    if (width <= 0 || height <= 0) return null
    return width.toFloat() / height.toFloat()
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ReaderSettingsSheet(
    mode: ReaderMode,
    fit: PageFit,
    gap: Int,
    autoScroll: Boolean,
    speed: Int,
    keepScreenOn: Boolean,
    theme: ThemeMode,
    onDismiss: () -> Unit,
    onModeChange: (ReaderMode) -> Unit,
    onFitChange: (PageFit) -> Unit,
    onGapChange: (Int) -> Unit,
    onGapCommit: () -> Unit,
    onAutoScrollChange: (Boolean) -> Unit,
    onSpeedChange: (Int) -> Unit,
    onSpeedCommit: () -> Unit,
    onKeepScreenChange: (Boolean) -> Unit,
    onThemeChange: (ThemeMode) -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp)
                .padding(bottom = 28.dp),
        ) {
            Text(
                text = stringResource(R.string.reader_settings),
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold,
            )
            Spacer(Modifier.height(18.dp))
            Text(
                text = stringResource(R.string.reader_mode),
                style = MaterialTheme.typography.titleSmall,
            )
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(
                    selected = mode == ReaderMode.VERTICAL,
                    onClick = { onModeChange(ReaderMode.VERTICAL) },
                    label = { Text(stringResource(R.string.reader_mode_vertical)) },
                )
                FilterChip(
                    selected = mode == ReaderMode.HORIZONTAL,
                    onClick = { onModeChange(ReaderMode.HORIZONTAL) },
                    label = { Text(stringResource(R.string.reader_mode_horizontal)) },
                )
            }
            Spacer(Modifier.height(16.dp))
            Text(
                text = stringResource(R.string.reader_fit),
                style = MaterialTheme.typography.titleSmall,
            )
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(
                    selected = fit == PageFit.WIDTH,
                    onClick = { onFitChange(PageFit.WIDTH) },
                    label = { Text(stringResource(R.string.reader_fit_width)) },
                )
                FilterChip(
                    selected = fit == PageFit.HEIGHT,
                    onClick = { onFitChange(PageFit.HEIGHT) },
                    label = { Text(stringResource(R.string.reader_fit_height)) },
                )
                FilterChip(
                    selected = fit == PageFit.SCREEN,
                    onClick = { onFitChange(PageFit.SCREEN) },
                    label = { Text(stringResource(R.string.reader_fit_screen)) },
                )
            }
            Spacer(Modifier.height(16.dp))
            Text(
                text = stringResource(R.string.reader_gap),
                style = MaterialTheme.typography.titleSmall,
            )
            Text(
                text = stringResource(R.string.reader_gap_value, gap),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Slider(
                value = gap.toFloat(),
                onValueChange = { onGapChange(it.roundToInt()) },
                onValueChangeFinished = onGapCommit,
                valueRange = 0f..32f,
                steps = 7,
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(12.dp))
            Text(
                text = stringResource(R.string.reader_theme),
                style = MaterialTheme.typography.titleSmall,
            )
            Spacer(Modifier.height(8.dp))
            LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                items(ThemeMode.entries, key = { it.key }) { item ->
                    FilterChip(
                        selected = theme == item,
                        onClick = { onThemeChange(item) },
                        label = { Text(stringResource(item.titleRes)) },
                    )
                }
            }
            Spacer(Modifier.height(16.dp))
            Divider()
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = stringResource(R.string.reader_auto_scroll),
                        style = MaterialTheme.typography.titleSmall,
                    )
                    Text(
                        text = stringResource(R.string.reader_auto_scroll_speed),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Switch(
                    checked = autoScroll,
                    onCheckedChange = onAutoScrollChange,
                    enabled = mode == ReaderMode.VERTICAL,
                )
            }
            Slider(
                value = speed.toFloat(),
                onValueChange = { onSpeedChange(it.roundToInt()) },
                onValueChangeFinished = onSpeedCommit,
                valueRange = 10f..100f,
                steps = 8,
                enabled = mode == ReaderMode.VERTICAL,
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = stringResource(R.string.reader_keep_screen_on),
                    style = MaterialTheme.typography.titleSmall,
                    modifier = Modifier.weight(1f),
                )
                Switch(
                    checked = keepScreenOn,
                    onCheckedChange = onKeepScreenChange,
                )
            }
            Spacer(Modifier.height(10.dp))
            Text(
                text = stringResource(R.string.reader_zoom_hint),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

private tailrec fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}
