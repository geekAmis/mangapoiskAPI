package ru.mangapoisk.reborn.ui.auth

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import ru.mangapoisk.reborn.R
import ru.mangapoisk.reborn.data.remote.AppError
import ru.mangapoisk.reborn.data.remote.ErrorKind
import ru.mangapoisk.reborn.data.remote.toAppError
import ru.mangapoisk.reborn.data.repo.AuthRepository
import ru.mangapoisk.reborn.di.AppContainer

enum class AuthMode { LOGIN, REGISTER }

sealed interface AuthEvent {
    data object Authenticated : AuthEvent
}

data class AuthUiState(
    val mode: AuthMode = AuthMode.LOGIN,
    val email: String = "",
    val password: String = "",
    val displayName: String = "",
    val isLoading: Boolean = false,
    val formErrorRes: Int? = null,
    val appError: AppError? = null,
)

class AuthViewModel(
    initialRegister: Boolean,
    private val authRepository: AuthRepository,
) : ViewModel() {

    private val _state = MutableStateFlow(
        AuthUiState(mode = if (initialRegister) AuthMode.REGISTER else AuthMode.LOGIN),
    )
    val state = _state.asStateFlow()
    private val _events = MutableSharedFlow<AuthEvent>(extraBufferCapacity = 1)
    val events = _events.asSharedFlow()

    fun setMode(mode: AuthMode) {
        _state.update {
            it.copy(mode = mode, formErrorRes = null, appError = null)
        }
    }

    fun setEmail(value: String) {
        _state.update { it.copy(email = value, formErrorRes = null) }
    }

    fun setPassword(value: String) {
        _state.update { it.copy(password = value, formErrorRes = null) }
    }

    fun setDisplayName(value: String) {
        _state.update { it.copy(displayName = value, formErrorRes = null) }
    }

    fun submit() {
        val snapshot = _state.value
        if (snapshot.isLoading) return
        val validationError = validate(snapshot)
        if (validationError != null) {
            _state.update { it.copy(formErrorRes = validationError, appError = null) }
            return
        }
        _state.update { it.copy(isLoading = true, formErrorRes = null, appError = null) }
        viewModelScope.launch {
            val result = when (snapshot.mode) {
                AuthMode.LOGIN -> authRepository.login(snapshot.email, snapshot.password)
                AuthMode.REGISTER -> authRepository.register(
                    email = snapshot.email,
                    password = snapshot.password,
                    displayName = snapshot.displayName,
                )
            }
            result.fold(
                onSuccess = {
                    _state.update { it.copy(isLoading = false) }
                    _events.tryEmit(AuthEvent.Authenticated)
                },
                onFailure = { throwable ->
                    val error = throwable.toAppError()
                    val formError = when {
                        error.kind == ErrorKind.NETWORK ||
                            error.kind == ErrorKind.TIMEOUT ||
                            error.kind == ErrorKind.SERVER -> null
                        snapshot.mode == AuthMode.LOGIN -> R.string.auth_error_login
                        else -> R.string.auth_error_register
                    }
                    _state.update {
                        it.copy(
                            isLoading = false,
                            formErrorRes = formError,
                            appError = error,
                        )
                    }
                },
            )
        }
    }

    private fun validate(state: AuthUiState): Int? {
        if (!EMAIL_REGEX.matches(state.email.trim())) {
            return R.string.auth_email_invalid
        }
        if (state.password.length < 8) {
            return R.string.auth_password_short
        }
        if (state.mode == AuthMode.REGISTER && state.displayName.isBlank()) {
            return R.string.auth_name_short
        }
        return null
    }

    companion object {
        private val EMAIL_REGEX = Regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$")

        fun factory(container: AppContainer, initialRegister: Boolean) = viewModelFactory {
            initializer {
                AuthViewModel(
                    initialRegister = initialRegister,
                    authRepository = container.authRepository,
                )
            }
        }
    }
}
