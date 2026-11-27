import Darwin
import Foundation

// The launcher's logic that needs no UI, kept apart so core-checks can run it: the
// Command Line Tools ship neither XCTest nor the Swift Testing macros.

public let progressPrefix = "@FACET_PROGRESS "

/// The phases `facet_mac.py setup` reports, in order, then `done` or `error`.
public enum SetupPhase: String, Sendable {
    case environment, library, check, done, error
}

/// One `@FACET_PROGRESS` event (processing/progress.py's protocol).
public struct ProgressEvent: Sendable, Equatable {
    public var phase: String
    public var current: Double?
    public var total: Double?
    public var message: String?
    public var mpsWorks: Bool?
    /// An `error` event's reason (macos_app.setup.error_<code>) and the values its text names.
    public var code: String?
    public var params: [String: String] = [:]

    public init(phase: String, current: Double? = nil, total: Double? = nil, message: String? = nil, mpsWorks: Bool? = nil) {
        self.phase = phase
        self.current = current
        self.total = total
        self.message = message
        self.mpsWorks = mpsWorks
    }

    public init?(line: String) {
        guard line.hasPrefix(progressPrefix),
              let object = try? JSONSerialization.jsonObject(with: Data(line.dropFirst(progressPrefix.count).utf8)),
              let dict = object as? [String: Any], let phase = dict["phase"] as? String else { return nil }
        self.phase = phase
        current = (dict["current"] as? NSNumber)?.doubleValue
        total = (dict["total"] as? NSNumber)?.doubleValue
        message = dict["message"] as? String
        mpsWorks = (dict["doctor"] as? [String: Any])?["mps_works"] as? Bool
        code = dict["code"] as? String
        params = (dict["params"] as? [String: Any])?.mapValues { "\($0)" } ?? [:]
    }

    /// 0...1 when the event carries a known total.
    public var setupPhase: SetupPhase? { SetupPhase(rawValue: phase) }

    public var fraction: Double? {
        guard let current, let total, total > 0 else { return nil }
        return min(max(current / total, 0), 1)
    }
}

/// Where the app is running from. The environment points at the bundle's interpreter, so the
/// app must run from a stable place: not from the disk image, and not from a translocated copy.
public enum InstallLocation: Equatable {
    case stable
    case diskImage
    case translocated

    public static func of(_ bundlePath: String) -> InstallLocation {
        // macOS runs a quarantined app that the user did not move from a random read-only path.
        if bundlePath.contains("/AppTranslocation/") { return .translocated }
        // Any read-only volume, not only one under /Volumes: an image mounted elsewhere would
        // otherwise run in place and rebuild the environment around its own Python.
        let url = URL(fileURLWithPath: bundlePath)
        let readOnly = (try? url.resourceValues(forKeys: [.volumeIsReadOnlyKey]))?.volumeIsReadOnly ?? false
        return readOnly ? .diskImage : .stable
    }
}

public enum Translations {
    public static let supported = ["en", "de", "es", "fr", "it", "pt", "zh"]

    public static func language(preferred: [String]) -> String {
        for identifier in preferred {
            let code = String(identifier.prefix(2)).lowercased()
            if supported.contains(code) { return code }
        }
        return "en"
    }

    /// A dotted path into a nested translation table; nil for a missing or empty entry.
    public static func lookup(_ path: String, in table: [String: Any]) -> String? {
        var node: Any = table
        for part in path.split(separator: ".") {
            guard let dict = node as? [String: Any], let next = dict[String(part)] else { return nil }
            node = next
        }
        guard let text = node as? String, !text.isEmpty else { return nil }
        return text
    }

    public static func fill(_ text: String, _ args: [String: String]) -> String {
        args.reduce(text) { $0.replacingOccurrences(of: "{\($1.key)}", with: $1.value) }
    }
}

/// The viewer supervisor's decisions, kept here so core-checks can run them.
public enum Supervision {
    public static let maxRestarts = 3
    /// A viewer that ran this long without crashing earns a fresh set of restarts.
    public static let stableUptime: TimeInterval = 300

    /// Restarts used once this crash is restarted, or nil when none are left. `uptime` is how
    /// long the viewer answered before it died (nil: it never did).
    public static func restartsAfterCrash(used: Int, uptime: TimeInterval?) -> Int? {
        let used = (uptime ?? 0) > stableUptime ? 0 : used
        return used < maxRestarts ? used + 1 : nil
    }

    /// Whether `path` is the bundled Python of some copy of Facet.app, wherever that copy now is:
    /// an update moves the old one to the Trash, where Finder may rename it.
    public static func isAppPython(_ path: String) -> Bool {
        path.contains(".app/Contents/Resources/python/")
    }
}

public enum Ports {
    public static let first = 5000
    public static let count = 50

    /// The last port if it is still free, else the first free one from 5000.
    public static func free(preferred: Int) -> Int? {
        let candidates = (preferred > 0 ? [preferred] : []) + Array(first..<(first + count))
        return candidates.first(where: isFree)
    }

    /// Free on loopback and on the wildcard address: macOS lets a loopback bind shadow a
    /// `0.0.0.0` listener (a terminal viewer, Docker, AirPlay), which would steal its URL.
    public static func isFree(_ port: Int) -> Bool {
        canBind(port, "127.0.0.1") && canBind(port, "0.0.0.0")
    }

    private static func canBind(_ port: Int, _ host: String) -> Bool {
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        guard fd >= 0 else { return false }
        defer { close(fd) }
        // As uvicorn binds: a stopped viewer's TIME_WAIT connections must not hide its port.
        var reuse: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &reuse, socklen_t(MemoryLayout<Int32>.size))
        var address = sockaddr_in()
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = in_port_t(UInt16(port).bigEndian)
        address.sin_addr.s_addr = inet_addr(host)
        let bound = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        return bound == 0
    }
}

/// The updater's decisions about a GitHub release, kept here so core-checks can run them.
public enum Updates {
    /// `v1.32.0` -> `1.32.0`: release tags carry a `v`, the bundle version does not.
    public static func version(fromTag tag: String) -> String {
        tag.hasPrefix("v") ? String(tag.dropFirst()) : tag
    }

    /// Numeric, part by part: as strings, `1.10.0` would sort before `1.9.0`.
    public static func isNewer(_ candidate: String, than current: String) -> Bool {
        let new = candidate.split(separator: ".").map { Int($0) ?? 0 }
        let old = current.split(separator: ".").map { Int($0) ?? 0 }
        for index in 0..<max(new.count, old.count) {
            let a = index < new.count ? new[index] : 0
            let b = index < old.count ? old[index] : 0
            if a != b { return a > b }
        }
        return false
    }

    /// Release notes as plain text for the update window: GitHub returns Markdown, which an
    /// NSTextView would show with its `###`, `**` and backticks.
    public static func plainNotes(_ markdown: String) -> String {
        markdown.split(separator: "\n", omittingEmptySubsequences: false).map { line -> String in
            var text = String(line)
            if text.hasPrefix("#") { text = String(text.drop(while: { $0 == "#" })).trimmingCharacters(in: .whitespaces) }
            if text.hasPrefix("- ") || text.hasPrefix("* ") { text = "• " + text.dropFirst(2) }
            return text.replacingOccurrences(of: "**", with: "").replacingOccurrences(of: "`", with: "")
        }.joined(separator: "\n")
    }

    /// The hash `sha256sum` listed for `file` in a SHA256SUMS text, lowercased; nil when absent.
    public static func checksum(for file: String, in sums: String) -> String? {
        for line in sums.split(whereSeparator: \.isNewline) {
            let parts = line.split(separator: " ", maxSplits: 1)
            guard parts.count == 2 else { continue }
            // `hash  name` in text mode, `hash *name` in binary mode.
            if parts[1].drop(while: { $0 == " " || $0 == "*" }) == file { return parts[0].lowercased() }
        }
        return nil
    }
}
