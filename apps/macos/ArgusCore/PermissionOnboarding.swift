public enum PermissionOnboardingStep: String, Codable, Equatable, Sendable {
    case notifications
    case accessibility
    case screenRecording
    case ready
}

public struct PermissionOnboardingState: Equatable, Sendable {
    public var notificationsGranted: Bool
    public var accessibilityTrusted: Bool
    public var screenRecordingGranted: Bool

    public init(
        notificationsGranted: Bool,
        accessibilityTrusted: Bool,
        screenRecordingGranted: Bool
    ) {
        self.notificationsGranted = notificationsGranted
        self.accessibilityTrusted = accessibilityTrusted
        self.screenRecordingGranted = screenRecordingGranted
    }

    public var nextStep: PermissionOnboardingStep {
        if !notificationsGranted {
            return .notifications
        }
        if !accessibilityTrusted {
            return .accessibility
        }
        if !screenRecordingGranted {
            return .screenRecording
        }
        return .ready
    }

    public var canCollectStructuralSignals: Bool {
        accessibilityTrusted
    }

    public var canUseScreenFallback: Bool {
        accessibilityTrusted && screenRecordingGranted
    }
}
