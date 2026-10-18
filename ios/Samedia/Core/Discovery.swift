import Foundation
import Network

/// Finds Samedia servers on the home network (nasOS advertises them as _samedia._tcp).
@MainActor
final class Discovery: ObservableObject {
    struct Found: Identifiable, Hashable {
        let id: String          // service name
        let name: String
        let url: URL
    }

    @Published private(set) var servers: [Found] = []
    @Published private(set) var searching = false

    private var browser: NWBrowser?
    private var resolving: [String: NWConnection] = [:]

    func start() {
        stop()
        searching = true
        let params = NWParameters()
        params.includePeerToPeer = false
        let browser = NWBrowser(for: .bonjour(type: "_samedia._tcp", domain: nil), using: params)
        browser.browseResultsChangedHandler = { [weak self] results, _ in
            Task { @MainActor in self?.update(results) }
        }
        browser.stateUpdateHandler = { [weak self] state in
            if case .failed = state { Task { @MainActor in self?.searching = false } }
        }
        browser.start(queue: .main)
        self.browser = browser
        // Browsing goes on in the background; the spinner only shows for the first few seconds
        Task { @MainActor in
            try? await Task.sleep(for: .seconds(6))
            self.searching = false
        }
    }

    func stop() {
        browser?.cancel()
        browser = nil
        resolving.values.forEach { $0.cancel() }
        resolving.removeAll()
    }

    private func update(_ results: Set<NWBrowser.Result>) {
        for result in results {
            guard case let .service(name, _, _, _) = result.endpoint,
                  !servers.contains(where: { $0.id == name }), resolving[name] == nil else { continue }
            resolve(name: name, endpoint: result.endpoint)
        }
    }

    /// Connects once to learn the service's IPv4 address and port.
    private func resolve(name: String, endpoint: NWEndpoint) {
        let params = NWParameters.tcp
        if let ip = params.defaultProtocolStack.internetProtocol as? NWProtocolIP.Options { ip.version = .v4 }
        let connection = NWConnection(to: endpoint, using: params)
        resolving[name] = connection
        connection.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                if case let .hostPort(host, port) = connection.currentPath?.remoteEndpoint {
                    var address = "\(host)"
                    if let zone = address.firstIndex(of: "%") { address = String(address[..<zone]) }
                    if let url = URL(string: "http://\(address):\(port.rawValue)") {
                        Task { @MainActor in
                            guard let self else { return }
                            let label = name.replacingOccurrences(of: "Samedia on ", with: "")
                            if !self.servers.contains(where: { $0.url == url }) {
                                self.servers.append(Found(id: name, name: label, url: url))
                            }
                        }
                    }
                }
                connection.cancel()
            case .failed, .cancelled:
                Task { @MainActor in self?.resolving[name] = nil }
            default:
                break
            }
        }
        connection.start(queue: .main)
    }
}
