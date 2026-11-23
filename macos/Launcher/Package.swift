// swift-tools-version:6.0
// The Facet.app launcher: a menu-bar app that sets up and supervises the Python viewer.
// Built by macos/build-app.sh with `swift build -c release`; no Xcode project needed.
// `swift run core-checks` checks the UI-free logic (the Command Line Tools have no XCTest).
import PackageDescription

let package = Package(
    name: "FacetLauncher",
    platforms: [.macOS(.v15)],
    targets: [
        .target(name: "FacetCore", path: "Sources/FacetCore"),
        .executableTarget(name: "Facet", dependencies: ["FacetCore"], path: "Sources/Facet"),
        .executableTarget(name: "core-checks", dependencies: ["FacetCore"], path: "Sources/CoreChecks"),
    ],
    swiftLanguageModes: [.v5]
)
