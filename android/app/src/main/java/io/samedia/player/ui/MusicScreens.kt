package io.samedia.player.ui

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Cast
import androidx.compose.material.icons.filled.Equalizer
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.LockOpen
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Radio
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameMillis
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil3.compose.AsyncImage
import io.samedia.player.core.Album
import io.samedia.player.core.AlbumList
import io.samedia.player.core.Artist
import io.samedia.player.core.ArtistList
import io.samedia.player.core.Format
import io.samedia.player.core.MusicHome
import io.samedia.player.core.MusicSearch
import io.samedia.player.core.Profile
import io.samedia.player.core.ProfilesResponse
import io.samedia.player.core.RemotePlayer
import io.samedia.player.core.SpotifyDevice
import io.samedia.player.core.SpotifyDevices
import io.samedia.player.core.SpotifyPlaylist
import io.samedia.player.core.SpotifyPlaylistDetail
import io.samedia.player.core.SpotifyPlaylists
import io.samedia.player.core.SpotifySearch
import io.samedia.player.core.SpotifyStatus
import io.samedia.player.core.SpotifyTrack
import io.samedia.player.core.Track
import io.samedia.player.core.AdminDevices
import io.samedia.player.player.MusicController
import io.samedia.player.player.Spectrum
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.net.URLEncoder
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.pow
import kotlin.math.sin

// ── shared bits ──

@Composable
fun Cover(url: String?, title: String, modifier: Modifier = Modifier, round: Boolean = false) {
    val model = LocalModel.current
    val shape = if (round) CircleShape else RoundedCornerShape(10.dp)
    Box(modifier.aspectRatio(1f).clip(shape).background(Brush.linearGradient(listOf(Palette.surface2, Palette.surface))),
        contentAlignment = Alignment.Center) {
        Text(title, color = Palette.faint, fontSize = 12.sp, maxLines = 3, overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(8.dp))
        AsyncImage(model.api?.art(url, 512) ?: url, null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
    }
}

/** Play tracks on another screen (TV, tablet). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MusicPlayOnSheet(tracks: List<Track>, start: Int, onDismiss: () -> Unit) {
    val model = LocalModel.current
    val scope = rememberCoroutineScope()
    var players by remember { mutableStateOf<List<RemotePlayer>?>(null) }
    LaunchedEffect(Unit) { players = model.players() }
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = Palette.surface) {
        Column(Modifier.navigationBarsPadding().padding(bottom = 16.dp)) {
            Text("Play on", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp))
            val list = players
            when {
                list == null -> Box(Modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
                list.isEmpty() -> Text("No other Samedia screens are on right now.", color = Palette.dim, modifier = Modifier.padding(24.dp))
                else -> list.forEach { p ->
                    ListItem(
                        headlineContent = { Text(p.name) },
                        leadingContent = { Icon(p.symbol, null) },
                        colors = ListItemDefaults.colors(containerColor = Color.Transparent),
                        modifier = Modifier.clickable {
                            scope.launch {
                                try {
                                    model.command(p, buildJsonObject {
                                        put("action", "play_music")
                                        put("tracks", JsonArray(tracks.map { JsonPrimitive(it.id) }))
                                        put("index", start)
                                        model.profile?.let { put("profile_id", it.id) }
                                    })
                                    model.show("Playing on ${p.name}")
                                    onDismiss()
                                } catch (e: Exception) {
                                    model.show(e.message ?: "That screen didn't answer")
                                }
                            }
                        },
                    )
                }
            }
        }
    }
}

/** Pick the Spotify device to play on (Spotify plays in its own app there). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SpotifyDeviceSheet(onPick: (SpotifyDevice) -> Unit, onDismiss: () -> Unit) {
    val model = LocalModel.current
    var devices by remember { mutableStateOf<List<SpotifyDevice>?>(null) }
    LaunchedEffect(Unit) {
        devices = runCatching { model.api?.get<SpotifyDevices>("/api/v1/spotify/devices")?.devices }.getOrNull() ?: emptyList()
    }
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = Palette.surface) {
        Column(Modifier.navigationBarsPadding().padding(bottom = 16.dp)) {
            Text("Play on Spotify device", style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp))
            val list = devices
            when {
                list == null -> Box(Modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
                list.isEmpty() -> Text("Open Spotify on a TV, phone or speaker: it shows up here then.", color = Palette.dim,
                    modifier = Modifier.padding(24.dp))
                else -> list.forEach { d ->
                    ListItem(
                        headlineContent = { Text(d.name) },
                        supportingContent = { Text((d.type ?: "") + if (d.active) " · playing" else "") },
                        leadingContent = { Icon(Icons.Filled.Equalizer, null) },
                        colors = ListItemDefaults.colors(containerColor = Color.Transparent),
                        modifier = Modifier.clickable { onPick(d); onDismiss() },
                    )
                }
            }
        }
    }
}

// ── the Music tab ──

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun MusicScreen() {
    val model = LocalModel.current
    val nav = LocalNavigator.current
    val context = LocalContext.current
    var section by rememberSaveable { mutableStateOf("albums") }
    var query by rememberSaveable { mutableStateOf("") }
    var home by remember { mutableStateOf<MusicHome?>(null) }
    var albums by remember { mutableStateOf<List<Album>?>(null) }
    var artists by remember { mutableStateOf<List<Artist>?>(null) }
    var spotify by remember { mutableStateOf<SpotifyStatus?>(null) }
    var playlists by remember { mutableStateOf<List<SpotifyPlaylist>?>(null) }
    var local by remember { mutableStateOf<MusicSearch?>(null) }
    var remoteHits by remember { mutableStateOf<SpotifySearch?>(null) }
    var pickDeviceFor by remember { mutableStateOf<SpotifyTrack?>(null) }
    val api = model.api

    LaunchedEffect(model.refreshToken) {
        home = runCatching { api?.get<MusicHome>("/api/v1/music/home") }.getOrNull()
        albums = runCatching { api?.get<AlbumList>("/api/v1/music/albums?sort=artist")?.albums }.getOrNull() ?: emptyList()
        spotify = runCatching { api?.get<SpotifyStatus>("/api/v1/spotify/status") }.getOrNull()
    }
    LaunchedEffect(section) {
        if (section == "artists" && artists == null) artists = runCatching { api?.get<ArtistList>("/api/v1/music/artists")?.artists }.getOrNull() ?: emptyList()
        if (section == "spotify" && playlists == null) playlists = runCatching { api?.get<SpotifyPlaylists>("/api/v1/spotify/playlists")?.playlists }.getOrNull() ?: emptyList()
    }
    LaunchedEffect(query) {
        val q = query.trim()
        if (q.isEmpty()) { local = null; remoteHits = null; return@LaunchedEffect }
        delay(300)
        val enc = URLEncoder.encode(q, "UTF-8")
        local = runCatching { api?.get<MusicSearch>("/api/v1/music/search?q=$enc") }.getOrNull()
        remoteHits = if (spotify?.connected == true) runCatching { api?.get<SpotifySearch>("/api/v1/spotify/search?q=$enc") }.getOrNull() else null
    }

    LazyVerticalGrid(
        columns = GridCells.Adaptive(minSize = 120.dp),
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 24.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
        modifier = Modifier.fillMaxSize(),
    ) {
        item(span = { GridItemSpan(maxLineSpan) }) {
            Column {
                ScreenTitle("Music", inset = 4.dp)
                OutlinedTextField(query, { query = it }, singleLine = true, leadingIcon = { Icon(Icons.Filled.Search, null) },
                    placeholder = { Text(if (spotify?.connected == true) "Your music and Spotify" else "Artists, albums, songs") },
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search), modifier = Modifier.fillMaxWidth())
                if (query.isBlank()) {
                    Row(Modifier.horizontalScroll(rememberScrollState()).padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        val chips = listOf("albums" to "Albums", "artists" to "Artists") +
                            if (spotify?.connected == true) listOf("spotify" to "Spotify") else emptyList()
                        chips.forEach { (key, label) ->
                            FilterChip(section == key, { section = key }, { Text(label) },
                                colors = FilterChipDefaults.filterChipColors(selectedContainerColor = Palette.accent.copy(alpha = 0.25f)))
                        }
                    }
                }
            }
        }
        if (query.isNotBlank()) {
            val l = local
            if (l != null) {
                if (l.artists.isNotEmpty()) {
                    item(span = { GridItemSpan(maxLineSpan) }) { SectionTitle("Artists") }
                    items(l.artists, key = { "ar" + it.id }) { a -> ArtistTile(a) }
                }
                if (l.albums.isNotEmpty()) {
                    item(span = { GridItemSpan(maxLineSpan) }) { SectionTitle("Albums") }
                    items(l.albums, key = { "al" + it.id }) { a -> AlbumTile(a) }
                }
                if (l.tracks.isNotEmpty()) {
                    item(span = { GridItemSpan(maxLineSpan) }) { SectionTitle("Songs") }
                    items(l.tracks, key = { "t" + it.id }, span = { GridItemSpan(maxLineSpan) }) { t ->
                        TrackRow(t, showArtist = true, onClick = { if (api != null) MusicController.play(context, api, listOf(t)) })
                    }
                }
            }
            val r = remoteHits
            if (r != null) {
                if (r.playlists.isNotEmpty()) {
                    item(span = { GridItemSpan(maxLineSpan) }) { SectionTitle("Spotify playlists") }
                    items(r.playlists.take(12), key = { "sp" + it.id }) { p -> PlaylistTile(p) }
                }
                if (r.tracks.isNotEmpty()) {
                    item(span = { GridItemSpan(maxLineSpan) }) { SectionTitle("Spotify songs") }
                    items(r.tracks, key = { "st" + it.id }, span = { GridItemSpan(maxLineSpan) }) { t ->
                        SpotifyRow(t) { pickDeviceFor = t }
                    }
                }
            }
        } else when (section) {
            "artists" -> items(artists ?: emptyList(), key = { it.id }) { ArtistTile(it) }
            "spotify" -> items(playlists ?: emptyList(), key = { it.id }) { PlaylistTile(it) }
            else -> {
                home?.shelves?.filter { it.id != "recent" }?.forEach { shelf ->
                    item(span = { GridItemSpan(maxLineSpan) }, key = "shelf-" + shelf.id) {
                        Column {
                            SectionTitle(shelf.title)
                            LazyRow(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                items(shelf.items, key = { shelf.id + it.id }) { a -> AlbumTile(a, Modifier.width(130.dp)) }
                            }
                        }
                    }
                }
                val list = albums
                if (list != null && list.isEmpty() && spotify?.connected != true) {
                    item(span = { GridItemSpan(maxLineSpan) }) {
                        Text("No music yet. Put music in a media folder (or set a folder to Music in the server admin page) and scan.",
                            color = Palette.dim, modifier = Modifier.padding(8.dp))
                    }
                }
                if (!list.isNullOrEmpty()) {
                    item(span = { GridItemSpan(maxLineSpan) }) { SectionTitle("All albums") }
                    items(list, key = { "all" + it.id }) { AlbumTile(it) }
                }
            }
        }
    }
    pickDeviceFor?.let { t ->
        SpotifyDeviceSheet(onPick = { d -> model.spotifyPlay(d, uris = listOfNotNull(t.uri)) }, onDismiss = { pickDeviceFor = null })
    }
}

@Composable
private fun AlbumTile(a: Album, modifier: Modifier = Modifier) {
    val nav = LocalNavigator.current
    Column(modifier.clickable { nav.push(Route.Album(a.id)) }) {
        Cover(a.art, a.title, Modifier.fillMaxWidth())
        Text(a.title, style = MaterialTheme.typography.labelLarge, maxLines = 1, overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(top = 6.dp))
        Text(a.artist ?: "", color = Palette.dim, style = MaterialTheme.typography.labelMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
private fun ArtistTile(a: Artist) {
    val nav = LocalNavigator.current
    Column(Modifier.clickable { nav.push(Route.Artist(a.id, a.name)) }, horizontalAlignment = Alignment.CenterHorizontally) {
        Cover(a.art, a.name, Modifier.fillMaxWidth(), round = true)
        Text(a.name, style = MaterialTheme.typography.labelLarge, maxLines = 1, overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(top = 6.dp))
    }
}

@Composable
private fun PlaylistTile(p: SpotifyPlaylist) {
    val nav = LocalNavigator.current
    Column(Modifier.clickable { nav.push(Route.SpotifyList(p.id)) }) {
        Cover(p.image, p.title, Modifier.fillMaxWidth())
        Text(p.title, style = MaterialTheme.typography.labelLarge, maxLines = 1, overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(top = 6.dp))
        Text("${p.tracks ?: 0} songs", color = Palette.dim, style = MaterialTheme.typography.labelMedium)
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun TrackRow(t: Track, showArtist: Boolean = false, number: Int? = null, onLongClick: (() -> Unit)? = null, onClick: () -> Unit) {
    val playing = MusicController.current?.id == t.id
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).combinedClickable(onClick = onClick, onLongClick = onLongClick)
            .padding(vertical = 10.dp, horizontal = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (number != null) Text("$number", color = if (playing) Palette.accent else Palette.faint, modifier = Modifier.width(32.dp))
        Column(Modifier.weight(1f)) {
            Text(t.title, color = if (playing) Palette.accent else Palette.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (showArtist && t.artist != null) Text(t.artist + (t.album?.let { " · $it" } ?: ""), color = Palette.dim,
                style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Text(t.duration?.let { Format.clock(it) } ?: "", color = Palette.dim, style = MaterialTheme.typography.bodySmall)
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun SpotifyRow(t: SpotifyTrack, onLongClick: (() -> Unit)? = null, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).combinedClickable(onClick = onClick, onLongClick = onLongClick)
            .padding(vertical = 8.dp, horizontal = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Cover(t.image, t.title ?: "", Modifier.size(44.dp))
        Column(Modifier.weight(1f).padding(start = 12.dp)) {
            Text(t.title ?: "", maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(t.artist ?: "", color = Palette.dim, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Text(t.duration?.let { Format.clock(it) } ?: "", color = Palette.dim, style = MaterialTheme.typography.bodySmall)
    }
}

/** Header of album/playlist pages: the cover big, the same blurred behind. */
@Composable
private fun CoverHeader(art: String?, title: String, onBack: () -> Unit) {
    val model = LocalModel.current
    Box(Modifier.fillMaxWidth().height(300.dp)) {
        AsyncImage(model.api?.art(art, 512) ?: art, null, contentScale = ContentScale.Crop,
            modifier = Modifier.fillMaxSize().blur(40.dp))
        Box(Modifier.fillMaxSize().background(Brush.verticalGradient(0.3f to Color.Black.copy(alpha = 0.3f), 1f to Palette.bg)))
        Cover(art, title, Modifier.align(Alignment.Center).padding(top = 30.dp).size(200.dp))
        IconButton(onClick = onBack, modifier = Modifier.statusBarsPadding().padding(8.dp).background(Color.Black.copy(alpha = 0.45f), CircleShape)) {
            Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Color.White)
        }
    }
}

@Composable
fun AlbumScreen(id: String, onBack: () -> Unit) {
    val model = LocalModel.current
    val nav = LocalNavigator.current
    val context = LocalContext.current
    var album by remember { mutableStateOf<Album?>(null) }
    var playOn by remember { mutableStateOf<Int?>(null) }
    LaunchedEffect(id) { album = runCatching { model.api?.get<Album>("/api/v1/music/albums/$id") }.getOrNull() }
    val a = album ?: run { Loading(); return }
    val api = model.api ?: return
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
        item { CoverHeader(a.art, a.title, onBack) }
        item {
            Column(Modifier.padding(horizontal = 20.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Text(a.title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                Text(a.artist ?: "", color = Palette.accent, modifier = Modifier.clickable {
                    a.artistId?.let { nav.push(Route.Artist(it, a.artist ?: "")) } })
                Text(listOfNotNull(a.year?.toString(), "${a.trackCount} songs", Format.runtime(a.duration), a.genre).joinToString("  ·  "),
                    color = Palette.dim, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 4.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.padding(vertical = 14.dp)) {
                    Button(onClick = { MusicController.play(context, api, a.tracks, 0) }) {
                        Icon(Icons.Filled.PlayArrow, null); Text("Play", Modifier.padding(start = 6.dp))
                    }
                    FilledTonalButton(onClick = { MusicController.play(context, api, a.tracks, a.tracks.indices.random(), shuffled = true) }) {
                        Icon(Icons.Filled.Shuffle, null); Text("Shuffle", Modifier.padding(start = 6.dp))
                    }
                    if (model.hasRemote) FilledTonalButton(onClick = { playOn = 0 }) { Icon(Icons.Filled.Cast, null) }
                }
            }
        }
        items(a.tracks.size) { i ->
            Box(Modifier.padding(horizontal = 14.dp)) {
                TrackRow(a.tracks[i], showArtist = a.artist == "Various Artists", number = a.tracks[i].track ?: (i + 1),
                    onLongClick = if (model.hasRemote) ({ playOn = i }) else null) { MusicController.play(context, api, a.tracks, i) }
            }
        }
    }
    playOn?.let { MusicPlayOnSheet(a.tracks, it) { playOn = null } }
}

@Composable
fun ArtistScreen(id: String, name: String, onBack: () -> Unit) {
    val model = LocalModel.current
    var artist by remember { mutableStateOf<Artist?>(null) }
    LaunchedEffect(id) { artist = runCatching { model.api?.get<Artist>("/api/v1/music/artists/$id") }.getOrNull() }
    LazyVerticalGrid(
        columns = GridCells.Adaptive(minSize = 130.dp),
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 24.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp), verticalArrangement = Arrangement.spacedBy(14.dp),
        modifier = Modifier.fillMaxSize(),
    ) {
        item(span = { GridItemSpan(maxLineSpan) }) {
            Row(Modifier.statusBarsPadding(), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") }
                Text(name, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            }
        }
        items(artist?.albums ?: emptyList(), key = { it.id }) { AlbumTile(it) }
    }
}

@Composable
fun SpotifyListScreen(id: String, onBack: () -> Unit) {
    val model = LocalModel.current
    var detail by remember { mutableStateOf<SpotifyPlaylistDetail?>(null) }
    var pick by remember { mutableStateOf<((io.samedia.player.core.SpotifyDevice) -> Unit)?>(null) }
    LaunchedEffect(id) { detail = runCatching { model.api?.get<SpotifyPlaylistDetail>("/api/v1/spotify/playlists/$id") }.getOrNull() }
    val p = detail ?: run { Loading(); return }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
        item { CoverHeader(p.image, p.title, onBack) }
        item {
            Column(Modifier.padding(horizontal = 20.dp).fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
                Text(p.title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                Text((p.owner?.let { "by $it  ·  " } ?: "") + "${p.tracks.size} songs  ·  hold a song for a radio",
                    color = Palette.dim, style = MaterialTheme.typography.bodySmall)
                Button(onClick = { pick = { d -> model.spotifyPlay(d, contextUri = p.uri) } }, modifier = Modifier.padding(vertical = 14.dp)) {
                    Icon(Icons.Filled.PlayArrow, null); Text("Play on Spotify…", Modifier.padding(start = 6.dp))
                }
            }
        }
        items(p.tracks.size) { i ->
            val t = p.tracks[i]
            Box(Modifier.padding(horizontal = 14.dp)) {
                SpotifyRow(t, onLongClick = { pick = { d -> t.uri?.let { model.spotifyRadio(d, it) } } }) {
                    pick = { d -> model.spotifyPlay(d, contextUri = p.uri, offset = i) }
                }
            }
        }
    }
    pick?.let { action -> SpotifyDeviceSheet(onPick = action, onDismiss = { pick = null }) }
}

// ── mini player and Now Playing ──

@Composable
fun MiniPlayer() {
    val model = LocalModel.current
    val nav = LocalNavigator.current
    val t = MusicController.current ?: return
    Row(
        Modifier.fillMaxWidth().background(Palette.surface2).clickable { nav.push(Route.NowPlaying) }.padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Cover(t.art, t.album ?: "", Modifier.size(44.dp))
        Column(Modifier.weight(1f).padding(horizontal = 12.dp)) {
            Text(t.title, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyMedium)
            Text(t.artist ?: "", color = Palette.dim, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall)
        }
        IconButton(onClick = { MusicController.toggle() }) {
            Icon(if (MusicController.playing) Icons.Filled.Pause else Icons.Filled.PlayArrow, null)
        }
        IconButton(onClick = { MusicController.next() }) { Icon(Icons.Filled.SkipNext, null) }
    }
}

private val VIZ = listOf("bars" to "Classic Spectrum", "scope" to "Oscilloscope", "disc" to "Vinyl")

@Composable
fun NowPlayingScreen(onBack: () -> Unit) {
    val model = LocalModel.current
    val t = MusicController.current
    var mode by rememberSaveable { mutableStateOf(0) }
    var showViz by rememberSaveable { mutableStateOf(true) }
    var scrub by remember { mutableStateOf<Float?>(null) }
    var playOn by remember { mutableStateOf(false) }
    var now by remember { mutableLongStateOf(0L) }
    LaunchedEffect(Unit) { while (true) { now = System.currentTimeMillis(); delay(500) } }
    Box(Modifier.fillMaxSize().background(Color.Black)) {
        AsyncImage(model.api?.art(t?.art, 512), null, contentScale = ContentScale.Crop, alpha = 0.35f,
            modifier = Modifier.fillMaxSize().blur(60.dp))
        Column(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(20.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Color.White) }
                Spacer(Modifier.weight(1f))
                TextButton(onClick = { showViz = !showViz }) { Text(if (showViz) "Cover" else "Visualizer", color = Color.White) }
                if (showViz) TextButton(onClick = { mode = (mode + 1) % VIZ.size }) { Text(VIZ[mode].second, color = Palette.accent) }
            }
            Box(Modifier.fillMaxWidth().weight(1f), contentAlignment = Alignment.Center) {
                if (showViz) Visualizer(VIZ[mode].first, t?.art, Modifier.fillMaxSize())
                else Cover(t?.art, t?.album ?: "", Modifier.fillMaxWidth(0.85f))
            }
            Text(t?.title ?: "Nothing playing", color = Color.White, style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(listOfNotNull(t?.artist, t?.album).joinToString(" — "), color = Palette.dim, maxLines = 1, overflow = TextOverflow.Ellipsis)
            val dur = MusicController.duration.toFloat().coerceAtLeast(1f)
            val at = scrub ?: (if (now > 0) MusicController.position.toFloat() else 0f).coerceIn(0f, dur)
            Slider(at, { scrub = it }, valueRange = 0f..dur, onValueChangeFinished = { scrub?.let { MusicController.seek(it.toDouble()) }; scrub = null },
                colors = SliderDefaults.colors(thumbColor = Color.White, activeTrackColor = Palette.accent))
            Row {
                Text(Format.clock(at.toDouble()), color = Palette.dim, style = MaterialTheme.typography.labelMedium)
                Spacer(Modifier.weight(1f))
                Text("-" + Format.clock((dur - at).toDouble()), color = Palette.dim, style = MaterialTheme.typography.labelMedium)
            }
            Row(Modifier.fillMaxWidth().padding(vertical = 10.dp), horizontalArrangement = Arrangement.SpaceEvenly, verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = { MusicController.shuffleOn(!MusicController.shuffle) }) {
                    Icon(Icons.Filled.Shuffle, "Shuffle", tint = if (MusicController.shuffle) Palette.accent else Palette.dim)
                }
                IconButton(onClick = { MusicController.previous() }, modifier = Modifier.size(56.dp)) {
                    Icon(Icons.Filled.SkipPrevious, "Previous", tint = Color.White, modifier = Modifier.size(36.dp))
                }
                FilledIconButton(onClick = { MusicController.toggle() }, modifier = Modifier.size(76.dp),
                    colors = IconButtonDefaults.filledIconButtonColors(containerColor = Color.White)) {
                    Icon(if (MusicController.playing) Icons.Filled.Pause else Icons.Filled.PlayArrow, null, tint = Color.Black, modifier = Modifier.size(40.dp))
                }
                IconButton(onClick = { MusicController.next() }, modifier = Modifier.size(56.dp)) {
                    Icon(Icons.Filled.SkipNext, "Next", tint = Color.White, modifier = Modifier.size(36.dp))
                }
                IconButton(onClick = { playOn = true }, enabled = model.hasRemote) { Icon(Icons.Filled.Cast, "Send to", tint = Palette.dim) }
            }
        }
    }
    if (playOn) {
        val q = MusicController.queue
        MusicPlayOnSheet(q, MusicController.index) { playOn = false }
    }
}

/** The visualizer: Winamp's bars, an oscilloscope, a record with a radial spectrum. */
@Composable
fun Visualizer(mode: String, art: String?, modifier: Modifier = Modifier) {
    var frame by remember { mutableLongStateOf(0L) }
    val peaks = remember { FloatArray(28) }
    var spin by remember { mutableStateOf(0f) }
    LaunchedEffect(mode) { while (true) withFrameMillis { frame = it } }
    val model = LocalModel.current
    Box(modifier) {
        if (mode == "disc") {
            AsyncImage(model.api?.art(art, 512), null, contentScale = ContentScale.Crop,
                modifier = Modifier.align(Alignment.Center).fillMaxWidth(0.34f).aspectRatio(1f).clip(CircleShape))
        }
        Canvas(Modifier.fillMaxSize()) {
            @Suppress("UNUSED_EXPRESSION") frame
            val playing = MusicController.playing
            when (mode) {
                "bars" -> {
                    val n = 28
                    val b = Spectrum.bands(n, playing)
                    val gap = size.width * 0.008f
                    val bw = (size.width - gap * (n - 1)) / n
                    val base = size.height * 0.8f
                    val seg = size.height * 0.018f
                    for (i in 0 until n) {
                        val h = b[i].toDouble().pow(1.3).toFloat() * base * 0.95f
                        var y = base - seg
                        while (y > base - h) {
                            val f = (base - y) / base
                            val c = when { f > 0.8f -> Color(0xFFFF2000); f > 0.55f -> Color(0xFFFFB000); else -> Color(0xFF00C800) }
                            drawRect(c, Offset(i * (bw + gap), y), Size(bw, seg))
                            y -= seg * 1.25f
                        }
                        peaks[i] = max(peaks[i] - base * 0.006f, h)
                        drawRect(Color(0xFFC8C8C8), Offset(i * (bw + gap), base - peaks[i] - seg * 0.5f), Size(bw, seg * 0.35f))
                    }
                }
                "scope" -> {
                    val w = Spectrum.wave(256, playing)
                    val path = Path()
                    w.forEachIndexed { i, v ->
                        val x = i / (w.size - 1f) * size.width
                        val y = size.height / 2 + v * size.height * 0.38f
                        if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
                    }
                    drawPath(path, Color(0xFF00FF8C).copy(alpha = 0.25f), style = Stroke(width = 12f, cap = StrokeCap.Round))
                    drawPath(path, Color(0xFF00FF8C), style = Stroke(width = 3f, cap = StrokeCap.Round))
                }
                else -> {
                    val n = 64
                    val b = Spectrum.bands(n / 2, playing)
                    if (playing) spin += 0.5f
                    val r = size.minDimension * 0.19f
                    val c = Offset(size.width / 2, size.height / 2)
                    for (i in 0 until n) {
                        val v = b[if (i < n / 2) i else n - 1 - i]
                        val a = i / n.toFloat() * 2 * PI.toFloat() - PI.toFloat() / 2
                        val len = 8f + v.toDouble().pow(1.2).toFloat() * size.minDimension * 0.25f
                        val hue = (200 + i / n.toFloat() * 160) % 360
                        drawLine(Color.hsv(hue, 0.85f, 0.95f), Offset(c.x + cos(a) * (r + 8), c.y + sin(a) * (r + 8)),
                            Offset(c.x + cos(a) * (r + 8 + len), c.y + sin(a) * (r + 8 + len)), strokeWidth = 6f, cap = StrokeCap.Round)
                    }
                    drawCircle(Color.Black.copy(alpha = 0f), r)
                }
            }
        }
    }
}

// ── locking a screen to approved music (admin) ──

@Composable
fun LockScreen(player: RemotePlayer, onBack: () -> Unit) {
    val model = LocalModel.current
    val scope = rememberCoroutineScope()
    val api = model.api ?: return
    var profiles by remember { mutableStateOf<List<Profile>>(emptyList()) }
    var artists by remember { mutableStateOf<List<Artist>>(emptyList()) }
    var albums by remember { mutableStateOf<List<Album>>(emptyList()) }
    var lists by remember { mutableStateOf<List<SpotifyPlaylist>>(emptyList()) }
    var locked by remember { mutableStateOf(false) }
    var profile by remember { mutableStateOf<String?>(null) }
    val pickedArtists = remember { mutableStateOf(setOf<String>()) }
    val pickedAlbums = remember { mutableStateOf(setOf<String>()) }
    val pickedLists = remember { mutableStateOf(setOf<String>()) }
    var filter by remember { mutableStateOf("") }
    LaunchedEffect(player.id) {
        profiles = runCatching { api.get<ProfilesResponse>("/api/v1/profiles?all=true").profiles }.getOrNull() ?: emptyList()
        artists = runCatching { api.get<ArtistList>("/api/v1/music/artists").artists }.getOrNull() ?: emptyList()
        albums = runCatching { api.get<AlbumList>("/api/v1/music/albums?sort=artist").albums }.getOrNull() ?: emptyList()
        lists = runCatching { api.get<SpotifyPlaylists>("/api/v1/spotify/playlists").playlists }.getOrNull() ?: emptyList()
        val lock = runCatching { api.get<AdminDevices>("/api/v1/admin/devices").devices.firstOrNull { it.id == player.id }?.lock }.getOrNull()
        locked = lock != null
        profile = lock?.profile ?: profiles.firstOrNull { it.kids }?.id ?: profiles.firstOrNull()?.id
        pickedArtists.value = lock?.artists?.toSet() ?: emptySet()
        pickedAlbums.value = lock?.albums?.toSet() ?: emptySet()
        pickedLists.value = lock?.playlists?.toSet() ?: emptySet()
    }
    fun save() = scope.launch {
        try {
            api.text("/api/v1/admin/devices/${player.id}/lock", "PUT", buildJsonObject {
                put("profile", profile ?: "default")
                put("music_only", true)
                put("artists", JsonArray(pickedArtists.value.map { JsonPrimitive(it) }))
                put("albums", JsonArray(pickedAlbums.value.map { JsonPrimitive(it) }))
                put("playlists", JsonArray(pickedLists.value.map { JsonPrimitive(it) }))
            })
            model.show("${player.name} is locked to music")
            onBack()
        } catch (e: Exception) { model.show(e.message ?: "Couldn't lock it") }
    }
    fun unlock() = scope.launch {
        runCatching { api.text("/api/v1/admin/devices/${player.id}/lock", "DELETE") }
        model.show("${player.name} is unlocked")
        onBack()
    }
    val f = filter.trim().lowercase()
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 32.dp)) {
        item {
            Row(Modifier.statusBarsPadding(), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") }
                Text("Lock ${player.name}", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            }
            Text("A locked screen shows one profile and plays only the music approved here: no films or shows.",
                color = Palette.dim, modifier = Modifier.padding(horizontal = 20.dp))
            SectionTitleIn("Profile")
            Row(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                profiles.forEach { p ->
                    FilterChip(profile == p.id, { profile = p.id }, { Text(p.name) }, leadingIcon = { Avatar(p, 22.dp) },
                        colors = FilterChipDefaults.filterChipColors(selectedContainerColor = Palette.accent.copy(alpha = 0.25f)))
                }
            }
            OutlinedTextField(filter, { filter = it }, singleLine = true, placeholder = { Text("Filter") },
                leadingIcon = { Icon(Icons.Filled.Search, null) }, modifier = Modifier.fillMaxWidth().padding(16.dp))
        }
        if (lists.isNotEmpty()) {
            item { SectionTitleIn("Spotify playlists") }
            items(lists.filter { f.isEmpty() || it.title.lowercase().contains(f) }, key = { "p" + it.id }) { p ->
                CheckRow(p.title, p.id in pickedLists.value) { on -> pickedLists.value = if (on) pickedLists.value + p.id else pickedLists.value - p.id }
            }
        }
        item { SectionTitleIn("Artists (all their albums)") }
        items(artists.filter { f.isEmpty() || it.name.lowercase().contains(f) }, key = { "r" + it.id }) { a ->
            CheckRow(a.name, a.id in pickedArtists.value) { on -> pickedArtists.value = if (on) pickedArtists.value + a.id else pickedArtists.value - a.id }
        }
        item { SectionTitleIn("Albums") }
        items(albums.filter { f.isEmpty() || it.title.lowercase().contains(f) || (it.artist ?: "").lowercase().contains(f) }, key = { "a" + it.id }) { a ->
            CheckRow("${a.artist} — ${a.title}", a.id in pickedAlbums.value) { on -> pickedAlbums.value = if (on) pickedAlbums.value + a.id else pickedAlbums.value - a.id }
        }
        item {
            Row(Modifier.padding(16.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(onClick = { save() }) { Icon(Icons.Filled.Lock, null); Text(if (locked) "Save lock" else "Lock", Modifier.padding(start = 6.dp)) }
                if (locked) OutlinedButton(onClick = { unlock() }) { Icon(Icons.Filled.LockOpen, null); Text("Unlock", Modifier.padding(start = 6.dp)) }
            }
        }
    }
}

@Composable
private fun SectionTitleIn(text: String) {
    Text(text, style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(start = 20.dp, top = 16.dp, bottom = 6.dp))
}

@Composable
private fun CheckRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().clickable { onChange(!checked) }.padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically) {
        Checkbox(checked, onChange)
        Text(label, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}
