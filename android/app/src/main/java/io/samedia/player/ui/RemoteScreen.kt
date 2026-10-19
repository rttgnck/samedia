package io.samedia.player.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.VolumeDown
import androidx.compose.material.icons.automirrored.filled.VolumeOff
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material.icons.filled.Forward30
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Replay10
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.TvOff
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import io.samedia.player.core.AppModel
import io.samedia.player.core.Format
import io.samedia.player.core.MediaItem
import io.samedia.player.core.RemotePlayer
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** Lets the phone's volume buttons reach the screen whose remote is open. */
object RemoteKeys {
    var volumeTarget: RemotePlayer? = null

    fun volume(model: AppModel, target: RemotePlayer, key: String) =
        model.send(target, buildJsonObject { put("action", "volume"); put("key", key) })
}

private fun cmd(action: String, block: kotlinx.serialization.json.JsonObjectBuilder.() -> Unit = {}): JsonObject =
    buildJsonObject { put("action", action); block() }

/** The other screens and what they play, with controls: the app as a remote. */
@Composable
fun RemoteScreen() {
    val model = LocalModel.current
    var players by remember { mutableStateOf<List<RemotePlayer>>(emptyList()) }
    var loaded by remember { mutableStateOf(false) }
    var fetchedAt by remember { mutableLongStateOf(0L) }
    var selectedId by rememberSaveable { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    suspend fun refresh() {
        players = model.players()
        fetchedAt = System.currentTimeMillis()
        loaded = true
    }
    LaunchedEffect(model.profile?.id) {
        while (true) {
            refresh()
            delay(2000)
        }
    }

    val selected = players.firstOrNull { it.id == selectedId }
        ?: players.firstOrNull { it.nowPlaying != null } ?: players.firstOrNull { it.kind == "tv" } ?: players.firstOrNull()
    DisposableEffect(selected) {
        RemoteKeys.volumeTarget = selected?.takeIf { "volume" in it.can }
        onDispose { RemoteKeys.volumeTarget = null }
    }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
        ScreenTitle("Remote")
        if (loaded && players.isEmpty()) {
            Column(
                Modifier.fillMaxWidth().padding(top = 80.dp, start = 32.dp, end = 32.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Icon(Icons.Filled.TvOff, null, Modifier.size(56.dp), tint = Palette.faint)
                Text("No other screens are on", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 12.dp))
                Text("Open Samedia on a TV, phone or tablet and it shows up here.", color = Palette.dim,
                    textAlign = TextAlign.Center, modifier = Modifier.padding(top = 6.dp))
            }
        }
        if (players.size > 1) {
            Row(
                Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                players.forEach { p ->
                    FilterChip(
                        selected = p.id == selected?.id,
                        onClick = { selectedId = p.id },
                        leadingIcon = { Icon(p.symbol, null, Modifier.size(18.dp)) },
                        label = { Text(p.name + if (p.nowPlaying?.playing == true) "  ▶" else "") },
                        colors = FilterChipDefaults.filterChipColors(selectedContainerColor = Palette.accent.copy(alpha = 0.25f)),
                    )
                }
            }
        }
        selected?.let { p ->
            RemotePanel(p, fetchedAt) { action ->
                model.send(p, action)
                scope.launch {
                    delay(350)
                    refresh()
                }
            }
        }
    }
}

@Composable
private fun RemotePanel(player: RemotePlayer, fetchedAt: Long, send: (JsonObject) -> Unit) {
    val model = LocalModel.current
    val now = player.nowPlaying
    val art = remember { mutableStateMapOf<String, MediaItem>() }
    LaunchedEffect(now?.itemId) {
        val id = now?.itemId ?: return@LaunchedEffect
        if (now.kind == "track") return@LaunchedEffect          // music says its own artwork
        if (id !in art) runCatching { model.api?.item(id)?.item }.getOrNull()?.let { art[id] = it }
    }
    val nav = LocalNavigator.current
    val music = now?.kind == "track"
    // Move the clock along between refreshes
    var tick by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(now?.playing) {
        while (now?.playing == true) {
            delay(500)
            tick = System.currentTimeMillis()
        }
    }

    Column(
        Modifier.padding(16.dp).fillMaxWidth().clip(RoundedCornerShape(22.dp)).background(Palette.surface).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(player.symbol, null, tint = Palette.accent)
            Text(player.name, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold,
                modifier = Modifier.padding(start = 10.dp).weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (player.kind == "tv") {
                TextButton(onClick = { nav.push(Route.Lock(player)) }) { Icon(Icons.Filled.Lock, null, Modifier.size(18.dp)); Text(" Lock…") }
            }
            if (now != null) {
                IconButton(onClick = { send(cmd("stop")) }) { Icon(Icons.Filled.Stop, "Stop", tint = Palette.dim) }
            }
        }

        if (now != null) {
            val item = art[now.itemId]
            Box(Modifier.fillMaxWidth().aspectRatio(if (music) 1.6f else 16f / 9f).clip(RoundedCornerShape(14.dp)).background(Palette.surface2)) {
                AsyncImage(model.api?.art(if (music) now.art else item?.scene ?: item?.thumb ?: item?.backdrop ?: item?.poster, 960), null,
                    contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
                Box(Modifier.fillMaxSize().background(Brush.verticalGradient(0.55f to Color.Transparent, 1f to Color.Black.copy(alpha = 0.75f))))
                Text(now.title ?: item?.fullTitle ?: "", color = Color.White, style = MaterialTheme.typography.titleMedium,
                    maxLines = 2, overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.align(Alignment.BottomStart).padding(14.dp))
            }

            val duration = now.duration ?: 0.0
            if (duration > 0) {
                var scrub by remember { mutableStateOf<Float?>(null) }
                val moved = if (now.playing) (tick - fetchedAt).coerceAtLeast(0) / 1000.0 else 0.0
                val at = ((now.position ?: 0.0) + moved).coerceAtMost(duration)
                val shown = scrub?.toDouble() ?: at
                Column {
                    Slider(
                        value = shown.toFloat(), valueRange = 0f..duration.toFloat(),
                        onValueChange = { scrub = it },
                        onValueChangeFinished = { scrub?.let { to -> send(cmd("seek") { put("position", to.toDouble()) }) }; scrub = null },
                        colors = SliderDefaults.colors(thumbColor = Color.White, activeTrackColor = Palette.accent),
                    )
                    Row {
                        Text(Format.clock(shown), color = Palette.dim, style = MaterialTheme.typography.labelMedium)
                        Spacer(Modifier.weight(1f))
                        Text("-" + Format.clock(duration - shown), color = Palette.dim, style = MaterialTheme.typography.labelMedium)
                    }
                }
            }

            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly, verticalAlignment = Alignment.CenterVertically) {
                if (music) RoundKey(Icons.Filled.SkipPrevious, "Previous", 56) { send(cmd("previous")) }
                else RoundKey(Icons.Filled.Replay10, "Back 10 seconds", 56) { send(cmd("skip") { put("delta", -10) }) }
                FilledIconButton(
                    onClick = { send(cmd("toggle")) }, modifier = Modifier.size(76.dp),
                    colors = IconButtonDefaults.filledIconButtonColors(containerColor = Palette.accent),
                ) {
                    Icon(if (now.playing) Icons.Filled.Pause else Icons.Filled.PlayArrow, if (now.playing) "Pause" else "Play",
                        Modifier.size(40.dp), tint = Color.White)
                }
                if (music) RoundKey(Icons.Filled.SkipNext, "Next", 56) { send(cmd("next")) }
                else RoundKey(Icons.Filled.Forward30, "Forward 30 seconds", 56) { send(cmd("skip") { put("delta", 30) }) }
            }
        } else {
            Text("Nothing playing. Choose a title and use Play on… to start it here.", color = Palette.dim)
        }

        if ("keys" in player.can) DPad(send)
        if ("volume" in player.can) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                RoundKey(Icons.AutoMirrored.Filled.VolumeDown, "Volume down", 52) { send(cmd("volume") { put("key", "down") }) }
                RoundKey(Icons.AutoMirrored.Filled.VolumeOff, "Mute", 52) { send(cmd("volume") { put("key", "mute") }) }
                RoundKey(Icons.AutoMirrored.Filled.VolumeUp, "Volume up", 52) { send(cmd("volume") { put("key", "up") }) }
            }
        }
    }
}

@Composable
private fun RoundKey(icon: ImageVector, label: String, size: Int, onClick: () -> Unit) {
    val haptics = LocalHapticFeedback.current
    Box(
        Modifier.size(size.dp).clip(CircleShape).background(Palette.surface2)
            .clickable { haptics.performHapticFeedback(HapticFeedbackType.TextHandleMove); onClick() },
        contentAlignment = Alignment.Center,
    ) { Icon(icon, label, tint = Palette.text, modifier = Modifier.size((size * 0.5f).dp)) }
}

/** Arrows, OK and back for the screen's own menus. */
@Composable
private fun DPad(send: (JsonObject) -> Unit) {
    val haptics = LocalHapticFeedback.current
    fun key(k: String) {
        haptics.performHapticFeedback(HapticFeedbackType.TextHandleMove)
        send(cmd("key") { put("key", k) })
    }
    Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
        Box(Modifier.size(232.dp).clip(CircleShape).background(Palette.surface2)) {
            val arrow = Modifier.size(76.dp)
            Box(arrow.align(Alignment.TopCenter).clip(CircleShape).clickable { key("up") }, contentAlignment = Alignment.Center) {
                Icon(Icons.Filled.KeyboardArrowUp, "Up", Modifier.size(40.dp))
            }
            Box(arrow.align(Alignment.BottomCenter).clip(CircleShape).clickable { key("down") }, contentAlignment = Alignment.Center) {
                Icon(Icons.Filled.KeyboardArrowDown, "Down", Modifier.size(40.dp))
            }
            Box(arrow.align(Alignment.CenterStart).clip(CircleShape).clickable { key("left") }, contentAlignment = Alignment.Center) {
                Icon(Icons.AutoMirrored.Filled.KeyboardArrowLeft, "Left", Modifier.size(40.dp))
            }
            Box(arrow.align(Alignment.CenterEnd).clip(CircleShape).clickable { key("right") }, contentAlignment = Alignment.Center) {
                Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, "Right", Modifier.size(40.dp))
            }
            Box(
                Modifier.size(84.dp).align(Alignment.Center).clip(CircleShape).background(Palette.accent).clickable { key("enter") },
                contentAlignment = Alignment.Center,
            ) { Text("OK", color = Color.White, fontWeight = FontWeight.Bold) }
        }
        Spacer(Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            PillKey(Icons.AutoMirrored.Filled.ArrowBack, "Back") { key("back") }
            PillKey(Icons.Filled.Home, "Home") { key("home") }
        }
    }
}

@Composable
private fun PillKey(icon: ImageVector, label: String, onClick: () -> Unit) {
    Row(
        Modifier.clip(RoundedCornerShape(50)).background(Palette.surface2).clickable(onClick = onClick)
            .padding(horizontal = 22.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, null, Modifier.size(20.dp))
        Spacer(Modifier.width(8.dp))
        Text(label)
    }
}
