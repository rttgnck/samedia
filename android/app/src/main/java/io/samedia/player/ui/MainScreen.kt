package io.samedia.player.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.Movie
import androidx.compose.material.icons.filled.People
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.SettingsRemote
import androidx.compose.material.icons.filled.Tv
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

enum class Tab(val label: String, val icon: ImageVector) {
    Remote("Remote", Icons.Filled.SettingsRemote),
    Home("Home", Icons.Filled.Home),
    Movies("Movies", Icons.Filled.Movie),
    Shows("TV", Icons.Filled.Tv),
    Search("Search", Icons.Filled.Search),
}

@Composable
fun MainScreen() {
    val model = LocalModel.current
    val tabs = if (model.hasRemote) Tab.entries else Tab.entries.filter { it != Tab.Remote }
    var tab by rememberSaveable { mutableStateOf(tabs.first()) }
    val stack = remember { mutableStateListOf<Route>() }
    val saved = rememberSaveableStateHolder()

    BackHandler(enabled = stack.isNotEmpty()) { stack.removeAt(stack.lastIndex) }

    CompositionLocalProvider(LocalNavigator provides Navigator { stack.add(it) }) {
        Scaffold(
            containerColor = Palette.bg,
            bottomBar = {
                NavigationBar(containerColor = Palette.surface) {
                    tabs.forEach { t ->
                        NavigationBarItem(
                            selected = t == tab && stack.isEmpty(),
                            onClick = { stack.clear(); tab = t },
                            icon = { Icon(t.icon, t.label) },
                            label = { Text(t.label) },
                            colors = NavigationBarItemDefaults.colors(
                                selectedIconColor = Palette.text, selectedTextColor = Palette.text,
                                indicatorColor = Palette.accent.copy(alpha = 0.28f),
                                unselectedIconColor = Palette.dim, unselectedTextColor = Palette.dim,
                            ),
                        )
                    }
                }
            },
        ) { padding ->
            Box(Modifier.fillMaxSize().padding(padding)) {
                val top = stack.lastOrNull()
                if (top == null) {
                    saved.SaveableStateProvider(tab.name) {
                        when (tab) {
                            Tab.Remote -> RemoteScreen()
                            Tab.Home -> HomeScreen()
                            Tab.Movies -> LibraryScreen("movies")
                            Tab.Shows -> LibraryScreen("shows")
                            Tab.Search -> SearchScreen()
                        }
                    }
                } else {
                    saved.SaveableStateProvider("route-${stack.size}-$top") {
                        when (top) {
                            is Route.Item -> DetailScreen(top.item) { stack.removeAt(stack.lastIndex) }
                            is Route.Show -> ShowScreen(top.id) { stack.removeAt(stack.lastIndex) }
                            is Route.Collection -> CollectionScreen(top.id) { stack.removeAt(stack.lastIndex) }
                        }
                    }
                }
                if (top == null) ProfileMenu(Modifier.align(Alignment.TopEnd).padding(8.dp))
            }
        }
    }
}

/** The profile's picture, top right: switch profile or server. */
@Composable
private fun ProfileMenu(modifier: Modifier) {
    val model = LocalModel.current
    val profile = model.profile ?: return
    var open by remember { mutableStateOf(false) }
    Box(modifier) {
        IconButton(onClick = { open = true }) { Avatar(profile, 34.dp) }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            DropdownMenuItem(
                text = { Text("Switch profile") },
                leadingIcon = { Icon(Icons.Filled.People, null) },
                onClick = { open = false; model.switchProfile() },
            )
            DropdownMenuItem(
                text = { Text("Change server") },
                leadingIcon = { Icon(Icons.AutoMirrored.Filled.Logout, null) },
                onClick = { open = false; model.forgetServer() },
            )
        }
    }
}

/** A screen's big title; [inset] is its distance from the left edge (less inside padded grids). */
@Composable
fun ScreenTitle(text: String, inset: Dp = 20.dp) {
    Text(
        text, style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold,
        modifier = Modifier.padding(start = inset, top = 16.dp, end = 64.dp, bottom = 8.dp),
    )
}
