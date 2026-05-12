import ApplicationServices
import CoreGraphics

struct MacPermissionSnapshot: Equatable {
    var accessibilityTrusted: Bool
    var screenRecordingGranted: Bool

    static func current(promptAccessibility: Bool = false) -> MacPermissionSnapshot {
        let accessibilityTrusted = AXIsProcessTrustedWithOptions([
            "AXTrustedCheckOptionPrompt": promptAccessibility
        ] as CFDictionary)

        return MacPermissionSnapshot(
            accessibilityTrusted: accessibilityTrusted,
            screenRecordingGranted: CGPreflightScreenCaptureAccess()
        )
    }

    @discardableResult
    static func requestScreenRecording() -> Bool {
        CGRequestScreenCaptureAccess()
    }
}
