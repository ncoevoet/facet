import AppKit
import FacetCore
import SwiftUI

@main
struct FacetApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate

    var body: some Scene {
        MenuBarExtra {
            MenuContent(model: delegate.model, delegate: delegate)
        } label: {
            Image(systemName: delegate.model.scan.running ? "camera.aperture" : "camera")
                .accessibilityLabel("Facet")
        }
        .menuBarExtraStyle(.menu)
    }
}

struct MenuContent: View {
    let model: AppModel
    let delegate: AppDelegate

    var body: some View {
        Text(model.statusText)
        Divider()
        Button(L10n.t("menu.open")) { delegate.openFacet() }
            .keyboardShortcut("o")
            .disabled(model.port == nil)
        Button(L10n.t("menu.add_folder")) { Task { await model.chooseFolders() } }
            .disabled(!model.isSetUp)
        Button(model.scan.running ? L10n.t("menu.scanning") : L10n.t("menu.scan_all")) {
            Task {
                if let error = await model.scanAllFolders() { delegate.showError(error) }
            }
        }
        .disabled(model.port == nil || model.scan.running)
        Divider()
        Button(L10n.t("menu.setup_window")) { delegate.showOnboarding() }
        if let logs = model.logsFolder {
            Button(L10n.t("menu.show_logs")) { NSWorkspace.shared.open(logs) }
        }
        Button(L10n.t("menu.copy_diagnostics")) { Task { await model.copyDiagnostics() } }
        if case .failed = model.server {
            Button(L10n.t("menu.restart")) { Task { await model.restartServer() } }
        }
        Divider()
        Button(L10n.t("menu.quit")) { NSApp.terminate(nil) }
            .keyboardShortcut("q")
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    let model = AppModel()
    private var onboardingWindow: NSWindow?
    private var quitting = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        if let other = NSRunningApplication.runningApplications(withBundleIdentifier: Bundle.main.bundleIdentifier ?? "")
            .first(where: { $0 != .current }) {
            other.activate()
            NSApp.terminate(nil)
            return
        }
        if InstallLocation.resolve() {
            NSApp.terminate(nil)
            return
        }
        Task {
            await model.loadSpec()
            // Onboarding closed before it finished still leaves a usable environment: keep it.
            if let mps = await model.readyCheck() { model.setup = .done(mpsWorks: mps) }
            if model.onboarded, model.isSetUp {
                await model.startServer()
            } else {
                showOnboarding()
            }
        }
    }

    func showOnboarding() {
        if let onboardingWindow {
            NSApp.activate()
            onboardingWindow.makeKeyAndOrderFront(nil)
            return
        }
        let flow = OnboardingFlow()
        // After an update rebuilds the environment, skip the introduction a returning user has seen.
        if model.onboarded { flow.step = .setup }
        let view = OnboardingView(model: model, flow: flow) { [weak self] scanNow in
            Task { @MainActor in
                await self?.finishOnboarding(scanNow: scanNow)
                // Re-arms the button only if the window is still up, after a failure.
                flow.opening = false
            }
        }
        let window = NSWindow(contentRect: .zero, styleMask: [.titled, .closable, .fullSizeContentView],
                              backing: .buffered, defer: false)
        window.titlebarAppearsTransparent = true
        window.title = "Facet"
        window.isReleasedWhenClosed = false
        window.contentView = NSHostingView(rootView: view)
        window.center()
        // A menu-bar app has no Dock icon; show one while the window is up so it can be found again.
        NSApp.setActivationPolicy(.regular)
        NSApp.activate()
        window.makeKeyAndOrderFront(nil)
        NotificationCenter.default.addObserver(forName: NSWindow.willCloseNotification, object: window, queue: .main) { [weak self] _ in
            Task { @MainActor in
                self?.onboardingWindow = nil
                NSApp.setActivationPolicy(.accessory)
            }
        }
        onboardingWindow = window
    }

    private func finishOnboarding(scanNow: Bool) async {
        // Usually started already on the last steps; the window stays up until the browser opens.
        await model.startServer()
        guard model.port != nil else {
            showError(model.statusText)
            return
        }
        model.onboarded = true
        if scanNow, let error = await model.scanAllFolders() { showError(error) }
        openFacet()
        onboardingWindow?.close()
    }

    func openFacet() {
        if let url = model.facetURL { NSWorkspace.shared.open(url) }
    }

    func showError(_ message: String) {
        AppModel.showError(message)
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if quitting { return .terminateNow }
        quitting = true
        model.terminating = true
        model.stopSetup()
        Task {
            await model.stopServer()
            NSApp.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
}
