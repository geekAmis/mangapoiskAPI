package ru.mangapoisk.reborn.ui.util

import android.text.Html
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import ru.mangapoisk.reborn.R
import ru.mangapoisk.reborn.data.remote.AppError
import ru.mangapoisk.reborn.data.remote.ErrorKind
import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import java.util.Locale

@Composable
fun AppError.userMessage(): String = stringResource(
    when (kind) {
        ErrorKind.NETWORK -> R.string.error_network
        ErrorKind.TIMEOUT -> R.string.error_timeout
        ErrorKind.UNAUTHORIZED -> R.string.error_unauthorized
        ErrorKind.NOT_FOUND -> R.string.error_not_found
        ErrorKind.RATE_LIMIT -> R.string.error_rate_limited
        ErrorKind.SERVER -> R.string.error_server
        ErrorKind.INVALID_RESPONSE -> R.string.error_invalid_response
        ErrorKind.UNKNOWN -> R.string.error_generic
    },
)

@Composable
fun chapterLabel(volume: String?, number: String?, title: String?): String {
    val chapter = stringResource(
        R.string.detail_chapter,
        number?.takeIf { it.isNotBlank() } ?: title?.takeIf { it.isNotBlank() } ?: "—",
    )
    return if (volume.isNullOrBlank()) {
        chapter
    } else {
        stringResource(R.string.detail_volume, volume) + " · " + chapter
    }
}

@Composable
fun statusLabel(status: String?): String = when (status?.trim()?.lowercase(Locale.ROOT)) {
    "ongoing", "publishing", "в процессе" -> stringResource(R.string.detail_status_ongoing)
    "completed", "finished", "завершён" -> stringResource(R.string.detail_status_completed)
    "hiatus", "on_hold", "приостановлен" -> stringResource(R.string.detail_status_hiatus)
    else -> stringResource(R.string.detail_status_unknown)
}

@Composable
fun contentTypeLabel(contentType: String?): String? = when (
    contentType?.trim()?.lowercase(Locale.ROOT)
) {
    "manga" -> stringResource(R.string.content_type_manga)
    "manhwa", "manhua" -> stringResource(R.string.content_type_manhwa)
    "comic", "comics" -> stringResource(R.string.content_type_comic)
    else -> null
}

fun stripHtml(source: String?): String? {
    if (source.isNullOrBlank()) return null
    val text = Html.fromHtml(source, Html.FROM_HTML_MODE_LEGACY).toString()
    return text.replace(Regex("\\s+"), " ").trim().ifBlank { null }
}

fun formatDate(raw: String?): String? {
    if (raw.isNullOrBlank()) return null
    val instant = runCatching { Instant.parse(raw) }
        .getOrElse {
            runCatching { OffsetDateTime.parse(raw).toInstant() }.getOrNull()
        } ?: return null
    val formatter = DateTimeFormatter.ofLocalizedDate(FormatStyle.MEDIUM)
        .withLocale(Locale.getDefault())
        .withZone(ZoneId.systemDefault())
    return formatter.format(instant)
}

fun formatScore(rating: Double?): String? {
    if (rating == null || rating <= 0.0) return null
    return String.format(Locale.US, "%.1f", rating)
}
