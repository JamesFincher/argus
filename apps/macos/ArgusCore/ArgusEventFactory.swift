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

    public static func sensorControl(
        action: String,
        scope: String = "macos",
        source: String = "macos.operator_control"
    ) -> ArgusEventEnvelope {
        ArgusEventEnvelope(
            platform: .macOS,
            source: source,
            kind: .sensorControl,
            summary: "Sensor control: \(action) \(scope)",
            payload: [
                "action": .string(action),
                "scope": .string(scope)
            ],
            sensitivity: .low
        )
    }

    public static func appLifecycle(
        bundleID: String?,
        appName: String,
        lifecycle: String,
        source: String = "nsworkspace.app_lifecycle"
    ) -> ArgusEventEnvelope {
        ArgusEventEnvelope(
            platform: .macOS,
            source: source,
            kind: .appLifecycle,
            summary: "App \(lifecycle): \(appName)",
            payload: [
                "bundle_id": bundleID.map(ArgusJSONValue.string) ?? .null,
                "app_name": .string(appName),
                "lifecycle": .string(lifecycle)
            ],
            sensitivity: .low
        )
    }

    public static func userShare(
        sourceApp: String?,
        contentType: String,
        title: String?,
        url: String?,
        text: String?,
        source: String = "ios.share_extension"
    ) -> ArgusEventEnvelope {
        let filter = ArgusPrivacyFilter()
        let summary = [
            title.map { "title=\($0)" },
            url.map { "url=\($0)" },
            text.map { "text=\($0)" }
        ].compactMap { $0 }.joined(separator: ", ")
        let result = filter.redact("User shared \(contentType): \(summary)")

        return ArgusEventEnvelope(
            platform: .iOS,
            source: source,
            kind: .userShare,
            summary: result.text,
            payload: [
                "source_app": sourceApp.map(ArgusJSONValue.string) ?? .null,
                "content_type": .string(contentType),
                "title": title.map(ArgusJSONValue.string) ?? .null,
                "url": url.map(ArgusJSONValue.string) ?? .null,
                "has_text": .bool(text?.isEmpty == false)
            ],
            sensitivity: result.sensitivity,
            redactionsApplied: result.redactionsApplied,
            rawReference: text?.isEmpty == false ? "local-ios-share-extension" : nil
        )
    }

    public static func healthAggregate(
        metric: String,
        value: Double,
        unit: String,
        intervalStart: Date,
        intervalEnd: Date,
        source: String = "watchos.healthkit"
    ) -> ArgusEventEnvelope {
        ArgusEventEnvelope(
            platform: .watchOS,
            source: source,
            kind: .healthSignal,
            summary: "Health aggregate: \(metric) \(value) \(unit)",
            payload: [
                "metric": .string(metric),
                "value": .double(value),
                "unit": .string(unit),
                "interval_start": .string(Self.iso8601(intervalStart)),
                "interval_end": .string(Self.iso8601(intervalEnd)),
                "aggregate_only": .bool(true)
            ],
            sensitivity: .medium,
            redactionsApplied: [],
            rawReference: nil
        )
    }

    private static func iso8601(_ date: Date) -> String {
        ISO8601DateFormatter().string(from: date)
    }
}
