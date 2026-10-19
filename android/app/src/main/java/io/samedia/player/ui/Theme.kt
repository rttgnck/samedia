package io.samedia.player.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// The TV app's colours
object Palette {
    val bg = Color(0xFF07090D)
    val surface = Color(0xFF11151C)
    val surface2 = Color(0xFF1A1F29)
    val text = Color(0xFFF2F4F8)
    val dim = Color(0x9EF2F4F8)
    val faint = Color(0x61F2F4F8)
    val accent = Color(0xFF5B8CFF)
    val accent2 = Color(0xFF8F6BFF)
    val ok = Color(0xFF3ECF8E)
}

private val colors = darkColorScheme(
    primary = Palette.accent,
    onPrimary = Color.White,
    primaryContainer = Color(0xFF223A73),
    onPrimaryContainer = Palette.text,
    secondary = Palette.accent2,
    secondaryContainer = Palette.surface2,
    onSecondaryContainer = Palette.text,
    background = Palette.bg,
    onBackground = Palette.text,
    surface = Palette.bg,
    onSurface = Palette.text,
    surfaceVariant = Palette.surface2,
    onSurfaceVariant = Palette.dim,
    surfaceContainerLowest = Palette.bg,
    surfaceContainerLow = Palette.surface,
    surfaceContainer = Palette.surface,
    surfaceContainerHigh = Palette.surface2,
    surfaceContainerHighest = Color(0xFF232937),
    outline = Color(0x33FFFFFF),
    outlineVariant = Color(0x14FFFFFF),
)

@Composable
fun SamediaTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = colors, content = content)
}
