package ru.mangapoisk.reborn.ui.sources

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import ru.mangapoisk.reborn.R
import ru.mangapoisk.reborn.data.model.Source
import ru.mangapoisk.reborn.ui.LocalAppContainer
import ru.mangapoisk.reborn.ui.components.EmptyState
import ru.mangapoisk.reborn.ui.components.ErrorState
import ru.mangapoisk.reborn.ui.components.LoadingBox
import ru.mangapoisk.reborn.ui.theme.MangaTheme
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SourcesScreen(onBack: () -> Unit) {
    val container = LocalAppContainer.current
    val viewModel: SourcesViewModel = viewModel(
        factory = remember(container) { SourcesViewModel.factory(container) },
    )
    val state by viewModel.state.collectAsStateWithLifecycle()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.sources_title)) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = stringResource(R.string.cd_back),
                        )
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
                .padding(padding)
                .navigationBarsPadding(),
            contentAlignment = Alignment.TopCenter,
        ) {
            when {
                state.isLoading -> LoadingBox()
                state.error != null && state.sources.isEmpty() -> ErrorState(
                    error = state.error,
                    onRetry = viewModel::load,
                )
                state.sources.isEmpty() -> EmptyState(
                    title = stringResource(R.string.sources_empty_title),
                    text = stringResource(R.string.sources_empty_text),
                    icon = Icons.Default.CloudOff,
                    actionLabel = stringResource(R.string.action_retry),
                    onAction = viewModel::load,
                )
                else -> LazyColumn(
                    modifier = Modifier
                        .widthIn(max = 980.dp)
                        .fillMaxWidth(),
                    contentPadding = PaddingValues(16.dp, 8.dp, 16.dp, 32.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    item(key = "legal") {
                        Surface(
                            shape = RoundedCornerShape(14.dp),
                            color = MangaTheme.colors.surface2,
                            border = BorderStroke(1.dp, MangaTheme.colors.border),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text(
                                text = stringResource(R.string.sources_legal),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(16.dp),
                            )
                        }
                    }
                    items(state.sources, key = { it.code }) { source ->
                        SourceCard(source)
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SourceCard(source: Source) {
    Surface(
        shape = RoundedCornerShape(18.dp),
        color = MaterialTheme.colorScheme.surface,
        border = BorderStroke(1.dp, MangaTheme.colors.border),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Surface(
                    shape = CircleShape,
                    color = MangaTheme.colors.surface2,
                    contentColor = MangaTheme.colors.accentText,
                    modifier = Modifier.size(44.dp),
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Text(
                            text = source.name.take(1).uppercase(Locale.getDefault()),
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }
                Spacer(Modifier.width(12.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = source.name,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(
                        text = stringResource(
                            R.string.source_language,
                            languageLabel(source.language),
                        ),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                SourceStatusBadge(source.enabled)
            }
            Spacer(Modifier.height(12.dp))
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                if (source.supportsSearch) CapabilityTag(stringResource(R.string.source_capability_search))
                if (source.supportsCatalog) CapabilityTag(stringResource(R.string.source_capability_catalog))
                if (source.supportsLatest) CapabilityTag(stringResource(R.string.source_capability_latest))
                if (source.supportsChapters) CapabilityTag(stringResource(R.string.source_capability_chapters))
                if (source.supportsPages) CapabilityTag(stringResource(R.string.source_capability_pages))
            }
            if (source.requiresCookies) {
                Spacer(Modifier.height(10.dp))
                Text(
                    text = stringResource(R.string.source_requires_cookies),
                    style = MaterialTheme.typography.labelSmall,
                    color = MangaTheme.colors.dangerText,
                )
            }
        }
    }
}

@Composable
private fun SourceStatusBadge(enabled: Boolean) {
    val color = if (enabled) MangaTheme.colors.success else MangaTheme.colors.danger
    val textColor = if (enabled) MangaTheme.colors.successText else MangaTheme.colors.dangerText
    Surface(
        shape = RoundedCornerShape(999.dp),
        color = color.copy(alpha = 0.14f),
        contentColor = textColor,
    ) {
        Text(
            text = stringResource(
                if (enabled) R.string.source_status_enabled else R.string.source_status_disabled,
            ),
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
        )
    }
}

@Composable
private fun CapabilityTag(text: String) {
    Surface(
        shape = RoundedCornerShape(999.dp),
        color = MangaTheme.colors.surface2,
        contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelSmall,
            modifier = Modifier.padding(horizontal = 9.dp, vertical = 4.dp),
        )
    }
}

@Composable
private fun languageLabel(language: String?): String {
    val value = language?.trim()?.lowercase(Locale.ROOT).orEmpty()
    return when (value) {
        "ru", "russian" -> stringResource(R.string.language_russian)
        "en", "english" -> stringResource(R.string.language_english)
        "" -> stringResource(R.string.unknown_value)
        else -> value.uppercase(Locale.getDefault())
    }
}
