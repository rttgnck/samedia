import SwiftUI

/// "Who's watching?" — profiles this device may show (set per device in the Samedia admin page).
struct ProfilesView: View {
    @Environment(AppModel.self) private var model
    @State private var picking: Profile?

    var body: some View {
        VStack(spacing: 40) {
            Spacer()
            Text("Who's watching?").font(.system(size: 44, weight: .heavy))
            if model.profiles.isEmpty {
                if model.busy { ProgressView() } else if let e = model.error { Text(e).foregroundStyle(.secondary) }
            }
            CenteredFlow(spacing: 40) {
                ForEach(model.profiles) { p in
                    Button { model.select(p) } label: {
                        VStack(spacing: 12) {
                            AvatarView(profile: p, size: 140)
                                .overlay(Circle().stroke(model.profile?.id == p.id ? Color.white : .clear, lineWidth: 4))
                            Text(p.name).font(.title3.weight(.semibold))
                            if p.kids == true {
                                Text("KIDS").font(.caption.weight(.heavy)).padding(.horizontal, 10).padding(.vertical, 3)
                                    .background(.green, in: Capsule()).foregroundStyle(.black)
                            }
                        }
                    }
                    .buttonStyle(.plain)
                    .contextMenu {
                        if model.hasAvatars {
                            Button("Change picture", systemImage: "person.crop.circle") { picking = p }
                        }
                    }
                }
            }
            .frame(maxWidth: 1000)
            Spacer()
            Button("Use a different server") { model.forgetServer() }.font(.footnote)
        }
        .padding(32)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(RadialGradient(colors: [Color.accentColor.opacity(0.18), .black], center: .top, startRadius: 0, endRadius: 900))
        .sheet(item: $picking) { p in AvatarPicker(profile: p) }
        .task { if model.profiles.isEmpty { try? await model.loadProfiles() } }
    }
}

struct AvatarPicker: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let profile: Profile

    static let avatars = ["fox", "panda", "owl", "cat", "dog", "bear", "rabbit", "penguin",
                          "frog", "lion", "koala", "tiger", "dino", "monster", "robot", "astronaut"]

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 96), spacing: 20)], spacing: 20) {
                    ForEach(Self.avatars + [""], id: \.self) { a in
                        Button {
                            Task { await model.setAvatar(a, for: profile); dismiss() }
                        } label: {
                            AvatarView(profile: Profile(id: profile.id, name: profile.name, color: profile.color,
                                                        kids: profile.kids, avatar: a.isEmpty ? nil : a), size: 96)
                                .overlay(Circle().stroke((profile.avatar ?? "") == a ? Color.white : .clear, lineWidth: 4))
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(24)
            }
            .navigationTitle("Choose a picture for \(profile.name)")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
        }
    }
}
