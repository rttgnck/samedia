package io.samedia.player.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Cast
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Replay
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material3.Button
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import io.samedia.player.core.Format
import io.samedia.player.core.ItemDetail
import io.samedia.player.core.MediaItem
import io.samedia.player.core.ShowDetail

/** The wide picture at the top of a details screen, with a back button over it: a title card (a
 *  scene other than the poster, with the title's logo faded in) when there is one. */
@Composable
private fun Header(art: String?, onBack: () -> Unit, logo: String? = null) {
    val model = LocalModel.current
    Box(Modifier.fillMaxWidth().aspectRatio(16f / 9f).background(Palette.surface)) {
        AsyncImage(model.api?.art(art, 1280), null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
        Box(Modifier.fillMaxSize().background(Brush.verticalGradient(0.5f to Color.Transparent, 1f to Palette.bg)))
        if (logo != null) AsyncImage(model.api?.art(logo, 640), null, contentScale = ContentScale.Fit, alpha = 0.85f,
            modifier = Modifier.align(Alignment.BottomStart).padding(start = 20.dp, bottom = 18.dp).fillMaxWidth(0.5f).aspectRatio(3f))
        IconButton(
            onClick = onBack,
            modifier = Modifier.statusBarsPadding().padding(8.dp).background(Color.Black.copy(alpha = 0.45f), CircleShape),
        ) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Color.White) }
    }
}

@Composable
private fun WatchedButton(watched: Boolean, onToggle: () -> Unit) {
    IconButton(onClick = onToggle) {
        if (watched) Icon(Icons.Filled.CheckCircle, "Watched", tint = Palette.ok)
        else Icon(Icons.Outlined.CheckCircle, "Mark watched", tint = Palette.dim)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun DetailScreen(start: MediaItem, onBack: () -> Unit) {
    val model = LocalModel.current
    val context = LocalContext.current
    var detail by remember { mutableStateOf<ItemDetail?>(null) }
    var playOn by remember { mutableStateOf(false) }
    LaunchedEffect(start.id, model.refreshToken) {
        detail = runCatching { model.api?.item(start.id) }.getOrNull() ?: detail
    }
    val item = detail?.item ?: start
    var watched by remember(item) { mutableStateOf(item.watched) }

    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 32.dp)) {
        item { Header(item.scene ?: item.backdrop ?: item.thumb, onBack, item.logo) }
        item {
            Column(Modifier.padding(horizontal = 20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                item.showTitle?.let {
                    Text("$it  ·  ${item.episodeLabel ?: ""}", color = Palette.accent, style = MaterialTheme.typography.labelLarge)
                }
                Text(item.title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                Text(Format.meta(item), color = Palette.dim, style = MaterialTheme.typography.bodyMedium)
                Format.progress(item)?.let { Text(it, color = Palette.accent, style = MaterialTheme.typography.bodyMedium) }

                FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    val resume = item.resumeAt
                    Button(onClick = { model.play(context, item, resume) }) {
                        Icon(Icons.Filled.PlayArrow, null)
                        Text(if (resume != null) "Resume" else "Play", Modifier.padding(start = 6.dp))
                    }
                    if (resume != null) {
                        FilledTonalButton(onClick = { model.play(context, item, null) }) {
                            Icon(Icons.Filled.Replay, null)
                            Text("Start over", Modifier.padding(start = 6.dp))
                        }
                    }
                    if (model.hasRemote) {
                        FilledTonalButton(onClick = { playOn = true }) {
                            Icon(Icons.Filled.Cast, null)
                            Text("Play on…", Modifier.padding(start = 6.dp))
                        }
                    }
                    WatchedButton(watched) {
                        watched = !watched
                        model.setWatched(item, watched)
                    }
                }

                detail?.extras?.tagline?.takeIf { it.isNotBlank() }?.let {
                    Text(it, fontStyle = FontStyle.Italic, color = Palette.dim)
                }
                item.plot?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
                detail?.extras?.director?.let { Text("Directed by $it", color = Palette.dim, style = MaterialTheme.typography.bodySmall) }
                detail?.extras?.cast?.takeIf { it.isNotEmpty() }?.let { cast ->
                    Text("With " + cast.take(8).joinToString(", ") { it.name }, color = Palette.dim, style = MaterialTheme.typography.bodySmall)
                }
                detail?.extras?.next?.let { next ->
                    SectionTitle("Next episode")
                    EpisodeRow(next)
                }
            }
        }
    }
    if (playOn) PlayOnSheet(item, item.resumeAt) { playOn = false }
}

@Composable
fun EpisodeRow(item: MediaItem) {
    val model = LocalModel.current
    val nav = LocalNavigator.current
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).clickable { nav.push(Route.Item(item)) }.padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.width(136.dp).aspectRatio(16f / 9f).clip(RoundedCornerShape(8.dp)).background(Palette.surface2)) {
            AsyncImage(model.api?.art(item.thumb ?: item.backdrop, 400), null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            val at = item.resumeAt
            val d = item.duration
            if (at != null && d != null && d > 0) ProgressBar(at / d, Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(6.dp))
            if (item.watched) Icon(Icons.Filled.CheckCircle, null, tint = Palette.ok,
                modifier = Modifier.align(Alignment.TopEnd).padding(4.dp).background(Color.Black, CircleShape))
        }
        Column(Modifier.weight(1f).padding(start = 12.dp)) {
            item.episodeLabel?.let { Text(it, color = Palette.dim, style = MaterialTheme.typography.labelMedium) }
            Text(item.title, style = MaterialTheme.typography.titleSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(Format.progress(item) ?: Format.runtime(item.duration) ?: "", color = Palette.faint, style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
fun ShowScreen(id: String, onBack: () -> Unit) {
    val model = LocalModel.current
    val context = LocalContext.current
    var detail by remember { mutableStateOf<ShowDetail?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var season by rememberSaveable(id) { mutableStateOf<Int?>(null) }
    var playOn by remember { mutableStateOf<MediaItem?>(null) }
    LaunchedEffect(id, model.refreshToken) {
        try {
            detail = model.api?.show(id)
        } catch (e: Exception) {
            if (detail == null) error = e.message
        }
    }
    val d = detail ?: run {
        if (error != null) ErrorBox(error ?: "") { onBack() } else Loading()
        return
    }
    val show = d.show
    val seasons = d.extras.seasons
    val current = season ?: d.extras.nextUp?.season ?: seasons.firstOrNull()?.season
    var watched by remember(show) { mutableStateOf(show.watched) }

    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 32.dp)) {
        item { Header(show.scene ?: show.backdrop, onBack, show.logo) }
        item {
            Column(Modifier.padding(horizontal = 20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(show.title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                Text(Format.meta(show), color = Palette.dim)
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                    d.extras.nextUp?.let { next ->
                        Button(onClick = { model.play(context, next, next.resumeAt) }) {
                            Icon(Icons.Filled.PlayArrow, null)
                            Text(next.episodeLabel ?: "Play", Modifier.padding(start = 6.dp))
                        }
                        if (model.hasRemote) {
                            FilledTonalButton(onClick = { playOn = next }) {
                                Icon(Icons.Filled.Cast, null)
                                Text("Play on…", Modifier.padding(start = 6.dp))
                            }
                        }
                    }
                    WatchedButton(watched) {
                        watched = !watched
                        model.setWatched(show, watched)
                    }
                }
                show.plot?.let { Text(it, style = MaterialTheme.typography.bodyMedium, maxLines = 6, overflow = TextOverflow.Ellipsis) }
                if (seasons.size > 1) {
                    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        seasons.forEach { s ->
                            FilterChip(
                                selected = s.season == current, onClick = { season = s.season },
                                label = { Text(if (s.season == 0) "Specials" else "Season ${s.season}") },
                                colors = FilterChipDefaults.filterChipColors(selectedContainerColor = Palette.accent.copy(alpha = 0.25f)),
                            )
                        }
                    }
                }
            }
        }
        items(d.extras.episodes.filter { it.season == current }, key = { it.id }) {
            Box(Modifier.padding(horizontal = 16.dp)) { EpisodeRow(it) }
        }
    }
    playOn?.let { item -> PlayOnSheet(item, item.resumeAt) { playOn = null } }
}

@Composable
fun CollectionScreen(id: String, onBack: () -> Unit) {
    val model = LocalModel.current
    var data by remember { mutableStateOf<Pair<MediaItem, List<MediaItem>>?>(null) }
    LaunchedEffect(id, model.refreshToken) { data = runCatching { model.api?.collection(id) }.getOrNull() ?: data }
    val (collection, items) = data ?: run { Loading(); return }
    LazyVerticalGrid(
        columns = GridCells.Adaptive(minSize = 104.dp),
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 24.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
        modifier = Modifier.fillMaxSize(),
    ) {
        item(span = { GridItemSpan(maxLineSpan) }) {
            Column {
                Header(collection.backdrop, onBack)
                Text(collection.title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(top = 4.dp))
                Text(Format.meta(collection), color = Palette.dim, modifier = Modifier.padding(bottom = 8.dp))
            }
        }
        items(items, key = { it.id }) { Poster(it, width = 300) }
    }
}
