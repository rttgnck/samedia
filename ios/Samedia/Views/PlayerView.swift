import AVFoundation
import AVKit
import Combine
import UIKit

/// Plays a movie or episode in the system player and keeps the server up to date with where the
/// profile is in it (every 10 s, on pause and on close), so any device can pick up from there.
@MainActor
final class PlayerCoordinator: NSObject {
    private var player: AVPlayer?
    private var controller: SamediaPlayerController?
    private var item: MediaItem?
    private var decision: PlaybackDecision?
    private weak var model: AppModel?
    private var timeObserver: Any?
    private var observers: [NSObjectProtocol] = []
    private var cancellables: Set<AnyCancellable> = []
    private var finished = false
    private var subtitles: SubtitleOverlay?
    private var inPictureInPicture = false

    func play(_ item: MediaItem, start: Double?, model: AppModel) {
        guard let api = model.api, player == nil else { return }
        self.model = model
        self.item = item
        finished = false
        Task { await open(item, start: start, api: api) }
    }

    private func open(_ item: MediaItem, start: Double?, api: APIClient) async {
        do {
            try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .moviePlayback)
            let session = "ios-" + APIClient.deviceID.suffix(8) + "-" + String(Int(Date().timeIntervalSince1970) % 100000)
            let language = Locale.current.language.languageCode?.identifier ?? "en"
            let d = try await api.post("/api/v1/items/\(item.id)/playback",
                                       ["capabilities": APIClient.capabilities, "start": start ?? 0,
                                        "session": session, "prefer_audio_lang": language,
                                        "subtitle_language": language],
                                       as: PlaybackDecision.self)
            guard d.mode == "direct" || d.mode == "hls" else {
                alert("Can't play this here",
                      "This video has to be converted on the server, which iPhone and iPad can't play yet.")
                return
            }
            decision = d
            let playerItem = AVPlayerItem(url: api.url(d.url))
            playerItem.externalMetadata = metadata(for: item)
            let player = AVPlayer(playerItem: playerItem)
            self.player = player

            let controller = SamediaPlayerController()
            controller.player = player
            controller.allowsPictureInPicturePlayback = true
            controller.modalPresentationStyle = .fullScreen
            controller.delegate = self
            controller.onClose = { [weak self] in
                guard let self, !self.inPictureInPicture else { return }   // still playing in the corner
                self.close()
            }
            topViewController()?.present(controller, animated: true)
            self.controller = controller

            try await waitUntilReady(playerItem)
            print("[Samedia] ready, mode \(d.mode), start \(start ?? 0)")
            if let start, start > 1 {
                let at = CMTime(seconds: max(0, start - d.startOffset), preferredTimescale: 600)
                _ = await player.seek(to: at, toleranceBefore: .zero, toleranceAfter: .positiveInfinity)
            }
            player.play()
            observe(player, playerItem)
            await showSubtitles(d, language: language, api: api)
        } catch {
            close(report: false)
            alert("Playback failed", error.localizedDescription)
        }
    }

    /// Subtitles that come on by themselves: full ones for audio in another language, else only
    /// the foreign-language parts (when the film has some).
    private func showSubtitles(_ d: PlaybackDecision, language: String, api: APIClient) async {
        guard let track = d.automaticSubtitles(language: language), let path = track.url,
              let player, let controller else { return }
        guard let (data, _) = try? await APIClient.session.data(from: api.url(path)),
              let text = String(data: data, encoding: .utf8) else { return }
        let cues = WebVTT.parse(text)
        guard !cues.isEmpty, self.player === player else { return }
        let overlay = SubtitleOverlay()
        overlay.attach(to: controller, player: player, cues: cues, offset: d.startOffset)
        subtitles = overlay
        print("[Samedia] subtitles: \(track.label), \(cues.count) lines")
    }

    private func waitUntilReady(_ item: AVPlayerItem) async throws {
        let deadline = Date().addingTimeInterval(45)
        while Date() < deadline {
            switch item.status {
            case .readyToPlay: return
            case .failed: throw item.error ?? APIError.unreachable("The video could not be opened.")
            default: try await Task.sleep(for: .milliseconds(100))
            }
        }
        throw APIError.unreachable("The video took too long to start.")
    }

    private func observe(_ player: AVPlayer, _ playerItem: AVPlayerItem) {
        timeObserver = player.addPeriodicTimeObserver(forInterval: CMTime(seconds: 10, preferredTimescale: 1),
                                                      queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.report() }
        }
        player.publisher(for: \.timeControlStatus)
            .removeDuplicates()
            .sink { [weak self] status in if status == .paused { self?.report() } }
            .store(in: &cancellables)
        playerItem.publisher(for: \.status)
            .sink { [weak self] status in
                if status == .failed { self?.alert("Playback stopped", playerItem.error?.localizedDescription ?? "") }
            }
            .store(in: &cancellables)
        observers.append(NotificationCenter.default.addObserver(forName: .AVPlayerItemDidPlayToEndTime, object: playerItem,
                                                                queue: .main) { [weak self] _ in
            MainActor.assumeIsolated {
                self?.report(ended: true)
                self?.controller?.dismiss(animated: true)
            }
        })
    }

    /// Tell the server where we are (it marks the title watched near the end).
    private func report(ended: Bool = false) {
        guard let player, let item, let decision, let api = model?.api else { return }
        let duration = decision.duration ?? item.duration ?? player.currentItem?.duration.seconds ?? 0
        var position = player.currentTime().seconds + decision.startOffset
        if ended, duration > 0 { position = duration }
        guard position.isFinite, position > 0 else { return }
        Task { try? await api.postIgnoringReply("/api/v1/items/\(item.id)/progress",
                                                ["position": position, "duration": duration]) }
    }

    private func close(report send: Bool = true) {
        guard !finished else { return }
        finished = true
        if send { report() }
        if let timeObserver { player?.removeTimeObserver(timeObserver) }
        timeObserver = nil
        subtitles?.detach()
        subtitles = nil
        observers.forEach(NotificationCenter.default.removeObserver)
        observers = []
        cancellables = []
        player?.pause()
        player = nil
        controller = nil
        decision = nil
        // Let the server save the last position before the screens reload
        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(400))
            self.model?.refreshToken += 1
        }
    }

    private func metadata(for item: MediaItem) -> [AVMetadataItem] {
        func entry(_ id: AVMetadataIdentifier, _ value: String?) -> AVMetadataItem? {
            guard let value else { return nil }
            let m = AVMutableMetadataItem()
            m.identifier = id
            m.value = value as NSString
            m.extendedLanguageTag = "und"
            return m
        }
        let title = item.showTitle.map { "\($0) · \(item.episodeLabel ?? "")" }
        return [entry(.commonIdentifierTitle, item.title), entry(.iTunesMetadataTrackSubTitle, title),
                entry(.commonIdentifierDescription, item.plot)].compactMap { $0 }
    }

    private func alert(_ title: String, _ message: String) {
        let a = UIAlertController(title: title, message: message, preferredStyle: .alert)
        a.addAction(UIAlertAction(title: "OK", style: .default) { [weak self] _ in self?.controller?.dismiss(animated: true) })
        topViewController()?.present(a, animated: true)
    }

    private func topViewController() -> UIViewController? {
        let scene = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
            .first { $0.activationState == .foregroundActive } ?? UIApplication.shared.connectedScenes.first as? UIWindowScene
        var top = scene?.windows.first { $0.isKeyWindow }?.rootViewController
        while let presented = top?.presentedViewController { top = presented }
        return top
    }
}

extension PlayerCoordinator: AVPlayerViewControllerDelegate {
    nonisolated func playerViewControllerWillStartPictureInPicture(_ playerViewController: AVPlayerViewController) {
        MainActor.assumeIsolated { inPictureInPicture = true }
    }

    nonisolated func playerViewControllerDidStopPictureInPicture(_ playerViewController: AVPlayerViewController) {
        MainActor.assumeIsolated {
            inPictureInPicture = false
            if controller?.presentingViewController == nil { close() }      // closed from the corner
        }
    }

    nonisolated func playerViewController(_ playerViewController: AVPlayerViewController,
                                          restoreUserInterfaceForPictureInPictureStopWithCompletionHandler completion: @escaping (Bool) -> Void) {
        MainActor.assumeIsolated {
            guard let controller, controller.presentingViewController == nil, let top = topViewController() else {
                completion(true)
                return
            }
            top.present(controller, animated: true) { completion(true) }
        }
    }
}

/// The system player, telling us when it goes away.
final class SamediaPlayerController: AVPlayerViewController {
    var onClose: (() -> Void)?

    override func viewDidDisappear(_ animated: Bool) {
        super.viewDidDisappear(animated)
        if isBeingDismissed || presentingViewController == nil { onClose?() }
    }
}
