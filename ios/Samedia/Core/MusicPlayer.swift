import AVFoundation
import Accelerate
import MediaPlayer
import MediaToolbox
import Observation
import UIKit

/// Music on the iPhone/iPad: a queue played with AVPlayer, in the background too, with the lock
/// screen's controls; tells the server what plays. The decoded sound goes to the visualizer
/// through an audio tap (Levels).
@MainActor
@Observable
final class MusicPlayer {
    // what AVPlayer plays as it is; the rest comes as MP3
    private static let plays: Set<String> = ["mp3", "aac", "alac", "flac", "pcm_s16le", "pcm_s24le", "ac3", "eac3"]

    private(set) var queue: [Track] = []
    private(set) var index = 0
    private(set) var playing = false
    var shuffle = false
    private(set) var position: Double = 0
    var current: Track? { queue.indices.contains(index) ? queue[index] : nil }

    private let player = AVPlayer()
    private weak var model: AppModel?
    private var timeObserver: Any?
    private var endObserver: NSObjectProtocol?
    private var playedSent: String?
    private var lastReport = Date.distantPast

    init() {
        timeObserver = player.addPeriodicTimeObserver(forInterval: CMTime(seconds: 0.5, preferredTimescale: 10), queue: .main) { [weak self] t in
            MainActor.assumeIsolated { self?.tick(t.seconds) }
        }
        let center = MPRemoteCommandCenter.shared()
        center.playCommand.addTarget { [weak self] _ in MainActor.assumeIsolated { self?.resume() }; return .success }
        center.pauseCommand.addTarget { [weak self] _ in MainActor.assumeIsolated { self?.pause() }; return .success }
        center.togglePlayPauseCommand.addTarget { [weak self] _ in MainActor.assumeIsolated { self?.toggle() }; return .success }
        center.nextTrackCommand.addTarget { [weak self] _ in MainActor.assumeIsolated { self?.next() }; return .success }
        center.previousTrackCommand.addTarget { [weak self] _ in MainActor.assumeIsolated { self?.previous() }; return .success }
        center.changePlaybackPositionCommand.addTarget { [weak self] e in
            if let e = e as? MPChangePlaybackPositionCommandEvent { MainActor.assumeIsolated { self?.seek(e.positionTime) } }
            return .success
        }
    }

    func play(_ tracks: [Track], start: Int = 0, shuffled: Bool = false, model: AppModel) {
        guard !tracks.isEmpty else { return }
        self.model = model
        var list = tracks
        var first = min(max(start, 0), tracks.count - 1)
        if shuffled {
            let chosen = list.remove(at: first)
            list.shuffle()
            list.insert(chosen, at: 0)
            first = 0
        }
        shuffle = shuffled
        queue = list
        index = first
        load()
    }

    private func load() {
        guard let t = current, let api = model?.api else { return }
        try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .default)
        try? AVAudioSession.sharedInstance().setActive(true)
        let format = Self.plays.contains(t.codec ?? "") ? [] : [URLQueryItem(name: "format", value: "mp3")]
        let item = AVPlayerItem(url: api.url("/api/v1/music/stream/\(t.id)", query: format))
        Levels.shared.attach(to: item)
        player.replaceCurrentItem(with: item)
        if let endObserver { NotificationCenter.default.removeObserver(endObserver) }
        endObserver = NotificationCenter.default.addObserver(forName: .AVPlayerItemDidPlayToEndTime, object: item, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.next(auto: true) }
        }
        playedSent = nil
        player.play()
        playing = true
        updateNowPlaying()
        report()
    }

    func toggle() { playing ? pause() : resume() }
    func pause() { player.pause(); playing = false; updateNowPlaying(); report() }
    func resume() { player.play(); playing = true; updateNowPlaying(); report() }
    func seek(_ s: Double) { player.seek(to: CMTime(seconds: max(0, s), preferredTimescale: 600)); position = s; updateNowPlaying() }

    func next(auto: Bool = false) {
        if index + 1 < queue.count { index += 1; load() } else if auto { stop() }
    }

    func previous() {
        if position > 4 || index == 0 { seek(0) } else { index -= 1; load() }
    }

    func stop() {
        player.pause()
        player.replaceCurrentItem(with: nil)
        queue = []
        index = 0
        playing = false
        MPNowPlayingInfoCenter.default().nowPlayingInfo = nil
        model?.remote.report(nil)
    }

    private func tick(_ seconds: Double) {
        guard seconds.isFinite, current != nil else { return }
        position = seconds
        if Date().timeIntervalSince(lastReport) > 5 { report() }
        // counts as played after 30 s
        if let t = current, playedSent != t.id, seconds > 30, let api = model?.api {
            playedSent = t.id
            Task { try? await api.postIgnoringReply("/api/v1/music/played", ["track_id": t.id]) }
        }
    }

    private func report() {
        lastReport = Date()
        guard let t = current, let model else { return }
        model.remote.report(["item_id": t.id, "title": t.title, "artist": t.artist ?? "", "kind": "track", "art": t.art ?? "",
                             "position": position, "duration": t.duration ?? 0, "playing": playing,
                             "profile_id": model.profile?.id ?? "default"])
    }

    private func updateNowPlaying() {
        guard let t = current else { return }
        var info: [String: Any] = [MPMediaItemPropertyTitle: t.title, MPMediaItemPropertyArtist: t.artist ?? "",
                                   MPMediaItemPropertyAlbumTitle: t.album ?? "",
                                   MPMediaItemPropertyPlaybackDuration: t.duration ?? 0,
                                   MPNowPlayingInfoPropertyElapsedPlaybackTime: position,
                                   MPNowPlayingInfoPropertyPlaybackRate: playing ? 1 : 0]
        MPNowPlayingInfoCenter.default().nowPlayingInfo = info
        if let url = model?.api?.art(t.art, width: 600) {
            Task {
                guard let image = await ImageCache.shared.image(for: url) else { return }
                info[MPMediaItemPropertyArtwork] = MPMediaItemArtwork(boundsSize: image.size) { _ in image }
                if self.current?.id == t.id { MPNowPlayingInfoCenter.default().nowPlayingInfo = info }
            }
        }
    }

    /// A command from another device; true when it was about music.
    func command(_ action: String, _ msg: [String: Any]) -> Bool {
        guard current != nil else { return false }
        switch action {
        case "toggle": toggle()
        case "pause": pause()
        case "resume": resume()
        case "next": next()
        case "previous": previous()
        case "seek": seek(msg["position"] as? Double ?? 0)
        case "skip": seek(position + (msg["delta"] as? Double ?? 0))
        case "stop": stop()
        default: return false
        }
        return true
    }
}

/// The sound as it plays, for the visualizer: an audio tap keeps the last samples; bands are
/// worked out on request. When there's nothing to read, a made-up groove keeps it moving.
final class Levels: @unchecked Sendable {
    static let shared = Levels()
    private let n = 2048
    private var ring = [Float](repeating: 0, count: 2048)
    private var pos = 0
    private var lastSound = Date.distantPast
    private var sampleRate: Double = 44100
    private let lock = NSLock()
    private var fake: Double = 0

    func attach(to item: AVPlayerItem) {
        Task {
            guard let track = try? await item.asset.loadTracks(withMediaType: .audio).first else { return }
            var callbacks = MTAudioProcessingTapCallbacks(
                version: kMTAudioProcessingTapCallbacksVersion_0, clientInfo: nil,
                init: { _, _, storage in storage.pointee = nil },
                finalize: { _ in },
                prepare: { _, _, format in Levels.shared.sampleRate = format.pointee.mSampleRate },
                unprepare: { _ in },
                process: { tap, frames, _, buffers, framesOut, flagsOut in
                    guard MTAudioProcessingTapGetSourceAudio(tap, frames, buffers, flagsOut, nil, framesOut) == noErr else { return }
                    let list = UnsafeMutableAudioBufferListPointer(buffers)
                    guard let first = list.first, let data = first.mData else { return }
                    let count = Int(first.mDataByteSize) / MemoryLayout<Float>.size
                    Levels.shared.push(data.assumingMemoryBound(to: Float.self), count)
                })
            var tap: MTAudioProcessingTap?
            guard MTAudioProcessingTapCreate(kCFAllocatorDefault, &callbacks, kMTAudioProcessingTapCreationFlag_PostEffects, &tap) == noErr,
                  let tap else { return }
            let params = AVMutableAudioMixInputParameters(track: track)
            params.audioTapProcessor = tap
            let mix = AVMutableAudioMix()
            mix.inputParameters = [params]
            await MainActor.run { item.audioMix = mix }
        }
    }

    func push(_ p: UnsafeMutablePointer<Float>, _ count: Int) {
        lock.lock(); defer { lock.unlock() }
        var loud: Float = 0
        for i in 0..<count {
            ring[pos] = p[i]
            pos = (pos + 1) % n
            loud = max(loud, abs(p[i]))
        }
        if loud > 0.002 { lastSound = Date() }
    }

    private func samples(_ m: Int) -> [Float] {
        lock.lock(); defer { lock.unlock() }
        let start = (pos - m + n) % n
        return (0..<m).map { ring[(start + $0) % n] }
    }

    private func live(_ playing: Bool) -> Bool { playing && Date().timeIntervalSince(lastSound) < 1.5 }

    func bands(_ count: Int, playing: Bool) -> [Float] {
        guard live(playing) else { return made(count, playing) }
        let size = 2048
        var re = samples(size)
        var window = [Float](repeating: 0, count: size)
        vDSP_hann_window(&window, vDSP_Length(size), Int32(vDSP_HANN_NORM))
        vDSP_vmul(re, 1, window, 1, &re, 1, vDSP_Length(size))
        var im = [Float](repeating: 0, count: size)
        guard let dft = vDSP_DFT_zop_CreateSetup(nil, vDSP_Length(size), .FORWARD) else { return made(count, playing) }
        var outRe = [Float](repeating: 0, count: size), outIm = [Float](repeating: 0, count: size)
        vDSP_DFT_Execute(dft, re, im, &outRe, &outIm)
        vDSP_DFT_DestroySetup(dft)
        let nyq = sampleRate / 2
        return (0..<count).map { b in
            let lo = 30 * pow(16000 / 30, Double(b) / Double(count)), hi = 30 * pow(16000 / 30, Double(b + 1) / Double(count))
            let a = min(max(Int(lo / nyq * Double(size / 2)), 1), size / 2 - 1)
            let z = min(max(a + 1, Int(hi / nyq * Double(size / 2))), size / 2)
            var m: Float = 0
            for k in a..<z { m = max(m, (outRe[k] * outRe[k] + outIm[k] * outIm[k]).squareRoot()) }
            let db = 20 * log10(m / Float(size / 4) + 1e-6)
            return min(max((db + 60) / 60, 0), 1)
        }
    }

    func wave(_ count: Int, playing: Bool) -> [Float] {
        guard live(playing) else {
            let amp = playing ? 0.35 + 0.25 * sin(fake * 2.1) : 0.02
            return (0..<count).map { k in
                let t = Double(k) / Double(count)
                return Float(amp * (sin(t * 22 + fake * 9) * 0.6 + sin(t * 57 - fake * 13) * 0.3 + sin(t * 5 + fake) * 0.1))
            }
        }
        let s = samples(1024)
        return (0..<count).map { s[$0 * s.count / count] }
    }

    private func made(_ count: Int, _ playing: Bool) -> [Float] {
        fake += playing ? 0.016 : 0.004
        let beat = pow(max(0, sin(fake * 7.5)), 6)
        return (0..<count).map { q in
            let x = Double(q) / Double(count)
            guard playing else { return 0.04 }
            return Float(min(1, max(0, 0.55 * (1 - x) * (0.6 + 0.4 * sin(fake * 3 + Double(q) * 0.7)) +
                0.25 * sin(fake * 5.3 + Double(q) * 1.9) * sin(fake * 1.7 + x * 6) + beat * (1 - x) * 0.5)))
        }
    }
}
