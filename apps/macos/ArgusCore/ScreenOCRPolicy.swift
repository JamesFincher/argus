import Foundation

public enum ScreenOCRBlockReason: String, Codable, Equatable, Sendable {
    case userConsentMissing = "user_consent_missing"
    case screenRecordingPermissionMissing = "screen_recording_permission_missing"
    case structuralSignalsAvailable = "structural_signals_available"
    case rateLimited = "rate_limited"
}

public struct ScreenOCRPolicy: Equatable, Sendable {
    public var userConsented: Bool
    public var screenRecordingGranted: Bool
    public var structuralSignalsAvailable: Bool
    public var minimumFrameInterval: TimeInterval

    public init(
        userConsented: Bool,
        screenRecordingGranted: Bool,
        structuralSignalsAvailable: Bool,
        minimumFrameInterval: TimeInterval = 2.0
    ) {
        self.userConsented = userConsented
        self.screenRecordingGranted = screenRecordingGranted
        self.structuralSignalsAvailable = structuralSignalsAvailable
        self.minimumFrameInterval = minimumFrameInterval
    }

    public func evaluate(
        now: Date = Date(),
        lastCapturedAt: Date? = nil
    ) -> ScreenOCRPolicyDecision {
        if !userConsented {
            return ScreenOCRPolicyDecision(allowed: false, blockReason: .userConsentMissing)
        }

        if !screenRecordingGranted {
            return ScreenOCRPolicyDecision(allowed: false, blockReason: .screenRecordingPermissionMissing)
        }

        if structuralSignalsAvailable {
            return ScreenOCRPolicyDecision(allowed: false, blockReason: .structuralSignalsAvailable)
        }

        if let lastCapturedAt, now.timeIntervalSince(lastCapturedAt) < minimumFrameInterval {
            return ScreenOCRPolicyDecision(allowed: false, blockReason: .rateLimited)
        }

        return ScreenOCRPolicyDecision(
            allowed: true,
            blockReason: nil,
            minimumFrameInterval: minimumFrameInterval
        )
    }
}

public struct ScreenOCRPolicyDecision: Equatable, Sendable {
    public var allowed: Bool
    public var blockReason: ScreenOCRBlockReason?
    public var minimumFrameInterval: TimeInterval
    public var includesAudio: Bool

    public init(
        allowed: Bool,
        blockReason: ScreenOCRBlockReason?,
        minimumFrameInterval: TimeInterval = 2.0,
        includesAudio: Bool = false
    ) {
        self.allowed = allowed
        self.blockReason = blockReason
        self.minimumFrameInterval = minimumFrameInterval
        self.includesAudio = includesAudio
    }
}

public struct ScreenOCRTextObservation: Equatable, Sendable {
    public var text: String
    public var confidence: Double

    public init(text: String, confidence: Double) {
        self.text = text
        self.confidence = confidence
    }
}

public struct ScreenOCRRecognizedTextCandidate: Equatable, Sendable {
    public var text: String
    public var confidence: Double

    public init(text: String, confidence: Double) {
        self.text = text
        self.confidence = confidence
    }
}

public struct ScreenOCRObservationProcessor: Sendable {
    public var minimumConfidence: Double
    public var maximumObservationCount: Int

    public init(
        minimumConfidence: Double = 0.35,
        maximumObservationCount: Int = 24
    ) {
        self.minimumConfidence = minimumConfidence
        self.maximumObservationCount = maximumObservationCount
    }

    public func observations(
        from candidates: [ScreenOCRRecognizedTextCandidate]
    ) -> [ScreenOCRTextObservation] {
        candidates
            .lazy
            .map { candidate in
                ScreenOCRTextObservation(
                    text: Self.normalizedText(candidate.text),
                    confidence: candidate.confidence
                )
            }
            .filter { observation in
                !observation.text.isEmpty && observation.confidence >= minimumConfidence
            }
            .prefix(maximumObservationCount)
            .map { $0 }
    }

    private static func normalizedText(_ text: String) -> String {
        text
            .split(whereSeparator: \.isWhitespace)
            .joined(separator: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

public struct ScreenOCREventBuilder: Sendable {
    private let privacyFilter: ArgusPrivacyFilter

    public init(privacyFilter: ArgusPrivacyFilter = ArgusPrivacyFilter()) {
        self.privacyFilter = privacyFilter
    }

    public func event(
        observations: [ScreenOCRTextObservation],
        decision: ScreenOCRPolicyDecision,
        appName: String? = nil,
        windowTitle: String? = nil,
        source: String = "screencapturekit.vision_ocr"
    ) -> ArgusEventEnvelope? {
        guard decision.allowed else {
            return nil
        }

        let rawText = observations
            .map(\.text)
            .filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
            .joined(separator: " ")
        guard !rawText.isEmpty else {
            return nil
        }

        let redacted = privacyFilter.redact(rawText)
        let summaryText = Self.summaryPreview(from: redacted.text)
        let context = [
            appName.map { "app=\($0)" },
            windowTitle.map { "window=\($0)" }
        ].compactMap { $0 }.joined(separator: ", ")
        let summarySuffix = context.isEmpty ? summaryText : "\(context): \(summaryText)"

        var payload: [String: ArgusJSONValue] = [
            "text": .string(redacted.text),
            "observation_count": .int(observations.count),
            "minimum_frame_interval_seconds": .double(decision.minimumFrameInterval),
            "includes_audio": .bool(decision.includesAudio),
            "redaction_before_summary": .bool(true)
        ]
        payload["app_name"] = appName.map(ArgusJSONValue.string) ?? .null
        payload["window_title"] = windowTitle.map(ArgusJSONValue.string) ?? .null
        payload["average_confidence"] = .double(Self.averageConfidence(observations))

        return ArgusEventEnvelope(
            platform: .macOS,
            source: source,
            kind: .screenFrame,
            summary: "Screen OCR: \(summarySuffix)",
            payload: payload,
            sensitivity: redacted.sensitivity,
            redactionsApplied: redacted.redactionsApplied,
            rawReference: "local-screen-ocr-frame"
        )
    }

    private static func averageConfidence(_ observations: [ScreenOCRTextObservation]) -> Double {
        guard !observations.isEmpty else {
            return 0
        }
        let total = observations.reduce(0.0) { $0 + $1.confidence }
        return total / Double(observations.count)
    }

    private static func summaryPreview(from text: String) -> String {
        let normalized = text
            .split(whereSeparator: \.isWhitespace)
            .joined(separator: " ")
        guard normalized.count > 160 else {
            return normalized
        }
        let end = normalized.index(normalized.startIndex, offsetBy: 160)
        return String(normalized[..<end]) + "..."
    }
}
