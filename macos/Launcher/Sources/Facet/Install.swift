import AppKit
import FacetCore

extension InstallLocation {
    /// Asks the user to install the app properly. Returns true when the app should quit.
    @MainActor
    static func resolve() -> Bool {
        let bundle = Bundle.main.bundleURL
        switch of(bundle.path) {
        case .stable:
            return false
        case .diskImage:
            let alert = NSAlert()
            alert.messageText = L10n.t("install.dmg_title")
            alert.informativeText = L10n.t("install.dmg_body")
            alert.addButton(withTitle: L10n.t("install.copy"))
            alert.addButton(withTitle: L10n.t("install.quit"))
            if alert.runModal() == .alertFirstButtonReturn {
                let target = URL(fileURLWithPath: "/Applications").appendingPathComponent(bundle.lastPathComponent)
                do {
                    if FileManager.default.fileExists(atPath: target.path) {
                        try FileManager.default.trashItem(at: target, resultingItemURL: nil)
                    }
                    try FileManager.default.copyItem(at: bundle, to: target)
                    openAfterExit(target)
                } catch {
                    let failed = NSAlert(error: error)
                    failed.runModal()
                }
            }
            return true
        case .translocated:
            let alert = NSAlert()
            alert.messageText = L10n.t("install.move_title")
            alert.informativeText = L10n.t("install.move_body")
            alert.addButton(withTitle: L10n.t("install.quit"))
            alert.runModal()
            return true
        }
    }

    /// Opens `app` once this process has exited. Opening it while this copy still runs races
    /// the single-instance check: the new copy quits, and macOS reports the launch as failed.
    static func openAfterExit(_ app: URL) {
        let waiter = Process()
        waiter.executableURL = URL(fileURLWithPath: "/bin/sh")
        waiter.arguments = ["-c", "while kill -0 \"$1\" 2>/dev/null; do sleep 0.2; done; exec /usr/bin/open \"$2\"",
                            "sh", String(ProcessInfo.processInfo.processIdentifier), app.path]
        try? waiter.run()
    }
}
