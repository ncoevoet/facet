import AppKit
import Darwin
import FacetCore
import Foundation
import Observation

/// The launcher's state: environment setup, the viewer process it supervises, and the scan
/// it keeps the Mac awake for.
@MainActor
@Observable
final class AppModel {
    enum SetupState: Equatable {
        case idle
        case running(ProgressEvent)
        case done(mpsWorks: Bool)
        case failed(String)
    }

    enum ServerState: Equatable {
        case stopped
        case starting
        case running(port: Int)
        case failed(String)
    }

    struct ScanState: Equatable {
        var running = false
        var current: Int? = nil
        var total: Int? = nil
    }

    /// How long a stopped viewer and its scans get to exit before SIGKILL.
    static let stopGrace: TimeInterval = 8
    static let healthTimeout: TimeInterval = 120
    static let scanPollSeconds: UInt64 = 5
    static let onboardedKey = "onboardingCompleted"
    static let portKey = "lastPort"
    static let serverPIDKey = "lastServerPID"
    // The viewer refuses any request without the install's key (api/access_key.py).
    static let accessKeyHeader = "X-Facet-Access-Key"
    static let accessKeyQuery = "access_key"

    var setup: SetupState = .idle
    var server: ServerState = .stopped
    var scan = ScanState()
    var folders: [String] = []
    var logsFolder: URL?
    private var accessKey = ""

    private var process: Process?
    private var starting: Task<Void, Never>?
    private var stopping = false
    private var restarts = 0
    var terminating = false
    private var runningSince: Date?
    private var setupProcess: Process?
    private var scanActivity: NSObjectProtocol?
    private var scanWatch: Task<Void, Never>?
    /// Folders were added during a scan; the viewer restarts to read them once the scan ends.
    private var restartAfterScan = false

    var isSetUp: Bool {
        if case .done = setup { return true }
        return false
    }

    var onboarded: Bool {
        get { UserDefaults.standard.bool(forKey: Self.onboardedKey) }
        set { UserDefaults.standard.set(newValue, forKey: Self.onboardedKey) }
    }

    var port: Int? {
        if case .running(let port) = server { return port }
        return nil
    }

    /// Opens the gallery with the key once; the viewer trades it for a cookie and drops it from the address.
    var facetURL: URL? {
        port.map { URL(string: "http://127.0.0.1:\($0)/?\(Self.accessKeyQuery)=\(accessKey)")! }
    }

    static func viewerRequest(_ port: Int, _ path: String, key: String) -> URLRequest {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)\(path)")!)
        request.setValue(key, forHTTPHeaderField: accessKeyHeader)
        return request
    }

    // MARK: - Setup

    func loadSpec() async {
        if let spec = await Helper.json(LaunchSpec.self, ["env"]) {
            logsFolder = URL(fileURLWithPath: spec.logs)
            accessKey = spec.access_key
        }
    }

    private struct Doctor: Decodable {
        let mps_works: Bool
    }

    /// The saved GPU check when the environment matches this build, else nil.
    func readyCheck() async -> Bool? {
        await Helper.json(Doctor.self, ["ready"])?.mps_works
    }

    /// Builds or repairs the environment. Safe to call again after a failure.
    func runSetup() async {
        if case .running = setup { return }
        setup = .running(ProgressEvent(phase: SetupPhase.environment.rawValue))
        // Setup replaces the environment; a viewer left by a force-quit copy may still run from it.
        await stopOrphanedServer()
        // The download takes minutes; an idle sleep would cut it off.
        let activity = ProcessInfo.processInfo.beginActivity(
            options: [.idleSystemSleepDisabled, .userInitiated], reason: "Facet is setting up")
        defer { ProcessInfo.processInfo.endActivity(activity) }
        let process = Helper.process(["setup"])
        setupProcess = process
        let (status, final) = await Helper.stream(process) { event in
            Task { @MainActor in
                // A progress event queued behind the result must not reopen a finished setup.
                if case .running = self.setup { self.setup = .running(event) }
            }
        }
        setupProcess = nil
        if status == 0, final?.setupPhase == .done {
            setup = .done(mpsWorks: final?.mpsWorks ?? false)
        } else if let code = final?.code {
            // Numbers in the reader's format: 2,1 GB in German, not Python's 2.1.
            let params = (final?.params ?? [:]).mapValues { value in
                Double(value).map { $0.formatted(.number.precision(.fractionLength(0...1))) } ?? value
            }
            setup = .failed(L10n.t("setup.error_" + code, params))
        } else {
            setup = .failed(final?.message ?? L10n.t("setup.failed_generic"))
        }
    }

    /// Stops a setup under way, uv downloads included (the helper leads its own process group).
    func stopSetup() {
        if let setupProcess, setupProcess.isRunning { kill(-setupProcess.processIdentifier, SIGTERM) }
    }

    // MARK: - Folders

    func refreshFolders() async {
        folders = await Helper.json([String].self, ["folders"]) ?? folders
    }

    /// Adds folders to the config. The viewer reads its config at start, so a running one restarts.
    func addFolders(_ urls: [URL]) async {
        for url in urls {
            let result = await Helper.run(["add-folder", url.path])
            let last = result.output.split(separator: "\n").last.map(String.init) ?? ""
            if result.status == 0, let updated = try? JSONDecoder().decode([String].self, from: Data(last.utf8)) {
                folders = updated
            } else {
                Self.showError(last.isEmpty ? L10n.t("setup.failed_generic") : last)
            }
        }
        // The viewer reads its folders at start. Restarting stops its scans, so a running one finishes first.
        if scan.running {
            restartAfterScan = true
            return
        }
        if case .starting = server { await startServer() }
        if port != nil { await restartServer() }
    }

    func chooseFolders() async {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = true
        panel.prompt = L10n.t("folders.add")
        NSApp.activate()
        guard panel.runModal() == .OK, !panel.urls.isEmpty else { return }
        await addFolders(panel.urls)
    }

    static func showError(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "Facet"
        alert.informativeText = message
        NSApp.activate()
        alert.runModal()
    }

    // MARK: - Server

    /// Starts the viewer and returns once it answers or failed. A second caller waits for
    /// the start already under way instead of returning before the viewer is up.
    func startServer() async {
        if let starting { return await starting.value }
        if process != nil { return }
        let task = Task { await launchServer() }
        starting = task
        await task.value
        starting = nil
    }

    private func launchServer() async {
        // A restart still under way when the app quits must not leave a new viewer behind.
        guard !terminating else { return }
        stopping = false
        server = .starting
        await stopOrphanedServer()
        guard let port = Ports.free(preferred: UserDefaults.standard.integer(forKey: Self.portKey)) else {
            server = .failed(L10n.t("server.no_port"))
            return
        }
        UserDefaults.standard.set(port, forKey: Self.portKey)
        let process = Helper.process(["serve", String(port)])
        if let logsFolder {
            try? FileManager.default.createDirectory(at: logsFolder, withIntermediateDirectories: true)
            let logURL = logsFolder.appendingPathComponent("viewer.log")
            // Keep the previous run: after a crash, the restart would otherwise erase its traceback.
            let previous = logsFolder.appendingPathComponent("viewer.previous.log")
            try? FileManager.default.removeItem(at: previous)
            try? FileManager.default.moveItem(at: logURL, to: previous)
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
            if let log = try? FileHandle(forWritingTo: logURL) {
                process.standardOutput = log
                process.standardError = log
            }
        }
        process.terminationHandler = { [weak self] ended in
            let status = ended.terminationStatus
            Task { @MainActor in self?.serverExited(ended, status: status) }
        }
        do {
            try process.run()
        } catch {
            server = .failed(error.localizedDescription)
            return
        }
        self.process = process
        UserDefaults.standard.set(Int(process.processIdentifier), forKey: Self.serverPIDKey)
        restartAfterScan = false    // a fresh viewer reads every folder in the config
        if await Self.waitForHealth(port: port, process: process, key: accessKey) {
            server = .running(port: port)
            runningSince = Date()
            watchScans()
        } else if self.process === process {
            // Stop it: a viewer that answers later would hold the port and library unseen.
            await stopServer()
            server = .failed(L10n.t("server.no_answer"))
        }
    }

    private func serverExited(_ ended: Process, status: Int32) {
        guard ended === process else { return }
        process = nil
        scanWatch?.cancel()
        setScanning(false)
        if stopping {
            server = .stopped
            UserDefaults.standard.removeObject(forKey: Self.serverPIDKey)
            return
        }
        // Scans it started share its process group and would otherwise outlive it.
        kill(-ended.processIdentifier, SIGTERM)
        let uptime = runningSince.map { Date().timeIntervalSince($0) }
        runningSince = nil
        guard let used = Supervision.restartsAfterCrash(used: restarts, uptime: uptime) else {
            server = .failed(L10n.t("server.crashed", ["code": String(status)]))
            return
        }
        restarts = used
        server = .starting
        let delay = UInt64(restarts * 2)
        Task {
            try? await Task.sleep(nanoseconds: delay * 1_000_000_000)
            await self.startServer()
        }
    }

    /// Stops the viewer and every scan it started: `facet_mac.py serve` gave it its own process group.
    func stopServer() async {
        guard let process else { return }
        stopping = true
        await Self.stopGroup(process.processIdentifier)
        process.waitUntilExit()
        serverExited(process, status: process.terminationStatus)
    }

    func restartServer() async {
        restarts = 0
        server = .starting    // no port while it stops, so the menu sends nothing to a viewer on its way out
        await stopServer()
        await startServer()
    }

    /// A launcher that crashed or was force-quit leaves its viewer running in its own process
    /// group: stop that one, so the Mac never runs two viewers on one library.
    private func stopOrphanedServer() async {
        let pid = pid_t(UserDefaults.standard.integer(forKey: Self.serverPIDKey))
        guard pid > 0, pid != process?.processIdentifier else { return }
        UserDefaults.standard.removeObject(forKey: Self.serverPIDKey)
        // Led or leaderless, the group may since belong to anything: stop it only while one of its
        // members still runs this app's bundled Python. A reused group id never holds one, and a
        // scan's own tools (ExifTool is Perl) may share the group, so not every member must.
        guard Self.groupIsAppPython(pid) else { return }
        await Self.stopGroup(pid)
    }

    /// Whether process group `pgid` still has a member running some copy of the app's Python.
    private static func groupIsAppPython(_ pgid: pid_t) -> Bool {
        let estimate = proc_listpids(UInt32(PROC_PGRP_ONLY), UInt32(pgid), nil, 0)
        guard estimate > 0 else { return false }
        // Headroom for a member started between the two calls.
        var pids = [pid_t](repeating: 0, count: Int(estimate) / MemoryLayout<pid_t>.stride + 16)
        let bytes = pids.withUnsafeMutableBytes { buffer in
            proc_listpids(UInt32(PROC_PGRP_ONLY), UInt32(pgid), buffer.baseAddress, Int32(buffer.count))
        }
        guard bytes > 0 else { return false }
        let members = pids.prefix(Int(bytes) / MemoryLayout<pid_t>.stride).filter { $0 > 0 }
        return members.contains(where: isAppPython)
    }

    /// Whether `pid` runs some copy of the app's bundled Python.
    private static func isAppPython(_ pid: pid_t) -> Bool {
        var path = [CChar](repeating: 0, count: 4096)
        return proc_pidpath(pid, &path, UInt32(path.count)) > 0 &&
            Supervision.isAppPython(String(cString: path))
    }

    /// SIGTERM a process group, then SIGKILL whatever is left of it after `stopGrace`.
    private static func stopGroup(_ pid: pid_t) async {
        kill(-pid, SIGTERM)
        let deadline = Date().addingTimeInterval(stopGrace)
        while kill(-pid, 0) == 0, Date() < deadline {
            try? await Task.sleep(nanoseconds: 100_000_000)
        }
        if kill(-pid, 0) == 0 { kill(-pid, SIGKILL) }
    }

    static func waitForHealth(port: Int, process: Process, key: String) async -> Bool {
        let deadline = Date().addingTimeInterval(healthTimeout)
        while Date() < deadline, process.isRunning {
            var request = viewerRequest(port, "/health", key: key)
            request.timeoutInterval = 2
            if let (_, response) = try? await URLSession.shared.data(for: request),
               (response as? HTTPURLResponse)?.statusCode == 200 {
                return true
            }
            try? await Task.sleep(nanoseconds: 500_000_000)
        }
        return false
    }

    // MARK: - Scans

    func scanAllFolders() async -> String? {
        guard let port else { return L10n.t("server.not_running") }
        await refreshFolders()
        guard !folders.isEmpty else { return L10n.t("scan.no_folders") }
        var request = Self.viewerRequest(port, "/api/scan/start", key: accessKey)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["directories": folders])
        guard let (data, response) = try? await URLSession.shared.data(for: request),
              let http = response as? HTTPURLResponse else { return L10n.t("server.not_running") }
        if http.statusCode == 200 {
            scan.running = true
            setScanning(true)
            return nil
        }
        // FastAPI sends a string, or for a validation error a list of {msg} objects.
        let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"]
        if let text = detail as? String { return text }
        let messages = (detail as? [[String: Any]])?.compactMap { $0["msg"] as? String } ?? []
        return messages.isEmpty ? "HTTP \(http.statusCode)" : messages.joined(separator: "\n")
    }

    private struct ScanStatus: Decodable {
        struct Progress: Decodable {
            let current: Double?
            let total: Double?
        }
        let running: Bool
        let progress: Progress?
    }

    /// Polls the viewer's scan status, whoever started the scan (the menu or the browser).
    private func watchScans() {
        scanWatch?.cancel()
        scanWatch = Task { [weak self] in
            while !Task.isCancelled {
                guard let self, let port = self.port else { return }
                let request = Self.viewerRequest(port, "/api/scan/status", key: self.accessKey)
                if let (data, _) = try? await URLSession.shared.data(for: request),
                   let status = try? JSONDecoder().decode(ScanStatus.self, from: data) {
                    self.scan = ScanState(running: status.running,
                                          current: status.progress?.current.map { Int($0) },
                                          total: status.progress?.total.map { Int($0) })
                    self.setScanning(status.running)
                    if !status.running, self.restartAfterScan {
                        self.restartAfterScan = false
                        // Not awaited here: stopping the viewer cancels this very task.
                        Task { await self.restartServer() }
                        return
                    }
                }
                try? await Task.sleep(nanoseconds: Self.scanPollSeconds * 1_000_000_000)
            }
        }
    }

    /// Keeps the Mac from idle-sleeping while a scan runs; the display may still sleep.
    private func setScanning(_ running: Bool) {
        if running, scanActivity == nil {
            scanActivity = ProcessInfo.processInfo.beginActivity(
                options: [.idleSystemSleepDisabled, .userInitiated], reason: "Facet is scanning photos")
        } else if !running, let activity = scanActivity {
            ProcessInfo.processInfo.endActivity(activity)
            scanActivity = nil
        }
    }

    // MARK: - Status and diagnostics

    var statusText: String {
        if case .running(let event) = setup {
            if let fraction = event.fraction {
                return L10n.t("status.setting_up_percent", ["percent": String(Int(fraction * 100))])
            }
            return L10n.t("status.setting_up")
        }
        if case .failed = setup { return L10n.t("status.setup_failed") }
        switch server {
        case .stopped: return L10n.t("status.stopped")
        case .starting: return L10n.t("status.starting")
        case .failed(let message): return L10n.t("status.error", ["message": message])
        case .running:
            guard scan.running else { return L10n.t("status.running") }
            if let current = scan.current, let total = scan.total, total > 0 {
                return L10n.t("status.scanning_count", ["current": String(current), "total": String(total)])
            }
            return L10n.t("status.scanning")
        }
    }

    func copyDiagnostics() async {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        var lines = [
            "Facet \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "?")",
            "macOS \(ProcessInfo.processInfo.operatingSystemVersionString)",
            "Chip \(Self.sysctlString("machdep.cpu.brand_string") ?? "?")",
            "Memory \(ProcessInfo.processInfo.physicalMemory / 1_073_741_824) GB",
            "Setup \(setup)",
            "Server \(server)",
        ]
        let doctor = await Helper.run(["doctor"])
        lines.append("Doctor \(doctor.output.trimmingCharacters(in: .whitespacesAndNewlines))")
        for name in ["setup.log", "viewer.previous.log", "viewer.log"] {
            guard let url = logsFolder?.appendingPathComponent(name),
                  let text = try? String(contentsOf: url, encoding: .utf8) else { continue }
            lines.append("--- \(name) (last 60 lines)")
            lines.append(contentsOf: text.split(separator: "\n", omittingEmptySubsequences: false).suffix(60).map(String.init))
        }
        // Folder names under the home folder can identify the user; keep them out of a pasted report.
        let report = lines.joined(separator: "\n").replacingOccurrences(of: home, with: "~")
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(report, forType: .string)
    }

    static func sysctlString(_ name: String) -> String? {
        var size = 0
        guard sysctlbyname(name, nil, &size, nil, 0) == 0, size > 0 else { return nil }
        var buffer = [CChar](repeating: 0, count: size)
        guard sysctlbyname(name, &buffer, &size, nil, 0) == 0 else { return nil }
        return String(cString: buffer)
    }

    /// The number setup checks against (statfs free space), so the two never disagree.
    static var freeDiskGB: Double {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let values = try? home.resourceValues(forKeys: [.volumeAvailableCapacityKey])
        return Double(values?.volumeAvailableCapacity ?? 0) / 1e9
    }
}
