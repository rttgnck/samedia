# The ffmpeg audio decoder is found by reflection and calls into native code.
-keep class androidx.media3.decoder.ffmpeg.** { *; }
# kotlinx.serialization: keep the generated serializers of our models
-keepclassmembers class io.samedia.player.core.** {
    *** Companion;
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class io.samedia.player.core.**$$serializer { *; }
