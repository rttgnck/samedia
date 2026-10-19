package io.samedia.player

import android.os.Bundle
import android.view.KeyEvent
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import io.samedia.player.core.AppModel
import io.samedia.player.ui.ConnectScreen
import io.samedia.player.ui.LocalModel
import io.samedia.player.ui.MainScreen
import io.samedia.player.ui.Palette
import io.samedia.player.ui.ProfilesScreen
import io.samedia.player.ui.RemoteKeys
import io.samedia.player.ui.SamediaTheme

class MainActivity : ComponentActivity() {
    private val model get() = (application as SamediaApp).model

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
        )
        setContent {
            SamediaTheme {
                CompositionLocalProvider(LocalModel provides model) {
                    Surface(Modifier.fillMaxSize(), color = Palette.bg, contentColor = Palette.text) {
                    Box(Modifier.fillMaxSize()) {
                        when (model.stage) {
                            AppModel.Stage.Connect -> ConnectScreen()
                            AppModel.Stage.Profiles -> ProfilesScreen()
                            AppModel.Stage.Main -> MainScreen()
                        }
                        AnimatedVisibility(
                            visible = model.toast != null,
                            enter = fadeIn(), exit = fadeOut(),
                            modifier = Modifier.align(Alignment.BottomCenter).navigationBarsPadding().padding(bottom = 96.dp),
                        ) {
                            Text(model.toast ?: "", color = Color.White,
                                modifier = Modifier.background(Color(0xE6232937), RoundedCornerShape(50))
                                    .padding(horizontal = 18.dp, vertical = 10.dp))
                        }
                    }
                    }
                }
            }
        }
    }

    // The phone's volume buttons turn the TV up and down while its remote is open
    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        val target = RemoteKeys.volumeTarget
        if (target != null && (keyCode == KeyEvent.KEYCODE_VOLUME_UP || keyCode == KeyEvent.KEYCODE_VOLUME_DOWN)) {
            RemoteKeys.volume(model, target, if (keyCode == KeyEvent.KEYCODE_VOLUME_UP) "up" else "down")
            return true
        }
        return super.onKeyDown(keyCode, event)
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent): Boolean {
        if (RemoteKeys.volumeTarget != null && (keyCode == KeyEvent.KEYCODE_VOLUME_UP || keyCode == KeyEvent.KEYCODE_VOLUME_DOWN)) return true
        return super.onKeyUp(keyCode, event)
    }
}
