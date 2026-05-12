import Foundation

public enum ArgusEventFactory {
    public static func focusedField(
        role: String?,
        label: String?,
        value: String?,
        source: String = "accessibility.focused_field"
    ) -> ArgusEventEnvelope {
        let filter = ArgusPrivacyFilter()
        let summaryParts = [
            label.map { "label=\($0)" },
            role.map { "role=\($0)" },
            value.map { "value=\($0)" }
        ].compactMap { $0 }
        let summary = "Focused field: " + (summaryParts.isEmpty ? "unknown" : summaryParts.joined(separator: ", "))

        return filter.sanitizedEnvelope(
            platform: .macOS,
            source: source,
            kind: .focusedField,
            summary: summary,
            payload: [
                "role": role.map(ArgusJSONValue.string) ?? .null,
                "label": label.map(ArgusJSONValue.string) ?? .null,
                "has_value": .bool(value?.isEmpty == false)
            ],
            rawReference: value?.isEmpty == false ? "local-ax-focused-field" : nil
        )
    }

    public static func permissionState(
        accessibilityTrusted: Bool,
        screenRecordingGranted: Bool,
        source: String = "macos.permissions"
    ) -> ArgusEventEnvelope {
        let missing = [
            accessibilityTrusted ? nil : "Accessibility",
            screenRecordingGranted ? nil : "Screen Recording"
        ].compactMap { $0 }

        let summary: String
        if missing.isEmpty {
            summary = "macOS permissions granted: Accessibility, Screen Recording"
        } else {
            summary = "macOS permissions missing: \(missing.joined(separator: ", "))"
        }

        return ArgusEventEnvelope(
            platform: .macOS,
            source: source,
            kind: .permissionState,
            summary: summary,
            payload: [
                "accessibility_trusted": .bool(accessibilityTrusted),
                "screen_recording_granted": .bool(screenRecordingGranted)
            ],
            sensitivity: .low
        )
    }
}
