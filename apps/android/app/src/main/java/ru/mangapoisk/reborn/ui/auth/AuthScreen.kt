package ru.mangapoisk.reborn.ui.auth

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.AsyncImage
import ru.mangapoisk.reborn.R
import ru.mangapoisk.reborn.ui.LocalAppContainer
import ru.mangapoisk.reborn.ui.LocalThemeId
import ru.mangapoisk.reborn.ui.theme.MangaTheme
import ru.mangapoisk.reborn.ui.util.userMessage

@Composable
fun AuthScreen(
    initialRegister: Boolean,
    onBack: () -> Unit,
    onAuthenticated: () -> Unit,
) {
    val container = LocalAppContainer.current
    val viewModel: AuthViewModel = viewModel(
        factory = remember(container, initialRegister) {
            AuthViewModel.factory(container, initialRegister)
        },
    )
    val state by viewModel.state.collectAsStateWithLifecycle()
    val theme = LocalThemeId.current
    val focusManager = LocalFocusManager.current
    var passwordVisible by rememberSaveable { mutableStateOf(false) }

    LaunchedEffect(viewModel) {
        viewModel.events.collect { event ->
            when (event) {
                AuthEvent.Authenticated -> onAuthenticated()
            }
        }
    }

    BoxWithConstraints(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background),
    ) {
        val wide = maxWidth >= 720.dp

        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .statusBarsPadding()
                .navigationBarsPadding(),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Row(
                modifier = Modifier
                    .widthIn(max = 1200.dp)
                    .fillMaxWidth()
                    .heightIn(min = 56.dp)
                    .padding(horizontal = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = onBack) {
                    Icon(
                        imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                        contentDescription = stringResource(R.string.cd_back),
                    )
                }
                Spacer(Modifier.weight(1f))
                Column(horizontalAlignment = Alignment.End) {
                    Text(
                        text = stringResource(R.string.home_title),
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        text = stringResource(R.string.home_reborn).uppercase(),
                        style = MaterialTheme.typography.labelSmall,
                        color = MangaTheme.colors.accentText,
                    )
                }
            }

            if (wide) {
                Row(
                    modifier = Modifier
                        .widthIn(max = 1200.dp)
                        .fillMaxWidth()
                        .padding(horizontal = 24.dp, vertical = 18.dp),
                    horizontalArrangement = Arrangement.spacedBy(32.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    AuthFormCard(
                        state = state,
                        passwordVisible = passwordVisible,
                        onPasswordVisibleChange = { passwordVisible = it },
                        onModeChange = viewModel::setMode,
                        onEmailChange = viewModel::setEmail,
                        onPasswordChange = viewModel::setPassword,
                        onDisplayNameChange = viewModel::setDisplayName,
                        onSubmit = {
                            focusManager.clearFocus()
                            viewModel.submit()
                        },
                        onBack = onBack,
                        modifier = Modifier.weight(1f),
                    )
                    AuthArtPanel(
                        themeBackgroundRes = theme.backgroundRes,
                        modifier = Modifier
                            .weight(1.08f)
                            .heightIn(min = 560.dp),
                    )
                }
            } else {
                AuthFormCard(
                    state = state,
                    passwordVisible = passwordVisible,
                    onPasswordVisibleChange = { passwordVisible = it },
                    onModeChange = viewModel::setMode,
                    onEmailChange = viewModel::setEmail,
                    onPasswordChange = viewModel::setPassword,
                    onDisplayNameChange = viewModel::setDisplayName,
                    onSubmit = {
                        focusManager.clearFocus()
                        viewModel.submit()
                    },
                    onBack = onBack,
                    modifier = Modifier
                        .widthIn(max = 460.dp)
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                )
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun AuthFormCard(
    state: AuthUiState,
    passwordVisible: Boolean,
    onPasswordVisibleChange: (Boolean) -> Unit,
    onModeChange: (AuthMode) -> Unit,
    onEmailChange: (String) -> Unit,
    onPasswordChange: (String) -> Unit,
    onDisplayNameChange: (String) -> Unit,
    onSubmit: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        shape = RoundedCornerShape(22.dp),
        color = MaterialTheme.colorScheme.surface,
        border = BorderStroke(1.dp, MangaTheme.colors.border),
        modifier = modifier,
    ) {
        Column(modifier = Modifier.padding(24.dp)) {
            Text(
                text = stringResource(R.string.home_title),
                style = MaterialTheme.typography.labelLarge,
                color = MangaTheme.colors.accentText,
                fontWeight = FontWeight.Bold,
            )
            Spacer(Modifier.height(6.dp))
            Text(
                text = stringResource(
                    if (state.mode == AuthMode.LOGIN) {
                        R.string.auth_title
                    } else {
                        R.string.auth_register_title
                    },
                ),
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold,
            )
            Spacer(Modifier.height(6.dp))
            Text(
                text = stringResource(
                    if (state.mode == AuthMode.LOGIN) {
                        R.string.auth_welcome
                    } else {
                        R.string.auth_welcome_register
                    },
                ),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(18.dp))

            AuthModeSwitch(
                mode = state.mode,
                enabled = !state.isLoading,
                onModeChange = onModeChange,
            )
            Spacer(Modifier.height(16.dp))

            if (state.mode == AuthMode.REGISTER) {
                OutlinedTextField(
                    value = state.displayName,
                    onValueChange = onDisplayNameChange,
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    label = { Text(stringResource(R.string.auth_display_name)) },
                    placeholder = { Text(stringResource(R.string.auth_display_name_hint)) },
                    enabled = !state.isLoading,
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                )
                Spacer(Modifier.height(10.dp))
            }

            OutlinedTextField(
                value = state.email,
                onValueChange = onEmailChange,
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                label = { Text(stringResource(R.string.auth_email)) },
                enabled = !state.isLoading,
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Email,
                    imeAction = ImeAction.Next,
                ),
            )
            Spacer(Modifier.height(10.dp))

            OutlinedTextField(
                value = state.password,
                onValueChange = onPasswordChange,
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                label = { Text(stringResource(R.string.auth_password)) },
                enabled = !state.isLoading,
                visualTransformation = if (passwordVisible) {
                    VisualTransformation.None
                } else {
                    PasswordVisualTransformation()
                },
                trailingIcon = {
                    IconButton(onClick = { onPasswordVisibleChange(!passwordVisible) }) {
                        Icon(
                            imageVector = if (passwordVisible) {
                                Icons.Default.VisibilityOff
                            } else {
                                Icons.Default.Visibility
                            },
                            contentDescription = stringResource(
                                if (passwordVisible) {
                                    R.string.auth_password_hide
                                } else {
                                    R.string.auth_password_show
                                },
                            ),
                        )
                    }
                },
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Password,
                    imeAction = ImeAction.Done,
                ),
                keyboardActions = KeyboardActions(onDone = { onSubmit() }),
            )

            val errorText = state.formErrorRes?.let { stringResource(it) }
                ?: state.appError?.takeIf {
                    state.formErrorRes == null &&
                        (it.kind == ru.mangapoisk.reborn.data.remote.ErrorKind.NETWORK ||
                            it.kind == ru.mangapoisk.reborn.data.remote.ErrorKind.TIMEOUT ||
                            it.kind == ru.mangapoisk.reborn.data.remote.ErrorKind.SERVER)
                }?.userMessage()

            if (errorText != null) {
                Spacer(Modifier.height(10.dp))
                Text(
                    text = errorText,
                    style = MaterialTheme.typography.bodySmall,
                    color = MangaTheme.colors.dangerText,
                )
            }

            Spacer(Modifier.height(18.dp))
            Button(
                onClick = onSubmit,
                enabled = !state.isLoading,
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 50.dp),
            ) {
                if (state.isLoading) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(18.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary,
                    )
                } else {
                    Text(
                        stringResource(
                            if (state.mode == AuthMode.LOGIN) {
                                R.string.auth_login_button
                            } else {
                                R.string.auth_register_button
                            },
                        ),
                    )
                }
            }

            Spacer(Modifier.height(8.dp))
            TextButton(
                onClick = onBack,
                modifier = Modifier.fillMaxWidth(),
                enabled = !state.isLoading,
            ) {
                Text(stringResource(R.string.auth_later))
            }

            Spacer(Modifier.height(10.dp))
            Text(
                text = stringResource(R.string.auth_legal),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun AuthModeSwitch(
    mode: AuthMode,
    enabled: Boolean,
    onModeChange: (AuthMode) -> Unit,
) {
    Surface(
        shape = RoundedCornerShape(10.dp),
        color = MangaTheme.colors.surface2,
        border = BorderStroke(1.dp, MangaTheme.colors.border),
    ) {
        Row(modifier = Modifier.padding(3.dp)) {
            AuthModeTab(
                label = stringResource(R.string.auth_login_tab),
                selected = mode == AuthMode.LOGIN,
                enabled = enabled,
                onClick = { onModeChange(AuthMode.LOGIN) },
                modifier = Modifier.weight(1f),
            )
            AuthModeTab(
                label = stringResource(R.string.auth_register_tab),
                selected = mode == AuthMode.REGISTER,
                enabled = enabled,
                onClick = { onModeChange(AuthMode.REGISTER) },
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun AuthModeTab(
    label: String,
    selected: Boolean,
    enabled: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        onClick = onClick,
        enabled = enabled,
        shape = RoundedCornerShape(7.dp),
        color = if (selected) {
            MaterialTheme.colorScheme.surface
        } else {
            Color.Transparent
        },
        contentColor = if (selected) {
            MaterialTheme.colorScheme.onSurface
        } else {
            MaterialTheme.colorScheme.onSurfaceVariant
        },
        modifier = modifier.heightIn(min = 44.dp),
    ) {
        Box(contentAlignment = Alignment.Center) {
            Text(
                text = label,
                style = MaterialTheme.typography.labelLarge,
                fontWeight = if (selected) FontWeight.Bold else FontWeight.Medium,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(horizontal = 8.dp, vertical = 10.dp),
            )
        }
    }
}

@Composable
private fun AuthArtPanel(
    themeBackgroundRes: Int,
    modifier: Modifier = Modifier,
) {
    Surface(
        shape = RoundedCornerShape(28.dp),
        color = MangaTheme.colors.surface2,
        border = BorderStroke(1.dp, MangaTheme.colors.border),
        modifier = modifier,
    ) {
        Box(modifier = Modifier.fillMaxSize()) {
            AsyncImage(
                model = themeBackgroundRes,
                contentDescription = null,
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize(),
            )
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(
                        Brush.verticalGradient(
                            listOf(
                                Color.Transparent,
                                Color.Black.copy(alpha = 0.22f),
                                MaterialTheme.colorScheme.surface.copy(alpha = 0.88f),
                            ),
                        ),
                    ),
            )
            Surface(
                shape = RoundedCornerShape(14.dp),
                color = MaterialTheme.colorScheme.surface.copy(alpha = 0.96f),
                border = BorderStroke(1.dp, MangaTheme.colors.border),
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .fillMaxWidth()
                    .padding(20.dp),
            ) {
                Column(modifier = Modifier.padding(20.dp)) {
                    Text(
                        text = "«",
                        style = MaterialTheme.typography.headlineLarge,
                        color = MangaTheme.colors.accentText,
                    )
                    Text(
                        text = stringResource(R.string.auth_quote),
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        text = stringResource(R.string.auth_quote_author).uppercase(),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}
