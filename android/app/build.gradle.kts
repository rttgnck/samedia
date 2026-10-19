import org.gradle.api.file.DirectoryProperty
import org.gradle.api.file.FileSystemOperations
import javax.inject.Inject

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

android {
    namespace = "io.samedia.player"
    compileSdk = 36

    defaultConfig {
        applicationId = "io.samedia.player"
        minSdk = 26
        targetSdk = 36
        // The repo's VERSION; release builds add the build number (scripts/release.mjs)
        val version = (findProperty("samediaVersion") as String?) ?: rootProject.file("../VERSION").readText().trim()
        val build = (findProperty("samediaBuild") as String?) ?: "0"
        val parts = build.split(".")
        versionCode = maxOf(1, parts[0].toInt() * 10 + (parts.getOrNull(1)?.toInt() ?: 0))
        versionName = if (build == "0") version else "$version+$build"
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            // For installing straight onto your own devices (sideloading): the debug key
            // Android Studio makes on this computer. Not for a store release.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlin {
        compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) }
    }
    buildFeatures { compose = true }
    packaging { resources.excludes += "/META-INF/{AL2.0,LGPL2.1}" }
}

/** The TV app (repo's tv/ folder), bundled for Samedia on Google TV: one copy of the TV UI. */
abstract class TvWebTask : DefaultTask() {
    @get:InputDirectory abstract val source: DirectoryProperty
    @get:OutputDirectory abstract val outputDir: DirectoryProperty
    @get:Inject abstract val fs: FileSystemOperations

    @TaskAction
    fun copy() {
        fs.sync {
            from(source) { include("index.html", "icon.png", "css/**", "js/**") }
            into(outputDir.dir("tv"))
        }
    }
}

val tvWeb = tasks.register<TvWebTask>("tvWeb") {
    source.set(rootProject.layout.projectDirectory.dir("../tv"))
}

androidComponents {
    onVariants { variant ->
        variant.sources.assets?.addGeneratedSourceDirectory(tvWeb, TvWebTask::outputDir)
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2025.12.00")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended:1.7.8")
    implementation("androidx.activity:activity-compose:1.11.0")
    implementation("androidx.core:core-ktx:1.17.0")
    implementation("androidx.lifecycle:lifecycle-process:2.9.4")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.4")
    implementation("androidx.webkit:webkit:1.14.0")

    implementation("androidx.media3:media3-exoplayer:1.8.0")
    implementation("androidx.media3:media3-exoplayer-hls:1.8.0")
    implementation("androidx.media3:media3-ui:1.8.0")
    // Dolby Digital, DTS, TrueHD... decoded on the phone (most phones have no decoder for them)
    implementation("org.jellyfin.media3:media3-ffmpeg-decoder:1.8.0+1")

    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.9.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("io.coil-kt.coil3:coil-compose:3.3.0")
    implementation("io.coil-kt.coil3:coil-network-okhttp:3.3.0")
    implementation("io.coil-kt.coil3:coil-svg:3.3.0")
}
