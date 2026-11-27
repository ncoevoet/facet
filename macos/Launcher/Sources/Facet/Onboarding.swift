import AppKit
import FacetCore
import Observation
import SwiftUI

/// The window's own state. A class rather than @State: the Command Line Tools ship no
/// SwiftUI macro plugin, and the app must build without Xcode.
@MainActor
@Observable
final class OnboardingFlow {
    enum Step: Int, CaseIterable {
        case welcome, thisMac, folders, setup, ready
    }

    var step: Step = .welcome
    var scanNow = true
    var opening = false
}

/// First-run window. Setup starts the moment it opens and runs in the background, so
/// picking folders never waits on a download, and Continue waits only where it must.
struct OnboardingView: View {
    typealias Step = OnboardingFlow.Step

    let model: AppModel
    let flow: OnboardingFlow
    let onFinish: (_ scanNow: Bool) -> Void

    private var step: Step { flow.step }

    var body: some View {
        VStack(spacing: 0) {
            StepDots(count: Step.allCases.count, current: step.rawValue)
                .padding(.top, 18)
            Group {
                switch step {
                case .welcome: WelcomeStep()
                case .thisMac: ThisMacStep(model: model)
                case .folders: FoldersStep(model: model)
                case .setup: SetupStep(model: model)
                case .ready: ReadyStep(model: model, flow: flow)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .padding(.horizontal, 40)
            .transition(.opacity)
            Divider()
            footer
        }
        .frame(width: 640, height: 500)
        .animation(.easeInOut(duration: 0.2), value: step)
        .task {
            await model.refreshFolders()
            if case .idle = model.setup { await model.runSetup() }
        }
        // The viewer takes a while to start: begin once setup is done and the folders are
        // chosen, so it is usually up by the time Open Facet is pressed.
        .task(id: canServe) {
            if canServe { await model.startServer() }
        }
    }

    private var canServe: Bool { model.isSetUp && step.rawValue > Step.folders.rawValue }

    private var footer: some View {
        HStack {
            if step != .welcome {
                Button(L10n.t("onboarding.back")) { move(-1) }
            }
            Spacer()
            if step == .ready {
                Button(L10n.t("onboarding.open_facet")) {
                    flow.opening = true
                    onFinish(flow.scanNow && !model.folders.isEmpty)
                }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
                .disabled(flow.opening)
            } else {
                Button(step == .folders && model.folders.isEmpty ? L10n.t("onboarding.skip") : L10n.t("onboarding.continue")) {
                    move(1)
                }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
                .disabled(step == .setup && !model.isSetUp)
            }
        }
        .padding(16)
    }

    private func move(_ delta: Int) {
        if let next = Step(rawValue: step.rawValue + delta) { flow.step = next }
    }
}

private struct StepDots: View {
    let count: Int
    let current: Int

    var body: some View {
        HStack(spacing: 8) {
            ForEach(0..<count, id: \.self) { index in
                Capsule()
                    .fill(index <= current ? Color.accentColor : Color.secondary.opacity(0.25))
                    .frame(width: index == current ? 22 : 8, height: 8)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(L10n.t("onboarding.step_of", ["current": String(current + 1), "total": String(count)]))
    }
}

private struct StepHeader: View {
    let symbol: String
    let title: String
    let subtitle: String

    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: symbol)
                .font(.system(size: 40, weight: .light))
                .foregroundStyle(.tint)
                .accessibilityHidden(true)
            Text(title).font(.title2.weight(.semibold))
            Text(subtitle)
                .font(.body)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.bottom, 18)
    }
}

private struct WelcomeStep: View {
    var body: some View {
        VStack(spacing: 14) {
            if let icon = NSImage(named: NSImage.applicationIconName) {
                Image(nsImage: icon).resizable().frame(width: 96, height: 96).accessibilityHidden(true)
            }
            Text(L10n.t("onboarding.welcome_title")).font(.largeTitle.weight(.semibold))
            Text(L10n.t("onboarding.welcome_body"))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
            Label(L10n.t("onboarding.welcome_private"), systemImage: "lock.shield")
                .font(.callout)
                .foregroundStyle(.secondary)
                .padding(.top, 6)
        }
    }
}

private struct ThisMacStep: View {
    /// The largest model set (20 GB) plus the environment: below this, the first scan can run out.
    private static let roomForModelsGB = 25.0

    let model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            StepHeader(symbol: "laptopcomputer", title: L10n.t("this_mac.title"), subtitle: L10n.t("this_mac.body"))
            VStack(alignment: .leading, spacing: 12) {
                Fact(symbol: "cpu", label: L10n.t("this_mac.chip"),
                     value: AppModel.sysctlString("machdep.cpu.brand_string") ?? "—")
                Fact(symbol: "memorychip", label: L10n.t("this_mac.memory"),
                     value: "\(ProcessInfo.processInfo.physicalMemory / 1_073_741_824) GB")
                Fact(symbol: "internaldrive", label: L10n.t("this_mac.disk"),
                     value: L10n.t("this_mac.free_gb", ["gb": String(format: "%.0f", AppModel.freeDiskGB)]))
                Fact(symbol: "bolt", label: L10n.t("this_mac.gpu"), value: gpuText)
            }
            .padding(18)
            .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 12))
            Text(L10n.t("this_mac.models_note"))
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.top, 14)
            if AppModel.freeDiskGB < Self.roomForModelsGB {
                TintedLabel(text: L10n.t("this_mac.low_disk", ["gb": String(format: "%.0f", AppModel.freeDiskGB)]),
                            symbol: "exclamationmark.triangle.fill", tint: .orange)
                    .font(.callout)
                    .padding(.top, 8)
            }
        }
    }

    private var gpuText: String {
        switch model.setup {
        case .done(let mps): return mps ? L10n.t("this_mac.gpu_ok") : L10n.t("this_mac.gpu_cpu")
        case .failed: return "—"
        default: return L10n.t("this_mac.gpu_after_setup")
        }
    }
}

/// A tinted icon beside text in the primary color: orange or green text is below AA contrast
/// on a light window.
private struct TintedLabel: View {
    let text: String
    let symbol: String
    let tint: Color

    var body: some View {
        Label { Text(text) } icon: { Image(systemName: symbol).foregroundStyle(tint) }
    }
}

private struct Fact: View {
    let symbol: String
    let label: String
    let value: String

    var body: some View {
        HStack {
            Label(label, systemImage: symbol).frame(width: 190, alignment: .leading)
            Text(value).foregroundStyle(.secondary).textSelection(.enabled)
            Spacer()
        }
        .accessibilityElement(children: .combine)
    }
}

private struct FoldersStep: View {
    let model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            StepHeader(symbol: "folder.badge.plus", title: L10n.t("folders.title"), subtitle: L10n.t("folders.body"))
            if model.folders.isEmpty {
                Text(L10n.t("folders.none"))
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, minHeight: 90)
                    .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 12))
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(model.folders, id: \.self) { folder in
                            Label(folder, systemImage: "folder")
                                .lineLimit(1)
                                .truncationMode(.middle)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    .padding(14)
                }
                .frame(maxHeight: 130)
                .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 12))
            }
            Button(L10n.t("folders.add")) {
                Task { await model.chooseFolders() }
            }
            .padding(.top, 12)
            Text(L10n.t("folders.photos_note"))
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.top, 10)
        }
    }
}

private struct SetupStep: View {
    let model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            StepHeader(symbol: "shippingbox", title: L10n.t("setup.title"), subtitle: L10n.t("setup.body"))
            switch model.setup {
            case .idle, .running:
                progress
            case .done(let mps):
                TintedLabel(text: mps ? L10n.t("setup.done_gpu") : L10n.t("setup.done_cpu"),
                            symbol: "checkmark.circle.fill", tint: .green)
                    .font(.headline)
            case .failed(let message):
                VStack(spacing: 10) {
                    TintedLabel(text: L10n.t("setup.failed"), symbol: "exclamationmark.triangle.fill", tint: .orange)
                        .font(.headline)
                    Text(message).font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
                        .textSelection(.enabled)
                    HStack {
                        Button(L10n.t("setup.retry")) { Task { await model.runSetup() } }
                        if let logs = model.logsFolder {
                            Button(L10n.t("menu.show_logs")) { NSWorkspace.shared.open(logs) }
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder private var progress: some View {
        let event: ProgressEvent? = { if case .running(let event) = model.setup { return event }; return nil }()
        VStack(alignment: .leading, spacing: 8) {
            if let fraction = event?.fraction {
                ProgressView(value: fraction)
                Text(L10n.t("setup.downloaded", [
                    "done": ByteCountFormatter.string(fromByteCount: Int64(event?.current ?? 0), countStyle: .file),
                    "total": ByteCountFormatter.string(fromByteCount: Int64(event?.total ?? 0), countStyle: .file),
                ]))
                .font(.callout).foregroundStyle(.secondary).monospacedDigit()
            } else {
                ProgressView().progressViewStyle(.linear)
                Text(phaseText(event?.setupPhase)).font(.callout).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: 420)
    }

    private func phaseText(_ phase: SetupPhase?) -> String {
        switch phase {
        case .library: return L10n.t("setup.phase_library")
        case .check: return L10n.t("setup.phase_check")
        default: return L10n.t("setup.phase_environment")
        }
    }
}

private struct ReadyStep: View {
    let model: AppModel
    let flow: OnboardingFlow

    var body: some View {
        VStack(spacing: 0) {
            StepHeader(symbol: "checkmark.seal", title: L10n.t("ready.title"), subtitle: L10n.t("ready.body"))
            if model.folders.isEmpty {
                Text(L10n.t("ready.no_folders")).foregroundStyle(.secondary).multilineTextAlignment(.center)
            } else {
                Toggle(L10n.t("ready.scan_now"),
                       isOn: Binding(get: { flow.scanNow }, set: { flow.scanNow = $0 }))
                    .toggleStyle(.checkbox)
            }
            Text(L10n.t("ready.menu_note"))
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.top, 14)
            ServerStatus(model: model).padding(.top, 18)
        }
    }
}

/// Where the viewer is while the last steps are on screen, so a slow start is visible.
private struct ServerStatus: View {
    let model: AppModel

    var body: some View {
        switch model.server {
        case .stopped:
            EmptyView()
        case .starting:
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text(model.statusText).foregroundStyle(.secondary)
            }
        case .running:
            TintedLabel(text: model.statusText, symbol: "checkmark.circle.fill", tint: .green)
        case .failed:
            VStack(spacing: 8) {
                TintedLabel(text: model.statusText, symbol: "exclamationmark.triangle.fill", tint: .orange)
                    .multilineTextAlignment(.center)
                HStack {
                    Button(L10n.t("menu.restart")) { Task { await model.restartServer() } }
                    if let logs = model.logsFolder {
                        Button(L10n.t("menu.show_logs")) { NSWorkspace.shared.open(logs) }
                    }
                }
            }
        }
    }
}
