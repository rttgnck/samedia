import Foundation
import UIKit

enum APIError: LocalizedError {
    case http(Int, String)
    case unreachable(String)

    var errorDescription: String? {
        switch self {
        case .http(let code, let message): return message.isEmpty ? "The server answered \(code)." : message
        case .unreachable(let message): return message
        }
    }
}

/// Talks to one Samedia server as this device and the chosen profile.
final class APIClient {
    let base: URL
    var token: String
    var profileID: String?

    init(base: URL, token: String = "", profileID: String? = nil) {
        self.base = base
        self.token = token
        self.profileID = profileID
    }

    /// This device's id for the server (its per-device profile rules). Random, kept on the device.
    static let deviceID: String = {
        let key = "deviceID"
        if let id = UserDefaults.standard.string(forKey: key) { return id }
        let id = "ios-" + UUID().uuidString.lowercased().replacingOccurrences(of: "-", with: "").prefix(20)
        UserDefaults.standard.set(id, forKey: key)
        return id
    }()

    @MainActor static var deviceName: String {
        UIDevice.current.userInterfaceIdiom == .pad ? "iPad" : "iPhone"
    }

    static let session: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 15
        config.urlCache = URLCache(memoryCapacity: 16 << 20, diskCapacity: 256 << 20)
        return URLSession(configuration: config)
    }()

    /// Absolute URL for a server path; carries the token when the server has a PIN (for images
    /// and streams, which can't send headers).
    func url(_ path: String, query: [URLQueryItem] = []) -> URL {
        var components = URLComponents(url: base.appendingPathComponent(""), resolvingAgainstBaseURL: false)!
        let parts = path.split(separator: "?", maxSplits: 1).map(String.init)
        components.path = (components.path.hasSuffix("/") ? String(components.path.dropLast()) : components.path) + parts[0]
        var items = parts.count > 1 ? (URLComponents(string: "?" + parts[1])?.queryItems ?? []) : []
        items += query
        if !token.isEmpty { items.append(URLQueryItem(name: "t", value: token)) }
        components.queryItems = items.isEmpty ? nil : items
        return components.url!
    }

    func art(_ path: String?, width: Int) -> URL? {
        guard let path, !path.isEmpty else { return nil }
        return url(path, query: [URLQueryItem(name: "w", value: String(min(1920, width)))])
    }

    @MainActor
    private func request(_ path: String, method: String, body: Data?) async throws -> Data {
        var req = URLRequest(url: url(path))
        req.httpMethod = method
        req.setValue(Self.deviceID, forHTTPHeaderField: "X-Samedia-Device")
        req.setValue(Self.deviceName.addingPercentEncoding(withAllowedCharacters: .alphanumerics),
                     forHTTPHeaderField: "X-Samedia-Device-Name")
        if let profileID { req.setValue(profileID, forHTTPHeaderField: "X-Samedia-Profile") }
        if !token.isEmpty { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let body {
            req.httpBody = body
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let data: Data, response: URLResponse
        do {
            (data, response) = try await Self.session.data(for: req)
        } catch {
            throw APIError.unreachable("Can't reach the server (\(error.localizedDescription))")
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw APIError.http(status, detail ?? "")
        }
        return data
    }

    @MainActor
    func get<T: Decodable>(_ path: String, as type: T.Type = T.self) async throws -> T {
        try JSONDecoder().decode(T.self, from: try await request(path, method: "GET", body: nil))
    }

    @MainActor
    @discardableResult
    func post<T: Decodable>(_ path: String, _ body: [String: Any], as type: T.Type = T.self) async throws -> T {
        let data = try JSONSerialization.data(withJSONObject: body)
        return try JSONDecoder().decode(T.self, from: try await request(path, method: "POST", body: data))
    }

    @MainActor
    func postIgnoringReply(_ path: String, _ body: [String: Any]) async throws {
        _ = try await request(path, method: "POST", body: try JSONSerialization.data(withJSONObject: body))
    }

    // What this device plays: MP4 family directly; anything else as HLS segments (H.264 only in
    // MPEG-TS on Apple players), which seek well.
    static let capabilities: [String: Any] = [
        "containers": ["mp4", "mov", "m4v"],
        "video": ["h264", "hevc"],
        "audio": ["aac", "ac3", "eac3", "mp3", "alac"],
        "hls_video": ["h264"],
        "ts_video": ["h264"],
        "prefer_hls": true,
        "max_width": 3840,
        "dolby_vision": false,
    ]
}
