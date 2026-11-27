import AppKit
import CryptoKit
import FacetCore
import Foundation
import Security

/// Checks GitHub for a newer Facet release and installs it over this copy of the app: the
/// release's disk image, checked against its SHA256SUMS, its bundle ID, its version and its
/// signature. Any failed check leaves the installed app as it was.
@MainActor
@Observable
final class Updater {
    struct Release: Decodable {
        struct Asset: Decodable {
            let name: String
            let url: URL
            enum CodingKeys: String, CodingKey { case name, url = "browser_download_url" }
        }

        let tag: String
        let page: URL
        let notes: String?
        let assets: [Asset]
        enum CodingKeys: String, CodingKey { case tag = "tag_name", page = "html_url", notes = "body", assets }

        static let diskImagePrefix = "Facet-"
        static let sumsName = "SHA256SUMS"

        var version: String { Updates.version(fromTag: tag) }

        /// The disk image and its SHA256SUMS; nil until the release workflow has attached both.
        var downloads: (image: Asset, sums: Asset)? {
            guard let image = assets.first(where: { $0.name.hasPrefix(Self.diskImagePrefix) && $0.name.hasSuffix(".dmg") }),
                  let sums = assets.first(where: { $0.name == Self.sumsName }) else { return nil }
            return (image, sums)
        }
    }

    enum UpdateError: LocalizedError {
        case noDownload, badChecksum, badApp(String), tool(String, Int32), http(Int)

        var errorDescription: String? {
            switch self {
            case .noDownload: return L10n.t("update.no_download")
            case .badChecksum: return L10n.t("update.bad_checksum")
            case .badApp(let version): return L10n.t("update.bad_app", ["version": version])
            case .tool(let tool, let status): return "\(tool) exited with \(status)"
            case .http(let status): return "HTTP \(status)"
            }
        }
    }

    static let repository = "ncoevoet/facet"
    /// Off with `defaults write io.github.ncoevoet.facet AutomaticUpdateChecks -bool false`.
    static let automaticKey = "AutomaticUpdateChecks"
    /// Another releases/latest URL, such as a fork's or a local test server's.
    static let feedKey = "UpdateFeedURL"
    static let lastCheckKey = "LastUpdateCheck"
    static let checkInterval: TimeInterval = 24 * 60 * 60

    private(set) var available: Release?
    private(set) var installing = false
    private let model: AppModel
    private var timer: Timer?

    init(model: AppModel) {
        self.model = model
    }

    static var current: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0"
    }

    private var feed: URL {
        UserDefaults.standard.string(forKey: Self.feedKey).flatMap(URL.init(string:))
            ?? URL(string: "https://api.github.com/repos/\(Self.repository)/releases/latest")!
    }

    /// Checks once a day: hourly ticks that skip until a day has passed, so an app left
    /// running for weeks still checks and ten launches in a day ask GitHub once.
    func start() {
        guard UserDefaults.standard.object(forKey: Self.automaticKey) as? Bool ?? true else { return }
        timer = Timer.scheduledTimer(withTimeInterval: 60 * 60, repeats: true) { [weak self] _ in
            Task { @MainActor in await self?.checkIfDue() }
        }
        Task { await checkIfDue() }
    }

    private func checkIfDue() async {
        let last = UserDefaults.standard.object(forKey: Self.lastCheckKey) as? Date ?? .distantPast
        guard Date().timeIntervalSince(last) >= Self.checkInterval else { return }
        // A daily check that fails stays quiet and tries again tomorrow.
        _ = try? await fetchLatest()
    }

    /// The menu's Check for Updates: says so when there is nothing new.
    func checkNow() async {
        do {
            if let release = try await fetchLatest() {
                await offer(release)
            } else {
                let alert = NSAlert()
                alert.messageText = L10n.t("update.up_to_date_title")
                alert.informativeText = L10n.t("update.up_to_date_body", ["current": Self.current])
                NSApp.activate()
                alert.runModal()
            }
        } catch {
            AppModel.showError(L10n.t("update.check_failed", ["reason": error.localizedDescription]))
        }
    }

    /// The latest release when it is newer than this app, else nil.
    @discardableResult
    private func fetchLatest() async throws -> Release? {
        var request = URLRequest(url: feed, cachePolicy: .reloadIgnoringLocalCacheData)
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        request.setValue("Facet/\(Self.current)", forHTTPHeaderField: "User-Agent")
        let (data, response) = try await URLSession.shared.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200 else { throw UpdateError.http(status) }
        let release = try JSONDecoder().decode(Release.self, from: data)
        UserDefaults.standard.set(Date(), forKey: Self.lastCheckKey)
        available = Updates.isNewer(release.version, than: Self.current) && release.downloads != nil ? release : nil
        return available
    }

    func offer(_ release: Release) async {
        let alert = NSAlert()
        alert.messageText = L10n.t("update.available_title", ["version": release.version])
        let folder = Bundle.main.bundleURL.deletingLastPathComponent()
        let writable = FileManager.default.isWritableFile(atPath: folder.path)
        alert.informativeText = writable
            ? L10n.t("update.available_body", ["current": Self.current])
            : L10n.t("update.not_writable")
        if let notes = release.notes, !notes.isEmpty { alert.accessoryView = Self.notesView(notes) }
        alert.addButton(withTitle: writable ? L10n.t("update.install") : L10n.t("update.open_page"))
        alert.addButton(withTitle: L10n.t("update.later"))
        NSApp.activate()
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        if writable {
            await install(release)
        } else {
            NSWorkspace.shared.open(release.page)
        }
    }

    private static func notesView(_ notes: String) -> NSView {
        let scroll = NSTextView.scrollableTextView()
        scroll.frame = NSRect(x: 0, y: 0, width: 420, height: 180)
        let text = scroll.documentView as! NSTextView
        text.isEditable = false
        text.string = Updates.plainNotes(notes)
        return scroll
    }

    private func install(_ release: Release) async {
        installing = true
        defer { installing = false }
        let app = Bundle.main.bundleURL
        let fm = FileManager.default
        var work: URL?
        do {
            // Same volume as the app, so the final swap is a rename.
            let folder = try fm.url(for: .itemReplacementDirectory, in: .userDomainMask, appropriateFor: app, create: true)
            work = folder
            guard let (image, sums) = release.downloads else { throw UpdateError.noDownload }
            let (sumsData, _) = try await URLSession.shared.data(from: sums.url)
            guard let expected = Updates.checksum(for: image.name, in: String(decoding: sumsData, as: UTF8.self)) else {
                throw UpdateError.noDownload
            }
            let (downloaded, _) = try await URLSession.shared.download(from: image.url)
            let dmg = folder.appendingPathComponent(image.name)
            try fm.moveItem(at: downloaded, to: dmg)
            guard try Self.sha256(dmg) == expected else { throw UpdateError.badChecksum }

            let mount = folder.appendingPathComponent("mount")
            let newApp = folder.appendingPathComponent(app.lastPathComponent)
            try await Self.run("/usr/bin/hdiutil", ["attach", "-quiet", "-nobrowse", "-readonly", "-noautoopen",
                                                    "-mountpoint", mount.path, dmg.path])
            var copyError: Error?
            do {
                try await Self.run("/usr/bin/ditto", [mount.appendingPathComponent("Facet.app").path, newApp.path])
            } catch {
                copyError = error
            }
            try await Self.run("/usr/bin/hdiutil", ["detach", "-quiet", mount.path])
            if let copyError { throw copyError }
            try Self.verify(newApp, version: release.version)

            // The viewer runs the bundled Python: stop it before its files are swapped out.
            await model.stopServer()
            do {
                _ = try fm.replaceItemAt(app, withItemAt: newApp, backupItemName: nil, options: .usingNewMetadataOnly)
            } catch {
                await model.startServer()
                throw error
            }
            try? fm.removeItem(at: folder)
            InstallLocation.openAfterExit(app)
            // Not from inside this main-actor task: terminate waits for the quit handler's reply,
            // itself a main-actor task, which could never run while this one holds the actor.
            RunLoop.main.perform { NSApp.terminate(nil) }
        } catch {
            if let work { try? fm.removeItem(at: work) }
            AppModel.showError(L10n.t("update.install_failed", ["reason": error.localizedDescription]))
        }
    }

    /// The right app, the promised version, and a signature no file in the bundle breaks.
    private static func verify(_ app: URL, version: String) throws {
        guard let bundle = Bundle(url: app),
              bundle.bundleIdentifier == Bundle.main.bundleIdentifier,
              bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String == version
        else { throw UpdateError.badApp(version) }
        var code: SecStaticCode?
        let flags = SecCSFlags(rawValue: UInt32(kSecCSCheckAllArchitectures | kSecCSCheckNestedCode | kSecCSStrictValidate))
        guard SecStaticCodeCreateWithPath(app as CFURL, [], &code) == errSecSuccess, let code,
              SecStaticCodeCheckValidity(code, flags, nil) == errSecSuccess
        else { throw UpdateError.badApp(version) }
    }

    /// Read 1 MB at a time: the disk image is about 95 MB.
    private static func sha256(_ file: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        var hasher = SHA256()
        while let chunk = try handle.read(upToCount: 1 << 20), !chunk.isEmpty { hasher.update(data: chunk) }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    private static func run(_ tool: String, _ arguments: [String]) async throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: tool)
        process.arguments = arguments
        process.standardOutput = FileHandle.nullDevice
        try await withCheckedThrowingContinuation { (done: CheckedContinuation<Void, Error>) in
            process.terminationHandler = { ended in
                if ended.terminationStatus == 0 {
                    done.resume()
                } else {
                    done.resume(throwing: UpdateError.tool((tool as NSString).lastPathComponent, ended.terminationStatus))
                }
            }
            do { try process.run() } catch { done.resume(throwing: error) }
        }
    }
}
