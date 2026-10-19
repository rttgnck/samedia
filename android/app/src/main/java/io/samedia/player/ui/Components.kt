package io.samedia.player.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Devices
import androidx.compose.material.icons.filled.PhoneAndroid
import androidx.compose.material.icons.filled.TabletMac
import androidx.compose.material.icons.filled.Tv
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil3.compose.AsyncImage
import io.samedia.player.core.AppModel
import io.samedia.player.core.MediaItem
import io.samedia.player.core.Profile
import io.samedia.player.core.RemotePlayer
import kotlinx.coroutines.launch

val LocalModel = staticCompositionLocalOf<AppModel> { error("no model") }

/** Where a card leads. */
sealed interface Route {
    data class Item(val item: MediaItem) : Route
    data class Show(val id: String) : Route
    data class Collection(val id: String) : Route
}

fun routeFor(item: MediaItem): Route = when (item.kind) {
    "show" -> Route.Show(item.id)
    "collection" -> Route.Collection(item.id)
    else -> Route.Item(item)
}

class Navigator(val push: (Route) -> Unit)

val LocalNavigator = staticCompositionLocalOf { Navigator {} }

val RemotePlayer.symbol: ImageVector
    get() = when (kind) {
        "tv" -> Icons.Filled.Tv
        "android" -> Icons.Filled.PhoneAndroid
        "ios" -> Icons.Filled.TabletMac
        else -> Icons.Filled.Devices
    }

fun parseColor(hex: String?, fallback: Color = Palette.accent): Color =
    runCatching { Color(android.graphics.Color.parseColor(hex)) }.getOrDefault(fallback)

@Composable
fun ProgressBar(value: Double, modifier: Modifier = Modifier) {
    Box(modifier.clip(RoundedCornerShape(50)).background(Color.White.copy(alpha = 0.25f))) {
        Box(Modifier.fillMaxWidth(value.toFloat().coerceIn(0f, 1f)).height(4.dp).background(Palette.accent))
    }
}

/** A poster with its title as the stand-in until (or unless) there is art. */
@Composable
fun Poster(item: MediaItem, modifier: Modifier = Modifier, width: Int = 342, showProgress: Boolean = true, onClick: (() -> Unit)? = null) {
    val model = LocalModel.current
    val nav = LocalNavigator.current
    Box(
        modifier
            .aspectRatio(2f / 3f)
            .clip(RoundedCornerShape(10.dp))
            .background(Brush.verticalGradient(listOf(Color(0xFF333333), Color(0xFF1A1A1A))))
            .clickable { onClick?.invoke() ?: nav.push(routeFor(item)) },
    ) {
        Text(item.title, color = Palette.dim, textAlign = TextAlign.Center, fontSize = 13.sp,
            modifier = Modifier.align(Alignment.Center).padding(10.dp))
        AsyncImage(model.api?.art(item.poster, width), null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
        val at = item.resumeAt
        val d = item.duration
        if (showProgress && at != null && d != null && d > 0) {
            ProgressBar(at / d, Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(8.dp))
        }
        if (item.watched) {
            Icon(Icons.Filled.CheckCircle, "Watched", tint = Palette.ok,
                modifier = Modifier.align(Alignment.TopEnd).padding(6.dp).size(22.dp).background(Color.Black, CircleShape))
        } else if ((item.unwatched ?: 0) > 0 && item.kind != "movie") {
            Text("${item.unwatched}", color = Color.White, fontSize = 11.sp, fontWeight = FontWeight.Bold,
                modifier = Modifier.align(Alignment.TopEnd).padding(6.dp)
                    .background(Palette.accent, RoundedCornerShape(50)).padding(horizontal = 7.dp, vertical = 2.dp))
        }
    }
}

/** A wide still with progress, for "Continue Watching". */
@Composable
fun WideCard(item: MediaItem, modifier: Modifier = Modifier) {
    val model = LocalModel.current
    val nav = LocalNavigator.current
    Column(modifier.clickable { nav.push(routeFor(item)) }, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Box(
            Modifier.fillMaxWidth().aspectRatio(16f / 9f).clip(RoundedCornerShape(10.dp)).background(Palette.surface2),
        ) {
            Text(item.showTitle ?: item.title, color = Palette.faint, textAlign = TextAlign.Center, fontSize = 13.sp,
                modifier = Modifier.align(Alignment.Center).padding(10.dp))
            AsyncImage(model.api?.art(item.thumb ?: item.backdrop ?: item.poster, 640), null,
                contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            val at = item.resumeAt
            val d = item.duration
            if (at != null && d != null && d > 0) {
                ProgressBar(at / d, Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(8.dp))
            }
        }
        Text(item.showTitle ?: item.title, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Text(item.episodeLabel?.let { "$it · ${item.title}" } ?: Format.remaining(item), color = Palette.dim,
            style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

private object Format {
    fun remaining(item: MediaItem): String {
        val at = item.resumeAt ?: return item.year?.toString() ?: ""
        val d = item.duration ?: return ""
        return io.samedia.player.core.Format.runtime(d - at)?.let { "$it left" } ?: ""
    }
}

@Composable
fun Avatar(profile: Profile, size: Dp, modifier: Modifier = Modifier) {
    val model = LocalModel.current
    val url = model.avatarUrl(profile)
    Box(
        modifier.size(size).clip(CircleShape).background(parseColor(profile.color)),
        contentAlignment = Alignment.Center,
    ) {
        if (url != null) {
            AsyncImage(url, profile.name, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
        } else {
            Text(profile.name.take(1).uppercase(), color = Color.White, fontWeight = FontWeight.Bold,
                fontSize = (size.value * 0.42f).sp)
        }
    }
}

@Composable
fun Loading(modifier: Modifier = Modifier) {
    Box(modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
}

@Composable
fun ErrorBox(message: String, retry: () -> Unit) {
    Column(
        Modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(message, color = Palette.dim, textAlign = TextAlign.Center)
        Button(onClick = retry, modifier = Modifier.padding(top = 16.dp)) { Text("Try again") }
    }
}

/** "Play on…": start a title on another screen without playing it here. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlayOnSheet(item: MediaItem, position: Double?, onDismiss: () -> Unit) {
    val model = LocalModel.current
    val scope = rememberCoroutineScope()
    var players by remember { mutableStateOf<List<RemotePlayer>?>(null) }
    LaunchedEffect(Unit) { players = model.players() }
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = Palette.surface) {
        Column(Modifier.navigationBarsPadding().padding(bottom = 16.dp)) {
            Text("Play ${item.title} on", style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp))
            val list = players
            when {
                list == null -> Box(Modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
                list.isEmpty() -> Text("No other Samedia screens are on right now.", color = Palette.dim,
                    modifier = Modifier.padding(24.dp))
                else -> list.forEach { p ->
                    ListItem(
                        headlineContent = { Text(p.name) },
                        supportingContent = {
                            Text(p.nowPlaying?.let { (if (it.playing) "Playing " else "Paused · ") + (it.title ?: "") } ?: "Idle",
                                maxLines = 1, overflow = TextOverflow.Ellipsis)
                        },
                        leadingContent = { Icon(p.symbol, null) },
                        colors = ListItemDefaults.colors(containerColor = Color.Transparent),
                        modifier = Modifier.clickable {
                            scope.launch { if (model.playOn(p, item, position)) onDismiss() }
                        },
                    )
                }
            }
        }
    }
}
