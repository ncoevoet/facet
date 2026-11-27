import FacetCore
import Foundation

/// Runs macos/facet_mac.py with the interpreter bundled in Facet.app. Every decision about
/// paths, the environment and the config is made there; this side only reads what it prints.
enum Helper {
    static let resources = Bundle.main.resourceURL!
    static let python = resources.appendingPathComponent("python/bin/python3")
    static let script = resources.appendingPathComponent("app/macos/facet_mac.py")

    struct Result {
        let status: Int32
        let output: String
    }

    static func process(_ arguments: [String]) -> Process {
        let process = Process()
        process.executableURL = python
        // -I: the user's PYTHONPATH, PYTHONHOME or site-packages must not reach the app.
        process.arguments = ["-I", script.path] + arguments
        return process
    }

    /// Starts the helper with stdout and stderr on one pipe.
    private static func start(_ process: Process) throws -> (Process, FileHandle) {
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        try process.run()
        return (process, pipe.fileHandleForReading)
    }

    /// Runs one command to completion off the main thread.
    static func run(_ arguments: [String]) async -> Result {
        await Task.detached {
            let process: Process, output: FileHandle
            do {
                (process, output) = try start(Helper.process(arguments))
            } catch {
                return Result(status: -1, output: error.localizedDescription)
            }
            let data = output.readDataToEndOfFile()
            process.waitUntilExit()
            return Result(status: process.terminationStatus, output: String(decoding: data, as: UTF8.self))
        }.value
    }

    static func json<T: Decodable>(_ type: T.Type, _ arguments: [String]) async -> T? {
        let result = await run(arguments)
        guard result.status == 0, let line = result.output.split(separator: "\n").last else { return nil }
        return try? JSONDecoder().decode(type, from: Data(line.utf8))
    }

    /// Runs a helper process that prints @FACET_PROGRESS lines, handing each event to `onEvent`.
    /// Returns the exit status and the final `done` or `error` event, if one was printed.
    static func stream(_ helper: Process,
                       onEvent: @escaping @Sendable (ProgressEvent) -> Void) async -> (Int32, ProgressEvent?) {
        await Task.detached {
            let process: Process, handle: FileHandle
            do {
                (process, handle) = try start(helper)
            } catch {
                return (-1, ProgressEvent(phase: SetupPhase.error.rawValue, message: error.localizedDescription))
            }
            var final: ProgressEvent?
            var buffer = Data()
            while true {
                let chunk = handle.availableData
                if chunk.isEmpty { break }
                buffer.append(chunk)
                while let newline = buffer.firstIndex(of: 0x0A) {
                    let line = String(decoding: buffer[..<newline], as: UTF8.self)
                    buffer.removeSubrange(...newline)
                    guard let event = ProgressEvent(line: line) else { continue }
                    if [.done, .error].contains(event.setupPhase) { final = event } else { onEvent(event) }
                }
            }
            process.waitUntilExit()
            return (process.terminationStatus, final)
        }.value
    }
}

/// What `facet_mac.py env` prints: only the log folder is needed here.
struct LaunchSpec: Decodable {
    let logs: String
    let access_key: String
}
