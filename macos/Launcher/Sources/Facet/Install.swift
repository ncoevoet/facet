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
                let applications = URL(fileURLWithPath: "/Applications")
                let target = applications.appendingPathComponent(bundle.lastPathComponent)
                let fm = FileManager.default
                var staging: URL?
                do {
                    // Copy first, beside the target: the installed app goes to the Trash only once
                    // the new copy is complete, and the final move is a rename.
                    let folder = try fm.url(for: .itemReplacementDirectory, in: .userDomainMask,
                                            appropriateFor: applications, create: true)
                    staging = folder
                    let staged = folder.appendingPathComponent(bundle.lastPathComponent)
                    try fm.copyItem(at: bundle, to: staged)
                    if fm.fileExists(atPath: target.path) {
                        try fm.trashItem(at: target, resultingItemURL: nil)
                    }
                    try fm.moveItem(at: staged, to: target)
                    try? fm.removeItem(at: folder)
                    openAfterExit(target)
                } catch {
                    if let staging { try? fm.removeItem(at: staging) }
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
