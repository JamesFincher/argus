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

    func testDefaultEventIDsUseSortableUUIDv7Layout() {
        let first = ArgusEventID.uuidV7(
            now: Date(timeIntervalSince1970: 1_000),
            randomBytes: Array(repeating: 0, count: 10)
        )
        let second = ArgusEventID.uuidV7(
            now: Date(timeIntervalSince1970: 1_001),
            randomBytes: Array(repeating: 0, count: 10)
        )
        let generated = ArgusEventEnvelope(
            platform: .macOS,
            source: "unit-test",
            kind: .frontmostWindow,
            summary: "generated"
        )
        let generatedID = generated.id.uuidString.lowercased()

        XCTAssertLessThan(first.uuidString.lowercased(), second.uuidString.lowercased())
        XCTAssertEqual(first.uuidString.lowercased().dropFirst(14).first, "7")
        XCTAssertEqual(generatedID.dropFirst(14).first, "7")
        XCTAssertTrue(["8", "9", "a", "b"].contains(String(generatedID.dropFirst(19).first!)))
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

    func testGatewayEnvelopeMatchesPythonEventContract() throws {
        let observedAt = Date(timeIntervalSince1970: 1_234)
        let ingestedAt = Date(timeIntervalSince1970: 1_235)
        let event = ArgusEventEnvelope(
            id: UUID(uuidString: "11111111-1111-1111-1111-111111111111")!,
            observedAt: observedAt,
            platform: .macOS,
            source: "accessibility.focused_field",
            kind: .focusedField,
            summary: "Focused field: value=[REDACTED_API_KEY]",
            payload: [
                "role": .string("AXTextField"),
                "has_value": .bool(true)
            ],
            sensitivity: .high,
            redactionsApplied: ["api_key"],
            rawReference: "local-ax-focused-field"
        )

        let gateway = event.gatewayEnvelope(
            sourceDeviceID: "macbook-test",
            sensorID: "argus-sensor-mac-test",
            ingestedAt: ingestedAt
        )

        XCTAssertEqual(gateway.eventID, "11111111-1111-1111-1111-111111111111")
        XCTAssertEqual(gateway.eventType, "activity.focused_field")
        XCTAssertEqual(gateway.schemaVersion, "2026-05-11")
        XCTAssertEqual(gateway.sourceDeviceID, "macbook-test")
        XCTAssertEqual(gateway.sourcePlatform, "macos")
        XCTAssertEqual(gateway.sensorID, "argus-sensor-mac-test")
        XCTAssertEqual(gateway.observedAt, "1970-01-01T00:20:34.000Z")
        XCTAssertEqual(gateway.ingestedAt, "1970-01-01T00:20:35.000Z")
        XCTAssertEqual(gateway.sensitivity, "high")
        XCTAssertEqual(gateway.rawScope, "ephemeral")
        XCTAssertEqual(gateway.payload["summary"], .string("Focused field: value=[REDACTED_API_KEY]"))
        XCTAssertEqual(gateway.payload["sensor_source"], .string("accessibility.focused_field"))
        XCTAssertEqual(gateway.payload["swift_event_kind"], .string("focused_field"))
        XCTAssertEqual(gateway.payload["raw_reference"], .string("local-ax-focused-field"))
        XCTAssertEqual(gateway.redactions, [
            ArgusGatewayRedaction(kind: "api_key", path: "$.summary", replacement: "[REDACTED]")
        ])
        XCTAssertTrue(gateway.tags.contains("macos"))
        XCTAssertTrue(gateway.tags.contains("accessibility.focused_field"))
        XCTAssertTrue(gateway.tags.contains("focused_field"))
    }

    func testGatewayEnvelopeEncodesCanonicalSnakeCaseKeys() throws {
        let event = ArgusEventFactory.permissionState(
            accessibilityTrusted: true,
            screenRecordingGranted: false
        )
        let gateway = event.gatewayEnvelope(sourceDeviceID: "macbook-test")
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let data = try encoder.encode(gateway)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])

        XCTAssertEqual(object["event_type"] as? String, "system.permission_state")
        XCTAssertEqual(object["source_device_id"] as? String, "macbook-test")
        XCTAssertEqual(object["source_platform"] as? String, "macos")
        XCTAssertEqual(object["sensor_id"] as? String, "argus-sensor-mac")
        XCTAssertEqual(object["raw_scope"] as? String, "none")
        XCTAssertNotNil(object["event_id"])
        XCTAssertNil(object["id"])
        XCTAssertNil(object["kind"])
        XCTAssertNil(object["platform"])
    }

    func testGatewayEnvelopeMapsRestrictedSwiftSensitivityToBlocked() {
        let event = ArgusEventEnvelope(
            platform: .macOS,
            source: "screencapturekit.vision_ocr",
            kind: .screenFrame,
            summary: "Card [REDACTED_CARD] was visible",
            sensitivity: .restricted,
            redactionsApplied: ["credit_card"],
            rawReference: "local-screen-ocr-frame"
        )

        let gateway = event.gatewayEnvelope(sourceDeviceID: "macbook-test")

        XCTAssertEqual(gateway.eventType, "activity.screen_frame_ocr")
        XCTAssertEqual(gateway.sensitivity, "blocked")
        XCTAssertEqual(gateway.rawScope, "ephemeral")
    }

    func testFocusedFieldFactoryRedactsSensitiveValueInSummary() {
        let event = ArgusEventFactory.focusedField(
            role: "AXTextField",
            label: "API token",
            value: "sk_test_1234567890abcdef"
        )

        XCTAssertEqual(event.kind, .focusedField)
        XCTAssertEqual(event.sensitivity, .high)
        XCTAssertFalse(event.summary.contains("sk_test_1234567890abcdef"))
        XCTAssertTrue(event.summary.contains("[REDACTED_API_KEY]"))
        XCTAssertEqual(event.payload["has_value"], .bool(true))
        XCTAssertEqual(event.rawReference, "local-ax-focused-field")
    }

    func testPermissionStateFactoryEmitsSystemPermissionEvent() {
        let event = ArgusEventFactory.permissionState(
            accessibilityTrusted: true,
            screenRecordingGranted: false
        )

        XCTAssertEqual(event.kind, .permissionState)
        XCTAssertEqual(event.sensitivity, .low)
        XCTAssertTrue(event.summary.contains("Screen Recording"))
        XCTAssertEqual(event.payload["accessibility_trusted"], .bool(true))
        XCTAssertEqual(event.payload["screen_recording_granted"], .bool(false))
    }

    func testSensorControlFactoryEmitsVisibleOperatorControlEvent() {
        let event = ArgusEventFactory.sensorControl(action: "pause", scope: "macos")

        XCTAssertEqual(event.kind, .sensorControl)
        XCTAssertEqual(event.sensitivity, .low)
        XCTAssertEqual(event.payload["action"], .string("pause"))
        XCTAssertEqual(event.payload["scope"], .string("macos"))
    }

    func testPermissionOnboardingOrdersAccessibilityBeforeScreenRecordingFallback() {
        XCTAssertEqual(
            PermissionOnboardingState(
                notificationsGranted: false,
                accessibilityTrusted: false,
                screenRecordingGranted: false
            ).nextStep,
            .notifications
        )
        XCTAssertEqual(
            PermissionOnboardingState(
                notificationsGranted: true,
                accessibilityTrusted: false,
                screenRecordingGranted: false
            ).nextStep,
            .accessibility
        )
        let needsScreen = PermissionOnboardingState(
            notificationsGranted: true,
            accessibilityTrusted: true,
            screenRecordingGranted: false
        )
        XCTAssertEqual(needsScreen.nextStep, .screenRecording)
        XCTAssertTrue(needsScreen.canCollectStructuralSignals)
        XCTAssertFalse(needsScreen.canUseScreenFallback)

        let ready = PermissionOnboardingState(
            notificationsGranted: true,
            accessibilityTrusted: true,
            screenRecordingGranted: true
        )
        XCTAssertEqual(ready.nextStep, .ready)
        XCTAssertTrue(ready.canUseScreenFallback)
    }

    func testIOSUserShareFactoryRedactsUserSelectedText() {
        let event = ArgusEventFactory.userShare(
            sourceApp: "com.apple.mobilesafari",
            contentType: "url",
            title: "Account",
            url: "https://example.com/account",
            text: "Email james@example.com token sk_test_1234567890abcdef"
        )

        XCTAssertEqual(event.platform, .iOS)
        XCTAssertEqual(event.kind, .userShare)
        XCTAssertEqual(event.sensitivity, .high)
        XCTAssertFalse(event.summary.contains("james@example.com"))
        XCTAssertFalse(event.summary.contains("sk_test_1234567890abcdef"))
        XCTAssertTrue(event.summary.contains("[REDACTED_EMAIL]"))
        XCTAssertEqual(event.payload["source_app"], .string("com.apple.mobilesafari"))
        XCTAssertEqual(event.payload["has_text"], .bool(true))
        XCTAssertEqual(event.rawReference, "local-ios-share-extension")
    }

    func testWatchHealthAggregateFactoryKeepsAggregateOnlyPayload() {
        let start = Date(timeIntervalSince1970: 100)
        let end = Date(timeIntervalSince1970: 200)
        let event = ArgusEventFactory.healthAggregate(
            metric: "steps",
            value: 1234,
            unit: "count",
            intervalStart: start,
            intervalEnd: end
        )

        XCTAssertEqual(event.platform, .watchOS)
        XCTAssertEqual(event.kind, .healthSignal)
        XCTAssertEqual(event.sensitivity, .medium)
        XCTAssertEqual(event.payload["metric"], .string("steps"))
        XCTAssertEqual(event.payload["aggregate_only"], .bool(true))
        XCTAssertNil(event.rawReference)
    }

    func testAppLifecycleFactoryEmitsNSWorkspaceLifecycleEvent() {
        let event = ArgusEventFactory.appLifecycle(
            bundleID: "com.apple.Safari",
            appName: "Safari",
            lifecycle: "launched"
        )

        XCTAssertEqual(event.kind, .appLifecycle)
        XCTAssertEqual(event.source, "nsworkspace.app_lifecycle")
        XCTAssertEqual(event.payload["bundle_id"], .string("com.apple.Safari"))
        XCTAssertEqual(event.payload["app_name"], .string("Safari"))
        XCTAssertEqual(event.payload["lifecycle"], .string("launched"))
    }

    func testScreenOCRPolicyRequiresConsentAndScreenRecording() {
        let noConsent = ScreenOCRPolicy(
            userConsented: false,
            screenRecordingGranted: true,
            structuralSignalsAvailable: false
        ).evaluate()
        XCTAssertFalse(noConsent.allowed)
        XCTAssertEqual(noConsent.blockReason, .userConsentMissing)
        XCTAssertFalse(noConsent.includesAudio)

        let missingPermission = ScreenOCRPolicy(
            userConsented: true,
            screenRecordingGranted: false,
            structuralSignalsAvailable: false
        ).evaluate()
        XCTAssertFalse(missingPermission.allowed)
        XCTAssertEqual(missingPermission.blockReason, .screenRecordingPermissionMissing)
        XCTAssertFalse(missingPermission.includesAudio)
    }

    func testScreenOCRPolicyPrefersStructuralSignalsBeforeCapture() {
        let decision = ScreenOCRPolicy(
            userConsented: true,
            screenRecordingGranted: true,
            structuralSignalsAvailable: true
        ).evaluate()

        XCTAssertFalse(decision.allowed)
        XCTAssertEqual(decision.blockReason, .structuralSignalsAvailable)
        XCTAssertFalse(decision.includesAudio)
    }

    func testScreenOCRPolicyAllowsOnlyLowRateNoAudioCapture() {
        let now = Date(timeIntervalSince1970: 100)
        let policy = ScreenOCRPolicy(
            userConsented: true,
            screenRecordingGranted: true,
            structuralSignalsAvailable: false,
            minimumFrameInterval: 3
        )

        let rateLimited = policy.evaluate(
            now: now,
            lastCapturedAt: now.addingTimeInterval(-1)
        )
        XCTAssertFalse(rateLimited.allowed)
        XCTAssertEqual(rateLimited.blockReason, .rateLimited)
        XCTAssertFalse(rateLimited.includesAudio)

        let allowed = policy.evaluate(
            now: now,
            lastCapturedAt: now.addingTimeInterval(-4)
        )
        XCTAssertTrue(allowed.allowed)
        XCTAssertNil(allowed.blockReason)
        XCTAssertEqual(allowed.minimumFrameInterval, 3)
        XCTAssertFalse(allowed.includesAudio)
    }

    func testScreenOCREventBuilderRedactsBeforeSummary() throws {
        let decision = ScreenOCRPolicyDecision(
            allowed: true,
            blockReason: nil,
            minimumFrameInterval: 2,
            includesAudio: false
        )
        let event = try XCTUnwrap(ScreenOCREventBuilder().event(
            observations: [
                ScreenOCRTextObservation(
                    text: "Reset token sk_test_1234567890abcdef for james@example.com",
                    confidence: 0.92
                )
            ],
            decision: decision,
            appName: "Safari",
            windowTitle: "Account"
        ))

        XCTAssertEqual(event.kind, .screenFrame)
        XCTAssertEqual(event.source, "screencapturekit.vision_ocr")
        XCTAssertEqual(event.sensitivity, .high)
        XCTAssertFalse(event.summary.contains("sk_test_1234567890abcdef"))
        XCTAssertFalse(event.summary.contains("james@example.com"))
        XCTAssertTrue(event.summary.contains("[REDACTED_API_KEY]"))
        XCTAssertTrue(event.summary.contains("[REDACTED_EMAIL]"))
        XCTAssertEqual(event.redactionsApplied, ["api_key", "email", "keyword_secret"])
        XCTAssertEqual(event.payload["includes_audio"], .bool(false))
        XCTAssertEqual(event.payload["redaction_before_summary"], .bool(true))
        XCTAssertEqual(event.rawReference, "local-screen-ocr-frame")
    }

    func testScreenOCREventBuilderDropsDisallowedOrEmptyCapture() {
        let builder = ScreenOCREventBuilder()

        XCTAssertNil(builder.event(
            observations: [ScreenOCRTextObservation(text: "Visible text", confidence: 0.7)],
            decision: ScreenOCRPolicyDecision(allowed: false, blockReason: .userConsentMissing)
        ))
        XCTAssertNil(builder.event(
            observations: [ScreenOCRTextObservation(text: "   ", confidence: 0.7)],
            decision: ScreenOCRPolicyDecision(allowed: true, blockReason: nil)
        ))
    }
}
