import Foundation
import Network

/// Finds Samedia servers on the home network: nasOS advertises them as _samedia._tcp, and the
/// usual name (nasos.local) is tried directly as well.
@MainActor
final class Discovery: ObservableObject {
    struct Found: Identifiable, Hashable {
        let id: String
        let name: String
        let url: URL
    }

    @Published private(set) var servers: [Found] = []
    @Published private(set) var searching = false
    /// iOS is not letting the app look on the local network (Settings > Privacy > Local Network).
    @Published private(set) var blocked = false

    private var browser: NWBrowser?
    private var resolving: [String: NWConnection] = [:]
    private static let likelyNames = ["nasos.local"]

    func start() {
        stop()
        searching = true
        blocked = false
        let params = NWParameters()
        params.includePeerToPeer = false
        let browser = NWBrowser(for: .bonjour(type: "_samedia._tcp", domain: nil), using: params)
        browser.browseResultsChangedHandler = { [weak self] results, _ in
            Task { @MainActor in self?.update(results) }
        }
        browser.stateUpdateHandler = { [weak self] state in
            Task { @MainActor in self?.browserState(state) }
        }
        browser.start(queue: .main)
        self.browser = browser
        Task { await probeLikelyNames() }
        Task { @MainActor in
            try? await Task.sleep(for: .seconds(8))
            self.searching = false
        }
    }

    func stop() {
        browser?.cancel()
        browser = nil
        resolving.values.forEach { $0.cancel() }
        resolving.removeAll()
    }

    private func browserState(_ state: NWBrowser.State) {
        log("browser \(state)")
        switch state {
        case .waiting(let error), .failed(let error):
            // -65570: the user hasn't allowed (or has turned off) local network access
            if case let .dns(code) = error, code == -65570 { blocked = true }
            if case .failed = state { searching = false }
        case .ready:
            blocked = false
        default:
            break
        }
    }

    private func update(_ results: Set<NWBrowser.Result>) {
        log("browse results: \(results.map { "\($0.endpoint)" })")
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
                            self?.add(id: name, name: name.replacingOccurrences(of: "Samedia on ", with: ""), url: url)
                        }
                    }
                }
                connection.cancel()
            case .failed(let error), .waiting(let error):
                Task { @MainActor in
                    self?.log("resolve \(name) failed: \(error)")
                    self?.resolving[name] = nil
                }
                connection.cancel()
            default:
                break
            }
        }
        connection.start(queue: .main)
    }

    /// nasOS's usual host name, asked directly (works where Bonjour browsing doesn't).
    private func probeLikelyNames() async {
        for host in Self.likelyNames {
            guard let url = URL(string: "http://\(host):8097") else { continue }
            let client = APIClient(base: url)
            if let info = try? await client.get("/api/v1/info", as: ServerInfo.self) {
                log("found \(host) directly")
                add(id: "direct-\(host)", name: info.name, url: url)
            } else {
                log("no answer from \(host)")
            }
        }
    }

    private func add(id: String, name: String, url: URL) {
        // Same server found both ways: keep the one by address
        if servers.contains(where: { $0.url == url || $0.name == name }) { return }
        servers.append(Found(id: id, name: name, url: url))
    }

    private func log(_ text: String) {
        print("[Samedia] discovery: \(text)")
    }
}
