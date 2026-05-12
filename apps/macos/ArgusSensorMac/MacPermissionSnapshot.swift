import ApplicationServices
import ArgusCore
import CoreGraphics

struct MacPermissionSnapshot: Equatable {
    var accessibilityTrusted: Bool
    var screenRecordingGranted: Bool

    var onboardingState: PermissionOnboardingState {
        PermissionOnboardingState(
            notificationsGranted: true,
            accessibilityTrusted: accessibilityTrusted,
            screenRecordingGranted: screenRecordingGranted
        )
    }

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

    func event() -> ArgusEventEnvelope {
        ArgusEventFactory.permissionState(
            accessibilityTrusted: accessibilityTrusted,
            screenRecordingGranted: screenRecordingGranted
        )
    }
}
