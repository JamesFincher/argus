import Foundation

public struct ArgusRedactionResult: Equatable, Sendable {
    public var text: String
    public var redactionsApplied: [String]
    public var sensitivity: ArgusSensitivity

    public init(
        text: String,
        redactionsApplied: [String],
        sensitivity: ArgusSensitivity
    ) {
        self.text = text
        self.redactionsApplied = redactionsApplied
        self.sensitivity = sensitivity
    }
}

public struct ArgusPrivacyFilter: Sendable {
    private struct Rule: Sendable {
        var name: String
        var pattern: String
        var replacement: String
        var sensitivity: ArgusSensitivity
    }

    private let rules: [Rule] = [
        Rule(
            name: "email",
            pattern: #"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"#,
            replacement: "[REDACTED_EMAIL]",
            sensitivity: .medium
        ),
        Rule(
            name: "api_key",
            pattern: #"\b(?:sk|pk|rk|ghp|github_pat)_[A-Za-z0-9_\-]{16,}\b"#,
            replacement: "[REDACTED_API_KEY]",
            sensitivity: .high
        ),
        Rule(
            name: "aws_access_key",
            pattern: #"\bAKIA[0-9A-Z]{16}\b"#,
            replacement: "[REDACTED_AWS_KEY]",
            sensitivity: .high
        ),
        Rule(
            name: "credit_card",
            pattern: #"\b(?:\d[ -]*?){13,19}\b"#,
            replacement: "[REDACTED_CARD]",
            sensitivity: .restricted
        )
    ]

    public init() {}

    public func redact(_ text: String) -> ArgusRedactionResult {
        var redacted = text
        var applied: [String] = []
        var sensitivity: ArgusSensitivity = .low

        for rule in rules {
            let regex = try? NSRegularExpression(
                pattern: rule.pattern,
                options: [.caseInsensitive]
            )
            let range = NSRange(redacted.startIndex..<redacted.endIndex, in: redacted)
            guard let regex, regex.firstMatch(in: redacted, range: range) != nil else {
                continue
            }

            redacted = regex.stringByReplacingMatches(
                in: redacted,
                range: range,
                withTemplate: rule.replacement
            )
            applied.append(rule.name)
            sensitivity = max(sensitivity, rule.sensitivity)
        }

        let lowered = text.lowercased()
        if lowered.contains("password") || lowered.contains("secret") || lowered.contains("token") {
            sensitivity = max(sensitivity, .high)
            if !applied.contains("keyword_secret") {
                applied.append("keyword_secret")
            }
        }

        return ArgusRedactionResult(
            text: redacted,
            redactionsApplied: applied.sorted(),
            sensitivity: sensitivity
        )
    }

    public func sanitizedEnvelope(
        platform: ArgusPlatform,
        source: String,
        kind: ArgusEventKind,
        summary: String,
        payload: [String: ArgusJSONValue] = [:],
        rawReference: String? = nil
    ) -> ArgusEventEnvelope {
        let result = redact(summary)
        return ArgusEventEnvelope(
            platform: platform,
            source: source,
            kind: kind,
            summary: result.text,
            payload: payload,
            sensitivity: result.sensitivity,
            redactionsApplied: result.redactionsApplied,
            rawReference: rawReference
        )
    }
}
