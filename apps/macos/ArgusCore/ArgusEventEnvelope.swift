import Foundation

public enum ArgusPlatform: String, Codable, Equatable, Sendable {
    case macOS = "macos"
    case iOS = "ios"
    case watchOS = "watchos"
}

public enum ArgusEventKind: String, Codable, Equatable, Sendable {
    case frontmostWindow = "frontmost_window"
    case focusedField = "focused_field"
    case screenFrame = "screen_frame"
    case browserPage = "browser_page"
    case fileActivity = "file_activity"
    case calendarSignal = "calendar_signal"
    case healthSignal = "health_signal"
    case userShare = "user_share"
    case permissionState = "permission_state"
    case sensorHeartbeat = "sensor_heartbeat"
    case sensorControl = "sensor_control"
    case appLifecycle = "app_lifecycle"
}

public enum ArgusSensitivity: String, Codable, Comparable, Equatable, Sendable {
    case low
    case medium
    case high
    case restricted

    public static func < (lhs: ArgusSensitivity, rhs: ArgusSensitivity) -> Bool {
        lhs.rank < rhs.rank
    }

    private var rank: Int {
        switch self {
        case .low: 0
        case .medium: 1
        case .high: 2
        case .restricted: 3
        }
    }
}

public enum ArgusJSONValue: Codable, Equatable, Sendable {
    case string(String)
    case int(Int)
    case double(Double)
    case bool(Bool)
    case object([String: ArgusJSONValue])
    case array([ArgusJSONValue])
    case null

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Int.self) {
            self = .int(value)
        } else if let value = try? container.decode(Double.self) {
            self = .double(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([String: ArgusJSONValue].self) {
            self = .object(value)
        } else {
            self = .array(try container.decode([ArgusJSONValue].self))
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value):
            try container.encode(value)
        case .int(let value):
            try container.encode(value)
        case .double(let value):
            try container.encode(value)
        case .bool(let value):
            try container.encode(value)
        case .object(let value):
            try container.encode(value)
        case .array(let value):
            try container.encode(value)
        case .null:
            try container.encodeNil()
        }
    }
}

public struct ArgusEventEnvelope: Codable, Equatable, Identifiable, Sendable {
    public var id: UUID
    public var observedAt: Date
    public var platform: ArgusPlatform
    public var source: String
    public var kind: ArgusEventKind
    public var summary: String
    public var payload: [String: ArgusJSONValue]
    public var sensitivity: ArgusSensitivity
    public var redactionsApplied: [String]
    public var rawReference: String?

    public init(
        id: UUID = UUID(),
        observedAt: Date = Date(),
        platform: ArgusPlatform,
        source: String,
        kind: ArgusEventKind,
        summary: String,
        payload: [String: ArgusJSONValue] = [:],
        sensitivity: ArgusSensitivity = .low,
        redactionsApplied: [String] = [],
        rawReference: String? = nil
    ) {
        self.id = id
        self.observedAt = observedAt
        self.platform = platform
        self.source = source
        self.kind = kind
        self.summary = summary
        self.payload = payload
        self.sensitivity = sensitivity
        self.redactionsApplied = redactionsApplied
        self.rawReference = rawReference
    }
}
