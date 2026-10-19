package io.samedia.player.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import io.samedia.player.core.Home
import io.samedia.player.core.ItemList
import io.samedia.player.core.MediaItem
import io.samedia.player.core.SearchResults
import io.samedia.player.core.Shelf
import kotlinx.coroutines.delay
import java.net.URLEncoder

@Composable
fun HomeScreen() {
    val model = LocalModel.current
    var home by remember { mutableStateOf<Home?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var attempt by remember { mutableStateOf(0) }
    LaunchedEffect(model.refreshToken, model.profile?.id, attempt) {
        try {
            home = model.api?.get<Home>("/api/v1/home")
            error = null
        } catch (e: Exception) {
            if (home == null) error = e.message
        }
    }
    val h = home
    when {
        h != null -> LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
            item { ScreenTitle("Home") }
            if (h.shelves.isEmpty()) item {
                Text("Nothing here yet. Add movies and shows on the server's admin page.", color = Palette.dim,
                    modifier = Modifier.padding(20.dp))
            }
            items(h.shelves, key = { it.id }) { ShelfRow(it) }
        }
        error != null -> ErrorBox(error ?: "") { attempt++ }
        else -> Loading()
    }
}

@Composable
private fun ShelfRow(shelf: Shelf) {
    val wide = shelf.id == "continue" || shelf.id == "nextup" || shelf.id == "bookmarks"
    Column(Modifier.padding(top = 14.dp)) {
        Text(shelf.title, style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp))
        LazyRow(contentPadding = PaddingValues(horizontal = 20.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            items(shelf.items, key = { it.id }) { item ->
                if (wide) WideCard(item, Modifier.width(232.dp)) else Poster(item, Modifier.width(116.dp))
            }
        }
    }
}

private val sorts = listOf("title" to "A–Z", "added" to "Recently added", "year" to "Year", "rating" to "Rating")

@Composable
fun LibraryScreen(kind: String) {
    val model = LocalModel.current
    var sort by rememberSaveable(kind) { mutableStateOf("title") }
    var list by remember(kind) { mutableStateOf<List<MediaItem>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var attempt by remember { mutableStateOf(0) }
    LaunchedEffect(kind, sort, model.refreshToken, model.profile?.id, attempt) {
        try {
            list = model.api?.get<ItemList>("/api/v1/$kind?sort=$sort")?.items
            error = null
        } catch (e: Exception) {
            if (list == null) error = e.message
        }
    }
    val items = list
    when {
        items != null -> LazyVerticalGrid(
            columns = GridCells.Adaptive(minSize = 104.dp),
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 24.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            modifier = Modifier.fillMaxSize(),
        ) {
            item(span = { GridItemSpan(maxLineSpan) }) {
                Column {
                    ScreenTitle(if (kind == "movies") "Movies" else "TV Shows", inset = 4.dp)
                    Row(Modifier.horizontalScroll(rememberScrollState()).padding(start = 4.dp, bottom = 6.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        sorts.forEach { (key, label) ->
                            FilterChip(
                                selected = sort == key, onClick = { sort = key }, label = { Text(label) },
                                colors = FilterChipDefaults.filterChipColors(selectedContainerColor = Palette.accent.copy(alpha = 0.25f)),
                            )
                        }
                    }
                }
            }
            items(items, key = { it.id }) { Poster(it, width = 300) }
        }
        error != null -> ErrorBox(error ?: "") { attempt++ }
        else -> Loading()
    }
}

@Composable
fun SearchScreen() {
    val model = LocalModel.current
    var query by rememberSaveable { mutableStateOf("") }
    var results by remember { mutableStateOf<SearchResults?>(null) }
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { if (query.isEmpty()) runCatching { focus.requestFocus() } }
    LaunchedEffect(query, model.refreshToken) {
        val q = query.trim()
        if (q.isEmpty()) { results = null; return@LaunchedEffect }
        delay(300)
        results = runCatching { model.api?.get<SearchResults>("/api/v1/search?q=" + URLEncoder.encode(q, "UTF-8")) }.getOrNull()
    }
    LazyVerticalGrid(
        columns = GridCells.Adaptive(minSize = 104.dp),
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 24.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
        modifier = Modifier.fillMaxSize(),
    ) {
        item(span = { GridItemSpan(maxLineSpan) }) {
            Column {
                ScreenTitle("Search", inset = 4.dp)
                OutlinedTextField(
                    query, { query = it }, singleLine = true,
                    leadingIcon = { Icon(Icons.Filled.Search, null) },
                    placeholder = { Text("Movies, shows, episodes") },
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                    modifier = Modifier.fillMaxWidth().padding(end = 4.dp).focusRequester(focus),
                )
            }
        }
        val r = results
        if (r != null) {
            if (r.movies.isEmpty() && r.shows.isEmpty() && r.episodes.isEmpty()) {
                item(span = { GridItemSpan(maxLineSpan) }) { Text("Nothing found.", color = Palette.dim, modifier = Modifier.padding(8.dp)) }
            }
            section("Movies", r.movies)
            section("Shows", r.shows)
            if (r.episodes.isNotEmpty()) {
                item(span = { GridItemSpan(maxLineSpan) }) { SectionTitle("Episodes") }
                items(r.episodes, key = { "e" + it.id }, span = { GridItemSpan(maxLineSpan) }) { EpisodeRow(it) }
            }
        }
    }
}

private fun androidx.compose.foundation.lazy.grid.LazyGridScope.section(title: String, list: List<MediaItem>) {
    if (list.isEmpty()) return
    item(span = { GridItemSpan(maxLineSpan) }) { SectionTitle(title) }
    items(list, key = { title + it.id }) { Poster(it, width = 300) }
}

@Composable
fun SectionTitle(text: String) {
    Text(text, style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 14.dp, bottom = 2.dp))
}
