// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "Argus",
    defaultLocalization: "en",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .library(
            name: "ArgusCore",
            targets: ["ArgusCore"]
        ),
        .executable(
            name: "argus-sensor-mac",
            targets: ["ArgusSensorMac"]
        )
    ],
    targets: [
        .target(
            name: "ArgusCore",
            path: "apps/macos/ArgusCore"
        ),
        .executableTarget(
            name: "ArgusSensorMac",
            dependencies: ["ArgusCore"],
            path: "apps/macos/ArgusSensorMac"
        ),
        .testTarget(
            name: "ArgusCoreTests",
            dependencies: ["ArgusCore"],
            path: "tests/macos/ArgusCoreTests"
        )
    ]
)
