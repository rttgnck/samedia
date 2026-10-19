package io.samedia.player.player

import androidx.media3.common.C
import androidx.media3.exoplayer.audio.TeeAudioProcessor
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * What the music sounds like right now, for the visualizer: the decoded audio passes through
 * (TeeAudioProcessor), the last 2048 samples are kept, and the screen asks for bands (0..1,
 * log-spaced 30 Hz – 16 kHz) or the wave (-1..1). When there's no sound to read, a made-up
 * groove keeps the screen moving.
 */
object Spectrum {
    private const val N = 2048
    private val ring = FloatArray(N)
    @Volatile private var pos = 0
    @Volatile private var sampleRate = 44100
    @Volatile private var channels = 2
    @Volatile private var pcm16 = true
    @Volatile private var lastAudioAt = 0L
    private var fake = 0.0

    val sink = object : TeeAudioProcessor.AudioBufferSink {
        override fun flush(sampleRateHz: Int, channelCount: Int, encoding: Int) {
            sampleRate = sampleRateHz
            channels = max(1, channelCount)
            pcm16 = encoding == C.ENCODING_PCM_16BIT
        }

        override fun handleBuffer(buffer: ByteBuffer) {
            if (!pcm16) return
            val b = buffer.duplicate().order(ByteOrder.LITTLE_ENDIAN)
            val frames = b.remaining() / (2 * channels)
            var loud = 0f
            for (f in 0 until frames) {
                var s = 0f
                for (c in 0 until channels) s += b.short.toFloat()
                val v = s / channels / 32768f
                ring[pos] = v
                pos = (pos + 1) % N
                loud = max(loud, kotlin.math.abs(v))
            }
            if (loud > 0.002f) lastAudioAt = System.currentTimeMillis()
        }
    }

    private fun live(playing: Boolean) = playing && System.currentTimeMillis() - lastAudioAt < 1500

    private fun samples(n: Int): FloatArray {
        val out = FloatArray(n)
        val start = (pos - n + N) % N
        for (i in 0 until n) out[i] = ring[(start + i) % N]
        return out
    }

    fun bands(n: Int, playing: Boolean): FloatArray {
        if (!live(playing)) return made(n, playing)
        val size = 2048
        val re = samples(size)
        val im = FloatArray(size)
        for (i in 0 until size) re[i] *= (0.5 - 0.5 * cos(2 * PI * i / (size - 1))).toFloat()   // Hann
        fft(re, im)
        val out = FloatArray(n)
        val nyq = sampleRate / 2.0
        for (b in 0 until n) {
            val lo = 30 * (16000.0 / 30).pow(b.toDouble() / n)
            val hi = 30 * (16000.0 / 30).pow((b + 1.0) / n)
            val a = (lo / nyq * size / 2).toInt().coerceIn(1, size / 2 - 1)
            val z = max(a + 1, (hi / nyq * size / 2).toInt()).coerceAtMost(size / 2)
            var m = 0f
            for (k in a until z) m = max(m, sqrt(re[k] * re[k] + im[k] * im[k]))
            val db = 20 * log10(m / (size / 4f) + 1e-6f)
            out[b] = ((db + 60) / 60f).coerceIn(0f, 1f)
        }
        return out
    }

    fun wave(n: Int, playing: Boolean): FloatArray {
        if (!live(playing)) {
            val amp = if (playing) 0.35 + 0.25 * sin(fake * 2.1) else 0.02
            return FloatArray(n) { k ->
                val t = k.toDouble() / n
                (amp * (sin(t * 22 + fake * 9) * 0.6 + sin(t * 57 - fake * 13) * 0.3 + sin(t * 5 + fake) * 0.1)).toFloat()
            }
        }
        val s = samples(1024)
        return FloatArray(n) { i -> s[i * s.size / n] }
    }

    private fun made(n: Int, playing: Boolean): FloatArray {
        fake += if (playing) 0.016 else 0.004
        val beat = max(0.0, sin(fake * 7.5)).pow(6)
        return FloatArray(n) { q ->
            val x = q.toDouble() / n
            if (!playing) 0.04f else min(1.0, max(0.0, 0.55 * (1 - x) * (0.6 + 0.4 * sin(fake * 3 + q * 0.7)) +
                0.25 * sin(fake * 5.3 + q * 1.9) * sin(fake * 1.7 + x * 6) + beat * (1 - x) * 0.5)).toFloat()
        }
    }

    /** In-place radix-2 FFT. */
    private fun fft(re: FloatArray, im: FloatArray) {
        val n = re.size
        var j = 0
        for (i in 1 until n) {
            var bit = n shr 1
            while (j and bit != 0) { j = j xor bit; bit = bit shr 1 }
            j = j xor bit
            if (i < j) {
                val tr = re[i]; re[i] = re[j]; re[j] = tr
                val ti = im[i]; im[i] = im[j]; im[j] = ti
            }
        }
        var len = 2
        while (len <= n) {
            val ang = -2 * PI / len
            val wr = cos(ang).toFloat(); val wi = sin(ang).toFloat()
            var i = 0
            while (i < n) {
                var cr = 1f; var ci = 0f
                for (k in 0 until len / 2) {
                    val ur = re[i + k]; val ui = im[i + k]
                    val vr = re[i + k + len / 2] * cr - im[i + k + len / 2] * ci
                    val vi = re[i + k + len / 2] * ci + im[i + k + len / 2] * cr
                    re[i + k] = ur + vr; im[i + k] = ui + vi
                    re[i + k + len / 2] = ur - vr; im[i + k + len / 2] = ui - vi
                    val nr = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = nr
                }
                i += len
            }
            len = len shl 1
        }
    }
}
