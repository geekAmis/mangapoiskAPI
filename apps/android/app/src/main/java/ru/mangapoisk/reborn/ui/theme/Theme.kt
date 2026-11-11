package ru.mangapoisk.reborn.ui.theme

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import androidx.core.view.WindowCompat
import ru.mangapoisk.reborn.R

/**
 * Theme ids and palettes are the contract from docs/DESIGN_SYSTEM.md.
 * Do not introduce Material You dynamic colour: it would change the brand.
 */
enum class ThemeMode(
    val key: String,
    val titleRes: Int,
    val backgroundRes: Int,
    val serifHeadings: Boolean = false,
) {
    MIDNIGHT("midnight", R.string.settings_theme_midnight, R.drawable.bg_midnight),
    NOIR("noir", R.string.settings_theme_noir, R.drawable.bg_noir, serifHeadings = true),
    ONI("oni", R.string.settings_theme_oni, R.drawable.bg_oni),
    CRIMSON("crimson", R.string.settings_theme_crimson, R.drawable.bg_crimson),
    SUNSET("sunset", R.string.settings_theme_sunset, R.drawable.bg_sunset),
    PAPER("paper", R.string.settings_theme_paper, R.drawable.bg_paper, serifHeadings = true);

    companion object {
        fun fromKey(value: String?): ThemeMode =
            entries.firstOrNull { it.key == value } ?: MIDNIGHT
    }
}

// Kept for call sites written before the design handoff introduced ThemeMode.
typealias ThemeId = ThemeMode

data class ThemePalette(
    val isDark: Boolean,
    val bg: Color,
    val surface: Color,
    val surface2: Color,
    val surface3: Color,
    val text: Color,
    val muted: Color,
    val border: Color,
    val borderStrong: Color,
    val accent: Color,
    val accentText: Color,
    val accent2: Color,
    val onAccent: Color,
    val onAccent2: Color,
    val danger: Color,
    val dangerText: Color,
    val onDanger: Color,
    val success: Color,
    val successText: Color,
) {
    val accentSoft: Color get() = accent.copy(alpha = 0.14f).compositeOver(surface)
    val dangerSoft: Color get() = danger.copy(alpha = 0.14f).compositeOver(surface)
}

fun paletteFor(themeId: ThemeMode): ThemePalette = when (themeId) {
    ThemeMode.MIDNIGHT -> ThemePalette(
        isDark = true,
        bg = Color(0xFF081120),
        surface = Color(0xFF0E1A2C),
        surface2 = Color(0xFF15243A),
        surface3 = Color(0xFF1C2E47),
        text = Color(0xFFEAF3FF),
        muted = Color(0xFFA3B9D4),
        border = Color(0xFF263B57),
        borderStrong = Color(0xFF52708F),
        accent = Color(0xFF7DD3FC),
        accentText = Color(0xFF7DD3FC),
        accent2 = Color(0xFF8AA6FF),
        onAccent = Color(0xFF04121F),
        onAccent2 = Color(0xFF061024),
        danger = Color(0xFFFF7A8A),
        dangerText = Color(0xFFFF9AA6),
        onDanger = Color(0xFF280A0E),
        success = Color(0xFF5BE3B0),
        successText = Color(0xFF7DEBC3),
    )

    ThemeMode.NOIR -> ThemePalette(
        isDark = true,
        bg = Color(0xFF070707),
        surface = Color(0xFF0F0F10),
        surface2 = Color(0xFF171718),
        surface3 = Color(0xFF1F1F20),
        text = Color(0xFFF2EFE5),
        muted = Color(0xFFA8A294),
        border = Color(0xFF2C2A25),
        borderStrong = Color(0xFF6B675E),
        accent = Color(0xFFE4DCC8),
        accentText = Color(0xFFE4DCC8),
        accent2 = Color(0xFFA79E8A),
        onAccent = Color(0xFF141310),
        onAccent2 = Color(0xFF12110E),
        danger = Color(0xFFF07A7A),
        dangerText = Color(0xFFF49A9A),
        onDanger = Color(0xFF240909),
        success = Color(0xFF8FC49A),
        successText = Color(0xFFAED9B6),
    )

    ThemeMode.ONI -> ThemePalette(
        isDark = true,
        bg = Color(0xFF120D0C),
        surface = Color(0xFF1B1413),
        surface2 = Color(0xFF251B19),
        surface3 = Color(0xFF2F2220),
        text = Color(0xFFF5E9DE),
        muted = Color(0xFFBCA89A),
        border = Color(0xFF392724),
        borderStrong = Color(0xFF7C6059),
        accent = Color(0xFFD23A31),
        accentText = Color(0xFFF07A6E),
        accent2 = Color(0xFFF0A35E),
        onAccent = Color(0xFFFFFFFF),
        onAccent2 = Color(0xFF2B1608),
        danger = Color(0xFFFF7C6E),
        dangerText = Color(0xFFFF9C90),
        onDanger = Color(0xFF2A0B08),
        success = Color(0xFF93C489),
        successText = Color(0xFFADD5A5),
    )

    ThemeMode.CRIMSON -> ThemePalette(
        isDark = true,
        bg = Color(0xFF060607),
        surface = Color(0xFF0D0D10),
        surface2 = Color(0xFF151518),
        surface3 = Color(0xFF1D1D21),
        text = Color(0xFFF4F1F2),
        muted = Color(0xFFAAA4AC),
        border = Color(0xFF28252B),
        borderStrong = Color(0xFF675F6D),
        accent = Color(0xFFD91C32),
        accentText = Color(0xFFFF8A98),
        accent2 = Color(0xFFB7A1F2),
        onAccent = Color(0xFFFFFFFF),
        onAccent2 = Color(0xFF1A1229),
        danger = Color(0xFFFF6B7A),
        dangerText = Color(0xFFFF93A0),
        onDanger = Color(0xFF2A0810),
        success = Color(0xFF5FD6A3),
        successText = Color(0xFF86E5BB),
    )

    ThemeMode.SUNSET -> ThemePalette(
        isDark = true,
        bg = Color(0xFF1A1124),
        surface = Color(0xFF241730),
        surface2 = Color(0xFF30203E),
        surface3 = Color(0xFF3C294C),
        text = Color(0xFFFFF1EA),
        muted = Color(0xFFC9B4C6),
        border = Color(0xFF4A3457),
        borderStrong = Color(0xFF7A5D8D),
        accent = Color(0xFFFF8A65),
        accentText = Color(0xFFFFA184),
        accent2 = Color(0xFFFFC46B),
        onAccent = Color(0xFF2A120E),
        onAccent2 = Color(0xFF2B1A07),
        danger = Color(0xFFFF7088),
        dangerText = Color(0xFFFF9AA9),
        onDanger = Color(0xFF2A0B14),
        success = Color(0xFF8FD8A8),
        successText = Color(0xFFB0E6C2),
    )

    ThemeMode.PAPER -> ThemePalette(
        isDark = false,
        bg = Color(0xFFF4F0E7),
        surface = Color(0xFFFCF9F2),
        surface2 = Color(0xFFEBE4D6),
        surface3 = Color(0xFFE0D6C4),
        text = Color(0xFF1D1A16),
        muted = Color(0xFF665F55),
        border = Color(0xFFD5CCBC),
        borderStrong = Color(0xFF8F8472),
        accent = Color(0xFFB83427),
        accentText = Color(0xFFA62E23),
        accent2 = Color(0xFF2E4A68),
        onAccent = Color(0xFFFFF9F3),
        onAccent2 = Color(0xFFF7F2E8),
        danger = Color(0xFFA32520),
        dangerText = Color(0xFF8E1F1B),
        onDanger = Color(0xFFFFF8F4),
        success = Color(0xFF276A4E),
        successText = Color(0xFF1F5A41),
    )
}

data class MangaPoiskColors(
    val accent: Color,
    val accentText: Color,
    val accent2: Color,
    val success: Color,
    val successText: Color,
    val danger: Color,
    val dangerText: Color,
    val border: Color,
    val borderStrong: Color,
    val surface2: Color,
    val surface3: Color,
)

private val LocalMangaPoiskColors = staticCompositionLocalOf {
    val palette = paletteFor(ThemeMode.MIDNIGHT)
    MangaPoiskColors(
        accent = palette.accent,
        accentText = palette.accentText,
        accent2 = palette.accent2,
        success = palette.success,
        successText = palette.successText,
        danger = palette.danger,
        dangerText = palette.dangerText,
        border = palette.border,
        borderStrong = palette.borderStrong,
        surface2 = palette.surface2,
        surface3 = palette.surface3,
    )
}

object MangaTheme {
    val colors: MangaPoiskColors
        @Composable
        @ReadOnlyComposable
        get() = LocalMangaPoiskColors.current
}

private fun ThemePalette.toColorScheme(): ColorScheme {
    val base = if (isDark) darkColorScheme() else lightColorScheme()
    return base.copy(
        primary = accent,
        onPrimary = onAccent,
        primaryContainer = accentSoft,
        onPrimaryContainer = accentText,
        inversePrimary = accent2,
        secondary = accent2,
        onSecondary = onAccent2,
        secondaryContainer = accentSoft,
        onSecondaryContainer = accentText,
        tertiary = accent2,
        onTertiary = onAccent2,
        tertiaryContainer = surface3,
        onTertiaryContainer = text,
        background = bg,
        onBackground = text,
        surface = surface,
        onSurface = text,
        surfaceVariant = surface2,
        onSurfaceVariant = muted,
        surfaceTint = Color.Transparent,
        inverseSurface = text,
        inverseOnSurface = surface,
        error = danger,
        onError = onDanger,
        errorContainer = dangerSoft,
        onErrorContainer = dangerText,
        outline = borderStrong,
        outlineVariant = border,
        scrim = Color.Black,
    )
}

private fun typographyFor(serifHeadings: Boolean): Typography {
    val displayFamily = if (serifHeadings) FontFamily.Serif else FontFamily.SansSerif
    val base = Typography()
    return base.copy(
        displayLarge = base.displayLarge.copy(
            fontFamily = displayFamily,
            fontWeight = FontWeight.Bold,
            fontSize = 40.sp,
            lineHeight = 42.sp,
            letterSpacing = (-0.035).em,
        ),
        displayMedium = base.displayMedium.copy(
            fontFamily = displayFamily,
            fontWeight = FontWeight.Bold,
            fontSize = 34.sp,
            lineHeight = 36.sp,
            letterSpacing = (-0.03).em,
        ),
        displaySmall = base.displaySmall.copy(
            fontFamily = displayFamily,
            fontWeight = FontWeight.Bold,
            fontSize = 30.sp,
            lineHeight = 33.sp,
            letterSpacing = (-0.025).em,
        ),
        headlineLarge = base.headlineLarge.copy(
            fontFamily = displayFamily,
            fontWeight = FontWeight.Bold,
            fontSize = 28.sp,
            lineHeight = 32.sp,
            letterSpacing = (-0.02).em,
        ),
        headlineMedium = base.headlineMedium.copy(
            fontFamily = displayFamily,
            fontWeight = FontWeight.Bold,
            fontSize = 24.sp,
            lineHeight = 28.sp,
            letterSpacing = (-0.02).em,
        ),
        headlineSmall = base.headlineSmall.copy(
            fontFamily = displayFamily,
            fontWeight = FontWeight.SemiBold,
            fontSize = 20.sp,
            lineHeight = 25.sp,
        ),
        titleLarge = base.titleLarge.copy(
            fontFamily = displayFamily,
            fontWeight = FontWeight.Bold,
            fontSize = 20.sp,
            lineHeight = 26.sp,
        ),
        titleMedium = base.titleMedium.copy(
            fontWeight = FontWeight.SemiBold,
            fontSize = 17.sp,
            lineHeight = 23.sp,
        ),
        titleSmall = base.titleSmall.copy(
            fontWeight = FontWeight.SemiBold,
            fontSize = 15.sp,
            lineHeight = 20.sp,
        ),
        bodyLarge = base.bodyLarge.copy(fontSize = 16.sp, lineHeight = 26.sp),
        bodyMedium = base.bodyMedium.copy(fontSize = 15.5.sp, lineHeight = 24.sp),
        bodySmall = base.bodySmall.copy(fontSize = 13.5.sp, lineHeight = 20.sp),
        labelLarge = base.labelLarge.copy(
            fontWeight = FontWeight.SemiBold,
            fontSize = 14.sp,
            lineHeight = 20.sp,
        ),
        labelMedium = base.labelMedium.copy(
            fontWeight = FontWeight.SemiBold,
            fontSize = 12.sp,
            lineHeight = 16.sp,
        ),
        labelSmall = base.labelSmall.copy(
            fontWeight = FontWeight.Medium,
            fontSize = 11.sp,
            lineHeight = 14.sp,
        ),
    )
}

private val AppShapes = Shapes(
    extraSmall = RoundedCornerShape(6.dp),
    small = RoundedCornerShape(8.dp),
    medium = RoundedCornerShape(14.dp),
    large = RoundedCornerShape(22.dp),
    extraLarge = RoundedCornerShape(28.dp),
)

@Composable
fun MangaPoiskTheme(themeKey: String, content: @Composable () -> Unit) {
    val theme = ThemeMode.fromKey(themeKey)
    val palette = paletteFor(theme)
    val view = LocalView.current
    val colors = MangaPoiskColors(
        accent = palette.accent,
        accentText = palette.accentText,
        accent2 = palette.accent2,
        success = palette.success,
        successText = palette.successText,
        danger = palette.danger,
        dangerText = palette.dangerText,
        border = palette.border,
        borderStrong = palette.borderStrong,
        surface2 = palette.surface2,
        surface3 = palette.surface3,
    )

    if (!view.isInEditMode) {
        SideEffect {
            val activity = view.context.findActivity() ?: return@SideEffect
            val window = activity.window
            window.statusBarColor = Color.Transparent.toArgb()
            window.navigationBarColor = Color.Transparent.toArgb()
            WindowCompat.getInsetsController(window, view).apply {
                isAppearanceLightStatusBars = !palette.isDark
                isAppearanceLightNavigationBars = !palette.isDark
            }
        }
    }

    CompositionLocalProvider(LocalMangaPoiskColors provides colors) {
        MaterialTheme(
            colorScheme = palette.toColorScheme(),
            typography = typographyFor(theme.serifHeadings),
            shapes = AppShapes,
            content = content,
        )
    }
}

private tailrec fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}
