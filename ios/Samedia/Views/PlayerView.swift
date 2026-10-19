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
    private var remoteObserver: Any?
    private var sendButton: UIButton?
    private var hideSendButton: Task<Void, Never>?
    private var inPictureInPicture = false

    func play(_ item: MediaItem, start: Double?, model: AppModel) {
        guard let api = model.api, player == nil else { return }
        self.model = model
        self.item = item
        finished = false
        Task { await open(item, start: start, api: api) }
    }

    /// Play something else now (a remote command), closing what is playing.
    func replace(with item: MediaItem, start: Double?, model: AppModel) {
        if let controller, controller.presentingViewController != nil {
            controller.dismiss(animated: false)
            close()
        }
        play(item, start: start, model: model)
    }

    /// A command from another device for what is playing here.
    func command(_ action: String, _ msg: [String: Any]) {
        guard let player else { return }
        let offset = decision?.startOffset ?? 0
        switch action {
        case "pause": player.pause()
        case "resume": player.play()
        case "toggle": player.rate == 0 ? player.play() : player.pause()
        case "seek":
            let to = (msg["position"] as? Double ?? 0) - offset
            player.seek(to: CMTime(seconds: max(0, to), preferredTimescale: 600))
        case "skip":
            let to = player.currentTime().seconds + (msg["delta"] as? Double ?? 0)
            player.seek(to: CMTime(seconds: max(0, to), preferredTimescale: 600))
        case "stop": controller?.dismiss(animated: true)
        default: break
        }
        reportRemote()
    }

    private func reportRemote() {
        guard let player, let item, let model else { return }
        let title = item.showTitle.map { "\($0) · \(item.title)" } ?? item.title
        model.remote.report(["item_id": item.id, "title": title, "kind": item.kind,
                             "position": player.currentTime().seconds + (decision?.startOffset ?? 0),
                             "duration": decision?.duration ?? item.duration ?? 0,
                             "playing": player.rate != 0, "profile_id": model.profile?.id ?? "default"])
    }

    /// Hand over to another screen: it carries on from here, this one stops.
    private func sendToAnotherScreen() {
        guard let model, let item, let player, let controller else { return }
        let at = max(0, player.currentTime().seconds + (decision?.startOffset ?? 0) - 2)
        Task {
            let players = await model.players()
            let sheet = UIAlertController(title: "Send to", message: players.isEmpty ? "No other Samedia screens are on." : nil,
                                          preferredStyle: .actionSheet)
            for p in players {
                sheet.addAction(UIAlertAction(title: p.name, style: .default) { _ in
                    Task {
                        if await model.playOn(p, item: item, at: at) { controller.dismiss(animated: true) }
                    }
                })
            }
            sheet.addAction(UIAlertAction(title: "Cancel", style: .cancel))
            sheet.popoverPresentationController?.sourceView = sendButton
            controller.present(sheet, animated: true)
        }
    }

    /// "Send to" floats over the player, showing for a few seconds after each touch.
    private func addSendButton(to controller: AVPlayerViewController) {
        guard model?.hasRemote == true else { return }
        var config = UIButton.Configuration.filled()
        config.image = UIImage(systemName: "tv.and.mediabox")
        config.title = "Send to"
        config.imagePadding = 8
        config.cornerStyle = .capsule
        config.baseBackgroundColor = UIColor(white: 0.15, alpha: 0.75)
        config.baseForegroundColor = .white
        let button = UIButton(configuration: config, primaryAction: UIAction { [weak self] _ in self?.sendToAnotherScreen() })
        button.translatesAutoresizingMaskIntoConstraints = false
        button.alpha = 0
        // On the window, not inside the player: the player cancels touches that start in its view
        guard let window = controller.view.window else { return }
        window.addSubview(button)
        NSLayoutConstraint.activate([
            button.trailingAnchor.constraint(equalTo: window.safeAreaLayoutGuide.trailingAnchor, constant: -20),
            button.topAnchor.constraint(equalTo: window.safeAreaLayoutGuide.topAnchor, constant: 64),
        ])
        sendButton = button
        let tap = UITapGestureRecognizer(target: self, action: #selector(touched))
        tap.cancelsTouchesInView = false
        tap.delegate = self
        controller.view.addGestureRecognizer(tap)
        touched()
    }

    @objc private func touched() {
        if let b = sendButton { b.superview?.bringSubviewToFront(b) }
        UIView.animate(withDuration: 0.2) { self.sendButton?.alpha = 1 }
        hideSendButton?.cancel()
        hideSendButton = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(4))
            guard !Task.isCancelled else { return }
            UIView.animate(withDuration: 0.4) { self?.sendButton?.alpha = 0 }
        }
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
            decision = d
            guard d.mode == "direct" || d.mode == "hls" else {
                reportError("needs \(d.mode), which this app can't play")
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
            topViewController()?.present(controller, animated: true) { [weak self] in self?.addSendButton(to: controller) }
            self.controller = controller

            try await waitUntilReady(playerItem)
            if let start, start > 1 {
                let at = CMTime(seconds: max(0, start - d.startOffset), preferredTimescale: 600)
                _ = await player.seek(to: at, toleranceBefore: .zero, toleranceAfter: .positiveInfinity)
            }
            player.play()
            observe(player, playerItem)
            remoteObserver = player.addPeriodicTimeObserver(forInterval: CMTime(seconds: 5, preferredTimescale: 1),
                                                            queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.reportRemote() }
            }
            await showSubtitles(d, language: language, api: api)
        } catch {
            reportError(error.localizedDescription)
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
            .sink { [weak self] status in
                if status == .paused { self?.report() }
                self?.reportRemote()
            }
            .store(in: &cancellables)
        playerItem.publisher(for: \.status)
            .sink { [weak self] status in
                if status == .failed {
                    self?.reportError(playerItem.error?.localizedDescription ?? "failed")
                    self?.alert("Playback stopped", playerItem.error?.localizedDescription ?? "")
                }
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

    /// Tell the server, so a title that failed can be found later (admin page).
    private func reportError(_ message: String) {
        guard let item, let api = model?.api else { return }
        var body: [String: Any] = ["kind": "playback_error", "item_id": item.id, "error": String(message.prefix(300))]
        if let decision { body["mode"] = decision.mode }
        Task { try? await api.postIgnoringReply("/api/v1/events", body) }
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
        if let remoteObserver { player?.removeTimeObserver(remoteObserver) }
        remoteObserver = nil
        hideSendButton?.cancel()
        sendButton?.removeFromSuperview()
        sendButton = nil
        model?.remote.report(nil)
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

extension PlayerCoordinator: UIGestureRecognizerDelegate {
    nonisolated func gestureRecognizer(_ g: UIGestureRecognizer, shouldRecognizeSimultaneouslyWith other: UIGestureRecognizer) -> Bool {
        true
    }
}

extension PlayerCoordinator: AVPlayerViewControllerDelegate {
    nonisolated func playerViewControllerWillStartPictureInPicture(_ playerViewController: AVPlayerViewController) {
        MainActor.assumeIsolated {
            inPictureInPicture = true
            sendButton?.isHidden = true
        }
    }

    nonisolated func playerViewControllerDidStopPictureInPicture(_ playerViewController: AVPlayerViewController) {
        MainActor.assumeIsolated {
            inPictureInPicture = false
            sendButton?.isHidden = false
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
