// `swift run core-checks`: exits non-zero on the first failed check.
import Darwin
import FacetCore

var failures = 0
func check(_ condition: Bool, _ name: String) {
    print(condition ? "ok    \(name)" : "FAIL  \(name)")
    if !condition { failures += 1 }
}

let event = ProgressEvent(line: #"@FACET_PROGRESS {"phase": "environment", "current": 50, "total": 200}"#)
check(event?.phase == "environment" && event?.fraction == 0.25, "progress line parses")
check(ProgressEvent(line: #"@FACET_PROGRESS {"phase": "done", "doctor": {"mps_works": true}}"#)?.mpsWorks == true,
      "done line carries the GPU check")
let failure = ProgressEvent(line: #"@FACET_PROGRESS {"phase": "error", "message": "x", "code": "no_space", "params": {"free": "2.1", "needed": "3"}}"#)
check(failure?.code == "no_space" && failure?.params == ["free": "2.1", "needed": "3"], "error line carries its reason")
check(ProgressEvent(line: "Downloading torch (76.9MiB)") == nil && ProgressEvent(line: "@FACET_PROGRESS not json") == nil,
      "other lines are ignored")
check(ProgressEvent(phase: "environment", current: 10, total: 0).fraction == nil, "unknown total has no fraction")
check(InstallLocation.of("/private/var/folders/x4/abc/T/AppTranslocation/1234/d/Facet.app") == .translocated,
      "translocated path is not stable")
check(InstallLocation.of("/Applications/Facet.app") == .stable, "Applications is stable")
check(Translations.language(preferred: ["fr-FR", "en"]) == "fr", "preferred language is used")
check(Translations.language(preferred: ["ja-JP"]) == "en", "unsupported language falls back to English")
let table: [String: Any] = ["macos_app": ["menu": ["open": "Open {name}", "empty": ""]]]
check(Translations.lookup("macos_app.menu.open", in: table) == "Open {name}", "nested lookup")
check(Translations.lookup("macos_app.menu.empty", in: table) == nil, "empty entry counts as missing")
check(Translations.fill("Open {name}", ["name": "Facet"]) == "Open Facet", "placeholders are filled")

check(Supervision.restartsAfterCrash(used: 0, uptime: 10) == 1, "a crash is restarted")
check(Supervision.restartsAfterCrash(used: 3, uptime: 10) == nil, "a crash loop stops after three restarts")
check(Supervision.restartsAfterCrash(used: 3, uptime: 600) == 1, "a long run earns fresh restarts")
check(Supervision.restartsAfterCrash(used: 3, uptime: nil) == nil, "a viewer that never answered earns none")
check(Supervision.isAppPython("/Users/me/.Trash/Facet 2.app/Contents/Resources/python/bin/python3.12"),
      "an old copy in the Trash is still the app")
check(!Supervision.isAppPython("/opt/homebrew/bin/python3.12"), "another Python is not the app")

// A port held by a listener must not be offered.
let held = socket(AF_INET, SOCK_STREAM, 0)
var address = sockaddr_in()
address.sin_family = sa_family_t(AF_INET)
address.sin_addr.s_addr = inet_addr("127.0.0.1")
address.sin_port = 0
_ = withUnsafePointer(to: &address) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(held, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) } }
var length = socklen_t(MemoryLayout<sockaddr_in>.size)
_ = withUnsafeMutablePointer(to: &address) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(held, $0, &length) } }
let heldPort = Int(UInt16(bigEndian: address.sin_port))
check(!Ports.isFree(heldPort), "a bound port is not free")
check(Ports.free(preferred: heldPort) != heldPort, "a held preferred port is skipped")

// A viewer that just stopped leaves its port in TIME_WAIT; the next viewer can still bind it.
listen(held, 1)
let client = socket(AF_INET, SOCK_STREAM, 0)
_ = withUnsafePointer(to: &address) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { connect(client, $0, length) } }
close(accept(held, nil, nil))
close(client)
close(held)
check(Ports.isFree(heldPort), "a port left in TIME_WAIT is free")

// A viewer started in a terminal listens on 0.0.0.0; a loopback bind would shadow it.
let wildcard = socket(AF_INET, SOCK_STREAM, 0)
var any = sockaddr_in()
any.sin_family = sa_family_t(AF_INET)
any.sin_addr.s_addr = INADDR_ANY
_ = withUnsafePointer(to: &any) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(wildcard, $0, length) } }
listen(wildcard, 1)
_ = withUnsafeMutablePointer(to: &any) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(wildcard, $0, &length) } }
check(!Ports.isFree(Int(UInt16(bigEndian: any.sin_port))), "a port held on 0.0.0.0 is not free")
close(wildcard)

exit(failures == 0 ? 0 : 1)
