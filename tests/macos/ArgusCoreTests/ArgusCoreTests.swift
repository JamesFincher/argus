import XCTest
@testable import ArgusCore

final class ArgusCoreTests: XCTestCase {
    func testBrandNamesUseArgusLine() {
        XCTAssertEqual(ArgusBrand.coreName, "Argus Core")
        XCTAssertEqual(ArgusBrand.sensorName, "Argus Sensor")
        XCTAssertEqual(ArgusBrand.meshName, "Argus Mesh")
        XCTAssertEqual(ArgusBrand.osName, "ArgusOS")
    }

    func testPrivacyFilterRedactsSecretsAndScoresSensitivity() {
        let filter = ArgusPrivacyFilter()
        let result = filter.redact("Email james@example.com with token sk_test_1234567890abcdef.")

        XCTAssertEqual(
            result.text,
            "Email [REDACTED_EMAIL] with token [REDACTED_API_KEY]."
        )
        XCTAssertEqual(result.sensitivity, .high)
        XCTAssertEqual(result.redactionsApplied, ["api_key", "email", "keyword_secret"])
    }

    func testPrivacyFilterMarksCardNumbersRestricted() {
        let filter = ArgusPrivacyFilter()
        let result = filter.redact("Card 4242 4242 4242 4242 was visible.")

        XCTAssertEqual(result.text, "Card [REDACTED_CARD] was visible.")
        XCTAssertEqual(result.sensitivity, .restricted)
        XCTAssertEqual(result.redactionsApplied, ["credit_card"])
    }

    func testEnvelopeRoundTripsThroughJSON() throws {
        let event = ArgusEventEnvelope(
            id: UUID(uuidString: "11111111-1111-1111-1111-111111111111")!,
            observedAt: Date(timeIntervalSince1970: 1_234),
            platform: .macOS,
            source: "unit-test",
            kind: .frontmostWindow,
            summary: "Frontmost app: Safari",
            payload: [
                "app_name": .string("Safari"),
                "visible": .bool(true),
                "count": .int(1)
            ],
            sensitivity: .low
        )

        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        let data = try encoder.encode(event)

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        XCTAssertEqual(try decoder.decode(ArgusEventEnvelope.self, from: data), event)
    }

    func testLocalEventBufferReturnsRecentEventsFirst() async {
        let buffer = LocalEventBuffer(limit: 3)
        let first = ArgusEventEnvelope(
            platform: .macOS,
            source: "test",
            kind: .frontmostWindow,
            summary: "first"
        )
        let second = ArgusEventEnvelope(
            platform: .macOS,
            source: "test",
            kind: .frontmostWindow,
            summary: "second"
        )
        let third = ArgusEventEnvelope(
            platform: .macOS,
            source: "test",
            kind: .frontmostWindow,
            summary: "third"
        )
        let fourth = ArgusEventEnvelope(
            platform: .macOS,
            source: "test",
            kind: .frontmostWindow,
            summary: "fourth"
        )

        await buffer.append(first)
        await buffer.append(second)
        await buffer.append(third)
        await buffer.append(fourth)

        let recent = await buffer.recent(limit: 3)
        XCTAssertEqual(recent.map(\.summary), ["fourth", "third", "second"])
        let trimmedEvent = await buffer.event(id: first.id)
        XCTAssertNil(trimmedEvent)
    }

    func testLocalEventSpoolAppendsAndReadsJSONLines() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let spool = LocalEventSpool(
            fileURL: directory.appendingPathComponent("events.jsonl")
        )
        let first = ArgusEventEnvelope(
            platform: .macOS,
            source: "test",
            kind: .frontmostWindow,
            summary: "first"
        )
        let second = ArgusEventEnvelope(
            platform: .macOS,
            source: "test",
            kind: .focusedField,
            summary: "second"
        )

        try await spool.append(first)
        try await spool.append(second)

        let events = try await spool.readAll()
        XCTAssertEqual(events.map(\.summary), ["first", "second"])
        XCTAssertEqual(events.map(\.kind), [.frontmostWindow, .focusedField])
    }

    func testLoopbackGatewayRejectsNonLocalEndpoints() throws {
        XCTAssertThrowsError(
            try LoopbackEventGatewaySink(endpoint: URL(string: "https://example.com/events")!)
        ) { error in
            guard case LoopbackEventGatewaySink.GatewayError.nonLoopbackURL = error else {
                return XCTFail("Unexpected error: \(error)")
            }
        }

        XCTAssertNoThrow(
            try LoopbackEventGatewaySink(endpoint: URL(string: "http://127.0.0.1:8765/events")!)
        )
    }
}
