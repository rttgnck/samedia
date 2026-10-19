package io.samedia.player.ui

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Dns
import androidx.compose.material.icons.filled.SwapHoriz
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import coil3.compose.AsyncImage
import io.samedia.player.R
import io.samedia.player.core.Api
import io.samedia.player.core.Discovery
import io.samedia.player.core.Profile

@Composable
fun ConnectScreen() {
    val model = LocalModel.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val discovery = remember { Discovery(context.applicationContext) }
    DisposableEffect(Unit) {
        discovery.start(scope)
        onDispose { discovery.stop() }
    }
    var address by rememberSaveable { mutableStateOf("") }
    fun connectTyped() = Api.normalize(address)?.let { model.connect(it) } ?: run { model.error = "Enter the server's address, like nasos.local" }

    Column(
        Modifier.fillMaxSize().safeDrawingPadding().verticalScroll(rememberScrollState()).padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.height(32.dp))
        Image(painterResource(R.drawable.logo), null, Modifier.size(112.dp).clip(RoundedCornerShape(26.dp)))
        Spacer(Modifier.height(14.dp))
        Text("Samedia", style = MaterialTheme.typography.headlineLarge, fontWeight = FontWeight.Bold)
        Text("Your movies and shows, and a remote for every screen", color = Palette.dim, textAlign = TextAlign.Center,
            modifier = Modifier.padding(top = 4.dp, bottom = 28.dp))

        Column(Modifier.widthIn(max = 520.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("On your network", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                if (discovery.searching) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
            }
            if (!discovery.searching && discovery.servers.isEmpty()) {
                Text("No servers found. Type its address below.", color = Palette.dim)
            }
            discovery.servers.forEach { s ->
                Row(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(Palette.surface)
                        .clickable(enabled = !model.busy) { model.connect(s.url) }.padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(Icons.Filled.Dns, null, tint = Palette.accent)
                    Column(Modifier.weight(1f).padding(horizontal = 14.dp)) {
                        Text(s.name, style = MaterialTheme.typography.titleMedium)
                        Text("${s.url.host}:${s.url.port}", color = Palette.dim, style = MaterialTheme.typography.bodySmall)
                    }
                    Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = Palette.dim)
                }
            }

            Spacer(Modifier.height(18.dp))
            Text("Or by address", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(
                value = address, onValueChange = { address = it },
                placeholder = { Text("nasos.local or 192.168.1.20") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Go),
                keyboardActions = KeyboardActions(onGo = { connectTyped() }),
                modifier = Modifier.fillMaxWidth(),
            )
            Button(onClick = { connectTyped() }, enabled = !model.busy && address.isNotBlank(), modifier = Modifier.fillMaxWidth().height(50.dp)) {
                if (model.busy) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = Color.White)
                else Text("Connect")
            }
            model.error?.let { Text(it, color = Color(0xFFFF8A80)) }
        }
    }

    if (model.needsPin) PinDialog()
}

@Composable
private fun PinDialog() {
    val model = LocalModel.current
    var pin by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = { model.needsPin = false },
        title = { Text("Enter the server's PIN") },
        text = {
            Column {
                Text("It's on the Samedia admin page.", color = Palette.dim)
                OutlinedTextField(pin, { pin = it.filter(Char::isDigit).take(8) }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
                    modifier = Modifier.padding(top = 12.dp))
                model.error?.let { Text(it, color = Color(0xFFFF8A80), modifier = Modifier.padding(top = 8.dp)) }
            }
        },
        confirmButton = { TextButton(onClick = { model.pair(pin) }, enabled = pin.isNotEmpty() && !model.busy) { Text("Pair") } },
        dismissButton = { TextButton(onClick = { model.needsPin = false }) { Text("Cancel") } },
    )
}

@OptIn(ExperimentalLayoutApi::class, ExperimentalFoundationApi::class)
@Composable
fun ProfilesScreen() {
    val model = LocalModel.current
    var picking by remember { mutableStateOf<Profile?>(null) }
    Box(Modifier.fillMaxSize().safeDrawingPadding()) {
        TextButton(onClick = { model.forgetServer() }, modifier = Modifier.align(Alignment.TopEnd).padding(8.dp)) {
            Icon(Icons.Filled.SwapHoriz, null)
            Spacer(Modifier.width(6.dp))
            Text("Change server")
        }
        Column(
            Modifier.align(Alignment.Center).verticalScroll(rememberScrollState()).padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text("Who's watching?", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(28.dp))
            if (model.profiles.isEmpty() && model.busy) CircularProgressIndicator()
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(22.dp, Alignment.CenterHorizontally),
                verticalArrangement = Arrangement.spacedBy(22.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                model.profiles.forEach { p ->
                    Column(
                        Modifier.width(104.dp).clip(RoundedCornerShape(12.dp)).combinedClickable(
                            onClick = { model.select(p) },
                            onLongClick = { if (model.hasAvatars) picking = p },
                        ).padding(4.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Avatar(p, 92.dp)
                        Text(p.name, maxLines = 1, modifier = Modifier.padding(top = 8.dp))
                    }
                }
            }
        }
    }
    picking?.let { p -> AvatarPicker(p) { picking = null } }
}

private val avatars = listOf("fox", "panda", "owl", "cat", "dog", "bear", "rabbit", "penguin",
    "frog", "lion", "koala", "tiger", "dino", "monster", "robot", "astronaut")

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun AvatarPicker(profile: Profile, onDone: () -> Unit) {
    val model = LocalModel.current
    Dialog(onDismissRequest = onDone) {
        Column(
            Modifier.clip(RoundedCornerShape(20.dp)).background(Palette.surface).padding(20.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text("Picture for ${profile.name}", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(16.dp))
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterHorizontally),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                avatars.forEach { name ->
                    val selected = profile.avatar == name
                    AsyncImage(
                        model.api?.url("/avatars/$name.svg"), name,
                        modifier = Modifier.size(60.dp).clip(CircleShape)
                            .border(if (selected) 3.dp else 0.dp, if (selected) Color.White else Color.Transparent, CircleShape)
                            .clickable { model.setAvatar(name, profile); onDone() },
                    )
                }
                Box(
                    Modifier.size(60.dp).clip(CircleShape).background(parseColor(profile.color))
                        .clickable { model.setAvatar("", profile); onDone() },
                    contentAlignment = Alignment.Center,
                ) { Text(profile.name.take(1).uppercase(), fontWeight = FontWeight.Bold, color = Color.White) }
            }
        }
    }
}
