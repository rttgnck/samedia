import AVKit
import UIKit

/// WebVTT cues (the server converts every text subtitle to WebVTT).
struct SubtitleCue {
    let start: Double
    let end: Double
    let text: String
}

enum WebVTT {
    static func parse(_ text: String) -> [SubtitleCue] {
        var cues: [SubtitleCue] = []
        let blocks = text.replacingOccurrences(of: "\r\n", with: "\n").components(separatedBy: "\n\n")
        for block in blocks {
            let lines = block.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
            guard let timing = lines.firstIndex(where: { $0.contains("-->") }) else { continue }
            let parts = lines[timing].components(separatedBy: "-->")
            guard parts.count == 2, let start = seconds(parts[0]),
                  let end = seconds(parts[1].trimmingCharacters(in: .whitespaces).components(separatedBy: " ")[0]) else { continue }
            let body = lines[(timing + 1)...].joined(separator: "\n")
                .replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression)
                .replacingOccurrences(of: "&amp;", with: "&").replacingOccurrences(of: "&lt;", with: "<")
                .replacingOccurrences(of: "&gt;", with: ">").replacingOccurrences(of: "&nbsp;", with: " ")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            if !body.isEmpty { cues.append(SubtitleCue(start: start, end: end, text: body)) }
        }
        return cues.sorted { $0.start < $1.start }
    }

    /// "01:02:03.456" or "02:03.456" -> seconds
    static func seconds(_ s: String) -> Double? {
        let parts = s.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: ",", with: ".").split(separator: ":")
        guard (2...3).contains(parts.count) else { return nil }
        var total = 0.0
        for p in parts {
            guard let v = Double(p) else { return nil }
            total = total * 60 + v
        }
        return total
    }
}

/// Draws subtitles over the system player's picture and keeps them in time.
@MainActor
final class SubtitleOverlay {
    private let label = PaddedLabel()
    private var cues: [SubtitleCue] = []
    private var observer: Any?
    private weak var player: AVPlayer?

    func attach(to controller: AVPlayerViewController, player: AVPlayer, cues: [SubtitleCue], offset: Double) {
        self.cues = cues
        self.player = player
        guard let overlay = controller.contentOverlayView else { return }
        label.numberOfLines = 0
        label.textAlignment = .center
        label.textColor = .white
        label.font = .systemFont(ofSize: 30, weight: .semibold)
        label.backgroundColor = UIColor.black.withAlphaComponent(0.55)
        label.layer.cornerRadius = 8
        label.layer.masksToBounds = true
        label.isHidden = true
        label.translatesAutoresizingMaskIntoConstraints = false
        overlay.addSubview(label)
        NSLayoutConstraint.activate([
            label.centerXAnchor.constraint(equalTo: overlay.centerXAnchor),
            label.bottomAnchor.constraint(equalTo: overlay.safeAreaLayoutGuide.bottomAnchor, constant: -48),
            label.widthAnchor.constraint(lessThanOrEqualTo: overlay.widthAnchor, multiplier: 0.86),
        ])
        observer = player.addPeriodicTimeObserver(forInterval: CMTime(value: 1, timescale: 10), queue: .main) { [weak self] time in
            MainActor.assumeIsolated { self?.show(at: time.seconds + offset) }
        }
    }

    private func show(at t: Double) {
        // last cue starting at or before t, if it is still showing
        var lo = 0, hi = cues.count - 1, found: Int?
        while lo <= hi {
            let mid = (lo + hi) / 2
            if cues[mid].start <= t { found = mid; lo = mid + 1 } else { hi = mid - 1 }
        }
        let text = found.flatMap { i in
            cues[max(0, i - 2)...i].filter { $0.end > t }.map(\.text).joined(separator: "\n")
        } ?? ""
        label.isHidden = text.isEmpty
        if label.text != text { label.text = text }
    }

    func detach() {
        if let observer { player?.removeTimeObserver(observer) }
        observer = nil
        label.removeFromSuperview()
    }
}

final class PaddedLabel: UILabel {
    override func drawText(in rect: CGRect) { super.drawText(in: rect.insetBy(dx: 14, dy: 6)) }
    override var intrinsicContentSize: CGSize {
        let s = super.intrinsicContentSize
        return CGSize(width: s.width + 28, height: s.height + 12)
    }
}
