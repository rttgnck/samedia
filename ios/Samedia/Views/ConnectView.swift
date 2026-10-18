import SwiftUI

/// First run: find the server on the home network, or type its address.
struct ConnectView: View {
    @Environment(AppModel.self) private var model
    @StateObject private var discovery = Discovery()
    @State private var address = ""
    @State private var pin = ""

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    VStack(spacing: 10) {
                        Image("Logo")
                            .resizable().frame(width: 84, height: 84).clipShape(RoundedRectangle(cornerRadius: 19))
                        Text("Samedia").font(.largeTitle.bold())
                        Text("Your movies and shows from your nasOS server.").foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity).padding(.vertical, 12)
                }
                .listRowBackground(Color.clear)

                if model.needsPin {
                    Section("This server has a PIN") {
                        SecureField("PIN", text: $pin).keyboardType(.numberPad)
                        Button("Pair") { Task { await model.pair(pin: pin) } }.disabled(pin.isEmpty || model.busy)
                    }
                } else {
                    Section {
                        if discovery.blocked && discovery.servers.isEmpty {
                            VStack(alignment: .leading, spacing: 8) {
                                Label("Samedia isn't allowed to look on your network", systemImage: "wifi.exclamationmark")
                                    .foregroundStyle(.orange)
                                Text("Turn on Local Network for Samedia in Settings, or enter the address below.")
                                    .font(.footnote).foregroundStyle(.secondary)
                                Button("Open Settings") {
                                    if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
                                }
                            }
                        } else if discovery.servers.isEmpty {
                            HStack {
                                if discovery.searching { ProgressView().padding(.trailing, 6) }
                                Text(discovery.searching ? "Looking on your network…" : "No server found automatically.")
                                    .foregroundStyle(.secondary)
                            }
                        }
                        ForEach(discovery.servers) { server in
                            Button {
                                Task { await model.connect(to: server.url) }
                            } label: {
                                HStack {
                                    Image(systemName: "server.rack").foregroundStyle(.tint)
                                    VStack(alignment: .leading) {
                                        Text(server.name).foregroundStyle(.primary)
                                        Text(server.url.absoluteString).font(.caption).foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                    Image(systemName: "chevron.right").foregroundStyle(.tertiary)
                                }
                            }
                            .disabled(model.busy)
                        }
                    } header: {
                        Text("On your network")
                    }

                    Section {
                        TextField("nasos.local or 192.168.1.20", text: $address)
                            .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                            .onSubmit(connectTyped)
                        Button("Connect", action: connectTyped).disabled(AppModel.normalize(address) == nil || model.busy)
                    } header: {
                        Text("Or enter the address")
                    } footer: {
                        Text("Samedia runs on port 8097 of your nasOS server.")
                    }
                }

                if let error = model.error {
                    Section { Text(error).foregroundStyle(.red) }
                }
            }
            .overlay { if model.busy { ProgressView().controlSize(.large) } }
            .frame(maxWidth: 640)
            .frame(maxWidth: .infinity)
        }
        .onAppear { discovery.start() }
        .refreshable { discovery.start() }
        .onDisappear { discovery.stop() }
    }

    private func connectTyped() {
        guard let url = AppModel.normalize(address) else { return }
        Task { await model.connect(to: url) }
    }
}
