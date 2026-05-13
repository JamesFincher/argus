import Foundation

public struct ArgusGatewayEnvelope: Codable, Equatable, Sendable {
    public var eventID: String
    public var eventType: String
    public var schemaVersion: String
    public var sourceDeviceID: String
    public var sourcePlatform: String
    public var sensorID: String
    public var sensorVersion: String
    public var observedAt: String
    public var ingestedAt: String
    public var sessionID: String?
    public var dedupeKey: String?
    public var sensitivity: String
    public var rawScope: String
    public var payload: [String: ArgusJSONValue]
    public var redactions: [ArgusGatewayRedaction]
    public var relationships: [ArgusGatewayRelationship]
    public var tags: [String]

    enum CodingKeys: String, CodingKey {
        case eventID = "event_id"
        case eventType = "event_type"
        case schemaVersion = "schema_version"
        case sourceDeviceID = "source_device_id"
        case sourcePlatform = "source_platform"
        case sensorID = "sensor_id"
        case sensorVersion = "sensor_version"
        case observedAt = "observed_at"
        case ingestedAt = "ingested_at"
        case sessionID = "session_id"
        case dedupeKey = "dedupe_key"
        case sensitivity
        case rawScope = "raw_scope"
        case payload
        case redactions
        case relationships
        case tags
    }
}

public struct ArgusGatewayRedaction: Codable, Equatable, Sendable {
    public var kind: String
    public var path: String
    public var replacement: String
}

public struct ArgusGatewayRelationship: Codable, Equatable, Sendable {
    public var kind: String
    public var targetEventID: String

    enum CodingKeys: String, CodingKey {
        case kind
        case targetEventID = "target_event_id"
    }
}

public extension ArgusEventEnvelope {
    func gatewayEnvelope(
        sourceDeviceID: String = ArgusGatewayDefaults.sourceDeviceID,
        sensorID: String = "argus-sensor-mac",
        sensorVersion: String = "0.1.0",
        ingestedAt: Date = Date()
    ) -> ArgusGatewayEnvelope {
        var gatewayPayload = payload
        gatewayPayload["summary"] = .string(summary)
        gatewayPayload["sensor_source"] = .string(source)
        gatewayPayload["swift_event_kind"] = .string(kind.rawValue)
        if let rawReference {
            gatewayPayload["raw_reference"] = .string(rawReference)
        }

        return ArgusGatewayEnvelope(
            eventID: id.uuidString.lowercased(),
            eventType: kind.gatewayEventType,
            schemaVersion: "2026-05-11",
            sourceDeviceID: sourceDeviceID,
            sourcePlatform: platform.rawValue,
            sensorID: sensorID,
            sensorVersion: sensorVersion,
            observedAt: ArgusGatewayDefaults.iso8601(observedAt),
            ingestedAt: ArgusGatewayDefaults.iso8601(ingestedAt),
            sessionID: nil,
            dedupeKey: nil,
            sensitivity: sensitivity.gatewaySensitivity,
            rawScope: rawReference == nil ? "none" : "ephemeral",
            payload: gatewayPayload,
            redactions: redactionsApplied.map {
                ArgusGatewayRedaction(kind: $0, path: "$.summary", replacement: "[REDACTED]")
            },
            relationships: [],
            tags: [platform.rawValue, source, kind.rawValue]
        )
    }
}

public enum ArgusGatewayDefaults {
    public static var sourceDeviceID: String {
        let hostname = Host.current().localizedName
        return hostname?.isEmpty == false ? hostname! : "local-mac"
    }

    public static func iso8601(_ date: Date) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.string(from: date)
    }
}

private extension ArgusEventKind {
    var gatewayEventType: String {
        switch self {
        case .frontmostWindow:
            return "activity.window_focus"
        case .focusedField:
            return "activity.focused_field"
        case .screenFrame:
            return "activity.screen_frame_ocr"
        case .browserPage:
            return "activity.browser_page"
        case .fileActivity:
            return "activity.file_change"
        case .calendarSignal:
            return "activity.calendar_item"
        case .healthSignal:
            return "activity.health_summary"
        case .userShare:
            return "activity.user_share"
        case .permissionState:
            return "system.permission_state"
        case .sensorHeartbeat:
            return "system.sensor_heartbeat"
        case .systemError:
            return "system.error"
        case .sensorControl:
            return "system.sensor_control"
        case .appLifecycle:
            return "activity.app_lifecycle"
        }
    }
}

private extension ArgusSensitivity {
    var gatewaySensitivity: String {
        switch self {
        case .low:
            return "low"
        case .medium:
            return "medium"
        case .high:
            return "high"
        case .restricted:
            return "blocked"
        }
    }
}
