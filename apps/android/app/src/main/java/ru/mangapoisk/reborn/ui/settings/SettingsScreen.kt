package ru.mangapoisk.reborn.ui.settings

import androidx.compose.foundation.border
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
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.text.KeyboardOptions
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.AsyncImage
import coil.imageLoader
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import ru.mangapoisk.reborn.BuildConfig
import ru.mangapoisk.reborn.R
import ru.mangapoisk.reborn.data.model.PageFit
import ru.mangapoisk.reborn.data.model.ReaderMode
import ru.mangapoisk.reborn.ui.LocalAppContainer
import ru.mangapoisk.reborn.ui.theme.MangaTheme
import ru.mangapoisk.reborn.ui.theme.ThemeId
import ru.mangapoisk.reborn.ui.theme.paletteFor
import kotlin.math.roundToInt

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun SettingsScreen(
    onOpenAuth: (register: Boolean) -> Unit,
    onOpenSources: () -> Unit,
) {
    val container = LocalAppContainer.current
    val viewModel: SettingsViewModel = viewModel(
        factory = remember(container) { SettingsViewModel.factory(container) },
    )
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    val invalidUrl = stringResource(R.string.settings_api_invalid)
    val insecureUrl = stringResource(R.string.settings_api_release_https)
    val savedUrl = stringResource(R.string.settings_api_saved)
    val savedAndLoggedOut = stringResource(R.string.settings_api_changed_logout)
    val loggedOut = stringResource(R.string.settings_sign_out_title)
    val downloadsCleared = stringResource(R.string.settings_clear_downloads_done)
    val historyCleared = stringResource(R.string.settings_clear_history_done)
    val cacheCleared = stringResource(R.string.settings_clear_cache_done)

    var showLogoutDialog by remember { mutableStateOf(false) }
    var showClearDownloadsDialog by remember { mutableStateOf(false) }
    var showClearHistoryDialog by remember { mutableStateOf(false) }

    LaunchedEffect(viewModel) {
        viewModel.events.collect { event ->
            val message = when (event) {
                SettingsEvent.InvalidUrl -> invalidUrl
                SettingsEvent.InsecureUrl -> insecureUrl
                is SettingsEvent.BaseUrlSaved -> if (event.loggedOut) {
                    savedAndLoggedOut
                } else {
                    savedUrl
                }
                SettingsEvent.LoggedOut -> loggedOut
                SettingsEvent.DownloadsCleared -> downloadsCleared
                SettingsEvent.HistoryCleared -> historyCleared
            }
            snackbarHostState.showSnackbar(message)
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.settings_title)) },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
            )
        },
        snackbarHost = { SnackbarHost(snackbarHostState) },
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(
                start = 16.dp,
                end = 16.dp,
                top = 8.dp,
                bottom = 32.dp,
            ),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            item(key = "account") {
                AccountSection(
                    userName = state.user?.displayName,
                    email = state.user?.email,
                    onLogin = { onOpenAuth(false) },
                    onRegister = { onOpenAuth(true) },
                    onLogout = { showLogoutDialog = true },
                )
            }

            item(key = "theme") {
                SettingsSection(title = stringResource(R.string.settings_theme)) {
                    Text(
                        text = stringResource(R.string.settings_theme_hint),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(12.dp))
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        ThemeId.entries.forEach { theme ->
                            ThemeSwatch(
                                theme = theme,
                                selected = ThemeId.fromKey(state.settings.themeId) == theme,
                                onClick = { viewModel.setTheme(theme.key) },
                            )
                        }
                    }
                }
            }

            item(key = "api") {
                SettingsSection(title = stringResource(R.string.settings_api)) {
                    OutlinedTextField(
                        value = state.baseUrlInput,
                        onValueChange = viewModel::onBaseUrlChange,
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        label = { Text(stringResource(R.string.settings_api_label)) },
                        placeholder = { Text(stringResource(R.string.settings_api_hint)) },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                    )
                    Spacer(Modifier.height(6.dp))
                    Text(
                        text = stringResource(R.string.settings_api_release_https),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(10.dp))
                    Button(
                        onClick = viewModel::saveBaseUrl,
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 48.dp),
                    ) {
                        Text(
                            text = stringResource(R.string.settings_api_save),
                            maxLines = 1,
                        )
                    }
                    Spacer(Modifier.height(8.dp))
                    OutlinedButton(
                        onClick = viewModel::resetBaseUrl,
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 48.dp),
                    ) {
                        Text(
                            text = stringResource(R.string.settings_api_reset),
                            maxLines = 1,
                        )
                    }
                }
            }

            item(key = "reader") {
                SettingsSection(title = stringResource(R.string.settings_reader)) {
                    Text(
                        text = stringResource(R.string.settings_reader_mode),
                        style = MaterialTheme.typography.titleSmall,
                    )
                    Spacer(Modifier.height(6.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        FilterChip(
                            selected = ReaderMode.fromKey(state.settings.readerMode) ==
                                ReaderMode.VERTICAL,
                            onClick = { viewModel.setReaderMode(ReaderMode.VERTICAL.key) },
                            label = { Text(stringResource(R.string.reader_mode_vertical)) },
                        )
                        FilterChip(
                            selected = ReaderMode.fromKey(state.settings.readerMode) ==
                                ReaderMode.HORIZONTAL,
                            onClick = { viewModel.setReaderMode(ReaderMode.HORIZONTAL.key) },
                            label = { Text(stringResource(R.string.reader_mode_horizontal)) },
                        )
                    }
                    Spacer(Modifier.height(12.dp))
                    Text(
                        text = stringResource(R.string.settings_reader_fit),
                        style = MaterialTheme.typography.titleSmall,
                    )
                    Spacer(Modifier.height(6.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        PageFit.entries.forEach { fit ->
                            FilterChip(
                                selected = PageFit.fromKey(state.settings.pageFit) == fit,
                                onClick = { viewModel.setPageFit(fit.key) },
                                label = {
                                    Text(
                                        stringResource(
                                            when (fit) {
                                                PageFit.WIDTH -> R.string.reader_fit_width
                                                PageFit.HEIGHT -> R.string.reader_fit_height
                                                PageFit.SCREEN -> R.string.reader_fit_screen
                                            },
                                        ),
                                    )
                                },
                            )
                        }
                    }
                    Spacer(Modifier.height(12.dp))
                    ReaderSpeedControl(
                        speed = state.settings.autoScrollSpeed,
                        onCommit = viewModel::setAutoScrollSpeed,
                    )
                    Spacer(Modifier.height(8.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            text = stringResource(R.string.settings_keep_screen_on),
                            style = MaterialTheme.typography.titleSmall,
                            modifier = Modifier.weight(1f),
                        )
                        Switch(
                            checked = state.settings.keepScreenOn,
                            onCheckedChange = viewModel::setKeepScreenOn,
                        )
                    }
                    Spacer(Modifier.height(4.dp))
                    Text(
                        text = stringResource(R.string.settings_reader_saved),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            item(key = "sources") {
                SettingsSection(title = stringResource(R.string.settings_sources)) {
                    Text(
                        text = stringResource(R.string.settings_sources_text),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(10.dp))
                    OutlinedButton(
                        onClick = onOpenSources,
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 48.dp),
                    ) {
                        Text(stringResource(R.string.settings_sources))
                    }
                }
            }

            item(key = "cache") {
                SettingsSection(title = stringResource(R.string.settings_cache)) {
                    OutlinedButton(
                        onClick = {
                            scope.launch {
                                val loader = context.imageLoader
                                loader.memoryCache?.clear()
                                withContext(Dispatchers.IO) { loader.diskCache?.clear() }
                                snackbarHostState.showSnackbar(cacheCleared)
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(stringResource(R.string.settings_clear_cache))
                    }
                    Spacer(Modifier.height(8.dp))
                    OutlinedButton(
                        onClick = { showClearDownloadsDialog = true },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(stringResource(R.string.settings_clear_downloads))
                    }
                    Spacer(Modifier.height(8.dp))
                    OutlinedButton(
                        onClick = { showClearHistoryDialog = true },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(stringResource(R.string.settings_clear_history))
                    }
                }
            }

            item(key = "about") {
                SettingsSection(title = stringResource(R.string.settings_about)) {
                    Text(
                        text = stringResource(R.string.settings_version, BuildConfig.VERSION_NAME),
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Spacer(Modifier.height(4.dp))
                    Text(
                        text = stringResource(R.string.settings_about_api, state.settings.baseUrl),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(10.dp))
                    Text(
                        text = stringResource(R.string.settings_legal),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }

    if (showLogoutDialog) {
        AlertDialog(
            onDismissRequest = { showLogoutDialog = false },
            title = { Text(stringResource(R.string.settings_logout_confirm)) },
            text = { Text(stringResource(R.string.settings_logout_confirm_text)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        showLogoutDialog = false
                        viewModel.logout()
                    },
                ) {
                    Text(stringResource(R.string.settings_logout))
                }
            },
            dismissButton = {
                TextButton(onClick = { showLogoutDialog = false }) {
                    Text(stringResource(R.string.action_cancel))
                }
            },
        )
    }

    if (showClearDownloadsDialog) {
        AlertDialog(
            onDismissRequest = { showClearDownloadsDialog = false },
            title = { Text(stringResource(R.string.settings_clear_downloads)) },
            text = { Text(stringResource(R.string.settings_clear_downloads_confirm)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        showClearDownloadsDialog = false
                        viewModel.clearDownloads()
                    },
                ) {
                    Text(stringResource(R.string.action_delete))
                }
            },
            dismissButton = {
                TextButton(onClick = { showClearDownloadsDialog = false }) {
                    Text(stringResource(R.string.action_cancel))
                }
            },
        )
    }

    if (showClearHistoryDialog) {
        AlertDialog(
            onDismissRequest = { showClearHistoryDialog = false },
            title = { Text(stringResource(R.string.settings_clear_history)) },
            text = { Text(stringResource(R.string.settings_clear_history_confirm)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        showClearHistoryDialog = false
                        viewModel.clearHistory()
                    },
                ) {
                    Text(stringResource(R.string.action_delete))
                }
            },
            dismissButton = {
                TextButton(onClick = { showClearHistoryDialog = false }) {
                    Text(stringResource(R.string.action_cancel))
                }
            },
        )
    }
}

@Composable
private fun ReaderSpeedControl(speed: Int, onCommit: (Int) -> Unit) {
    var value by remember(speed) { mutableStateOf(speed.toFloat()) }
    Text(
        text = stringResource(R.string.settings_auto_scroll_speed_value, value.roundToInt()),
        style = MaterialTheme.typography.titleSmall,
    )
    Slider(
        value = value,
        onValueChange = { value = it },
        onValueChangeFinished = { onCommit(value.roundToInt()) },
        valueRange = 10f..100f,
        steps = 8,
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun AccountSection(
    userName: String?,
    email: String?,
    onLogin: () -> Unit,
    onRegister: () -> Unit,
    onLogout: () -> Unit,
) {
    SettingsSection(title = stringResource(R.string.settings_account)) {
        if (userName != null) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Surface(
                    shape = CircleShape,
                    color = MaterialTheme.colorScheme.primaryContainer,
                    contentColor = MaterialTheme.colorScheme.onPrimaryContainer,
                    modifier = Modifier.size(56.dp),
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Text(
                            text = userName.take(1).uppercase(),
                            style = MaterialTheme.typography.headlineSmall,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }
                Spacer(Modifier.width(12.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = userName.ifBlank { stringResource(R.string.settings_guest) },
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    if (!email.isNullOrBlank()) {
                        Text(
                            text = email,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }
                TextButton(onClick = onLogout) {
                    Text(stringResource(R.string.settings_logout))
                }
            }
        } else {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Surface(
                    shape = CircleShape,
                    color = MaterialTheme.colorScheme.surfaceVariant,
                    contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(56.dp),
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Icon(
                            imageVector = Icons.Default.Person,
                            contentDescription = null,
                            modifier = Modifier.size(28.dp),
                        )
                    }
                }
                Spacer(Modifier.width(12.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = stringResource(R.string.settings_guest),
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        text = stringResource(R.string.settings_guest_text),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onLogin, modifier = Modifier.weight(1f)) {
                    Text(stringResource(R.string.settings_login))
                }
                OutlinedButton(onClick = onRegister, modifier = Modifier.weight(1f)) {
                    Text(stringResource(R.string.settings_register))
                }
            }
        }
    }
}

@Composable
private fun SettingsSection(
    title: String,
    content: @Composable () -> Unit,
) {
    Column {
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.padding(start = 4.dp, bottom = 8.dp),
        )
        Surface(
            shape = MaterialTheme.shapes.large,
            color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.45f),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(modifier = Modifier.padding(14.dp)) {
                content()
            }
        }
    }
}

@Composable
private fun ThemeSwatch(
    theme: ThemeId,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val palette = paletteFor(theme)
    val borderColor = if (selected) {
        MaterialTheme.colorScheme.primary
    } else {
        MangaTheme.colors.border
    }
    Column(
        modifier = Modifier
            .width(142.dp)
            .clip(MaterialTheme.shapes.medium)
            .selectable(
                selected = selected,
                onClick = onClick,
                role = Role.RadioButton,
            )
            .padding(3.dp),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(70.dp)
                .clip(RoundedCornerShape(9.dp))
                .border(if (selected) 2.dp else 1.dp, borderColor, RoundedCornerShape(9.dp)),
        ) {
            AsyncImage(
                model = theme.backgroundRes,
                contentDescription = null,
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize(),
            )
            if (selected) {
                Surface(
                    shape = CircleShape,
                    color = MaterialTheme.colorScheme.primary,
                    contentColor = MaterialTheme.colorScheme.onPrimary,
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .padding(5.dp)
                        .size(20.dp),
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Icon(
                            imageVector = Icons.Default.Check,
                            contentDescription = null,
                            modifier = Modifier.size(14.dp),
                        )
                    }
                }
            }
        }
        Row(
            modifier = Modifier.padding(top = 6.dp, start = 2.dp),
            horizontalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            listOf(
                palette.accent,
                palette.accent2,
                palette.success,
                palette.danger,
            ).forEach { color ->
                Surface(
                    shape = CircleShape,
                    color = color,
                    modifier = Modifier.size(8.dp),
                ) {}
            }
        }
        Text(
            text = stringResource(theme.titleRes),
            style = MaterialTheme.typography.labelMedium,
            fontWeight = if (selected) FontWeight.Bold else FontWeight.Medium,
            color = if (selected) {
                MangaTheme.colors.accentText
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
            maxLines = 1,
            modifier = Modifier.padding(top = 4.dp, start = 2.dp, bottom = 2.dp),
        )
    }
}
