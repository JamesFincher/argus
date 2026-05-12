import ArgusCore
import CoreMedia
import Foundation
import ScreenCaptureKit
import Vision

@available(macOS 14.0, *)
final class MacScreenOCRSensor {
    private let eventBuilder: ScreenOCREventBuilder

    init(eventBuilder: ScreenOCREventBuilder = ScreenOCREventBuilder()) {
        self.eventBuilder = eventBuilder
    }

    func captureOCREvent(
        policy: ScreenOCRPolicy,
        lastCapturedAt: Date? = nil,
        appName: String? = nil,
        windowTitle: String? = nil
    ) async throws -> ArgusEventEnvelope? {
        let decision = policy.evaluate(lastCapturedAt: lastCapturedAt)
        guard decision.allowed else {
            return nil
        }

        _ = try await availableShareableContent()
        _ = makeStreamConfiguration(decision: decision)

        // Runtime capture is intentionally not started until the sensor has explicit consent
        // and no structural Accessibility/NSWorkspace signal can answer the same question.
        // The production path should configure SCStream with audio disabled and feed frames
        // through VNRecognizeTextRequest before calling eventBuilder.event(...).
        return eventBuilder.event(
            observations: [],
            decision: decision,
            appName: appName,
            windowTitle: windowTitle
        )
    }

    private func makeStreamConfiguration(decision: ScreenOCRPolicyDecision) -> SCStreamConfiguration {
        let configuration = SCStreamConfiguration()
        configuration.capturesAudio = false
        configuration.minimumFrameInterval = CMTime(
            seconds: decision.minimumFrameInterval,
            preferredTimescale: 600
        )
        return configuration
    }

    private func availableShareableContent() async throws -> SCShareableContent {
        try await SCShareableContent.excludingDesktopWindows(
            false,
            onScreenWindowsOnly: true
        )
    }

    private func makeTextRecognitionRequest() -> VNRecognizeTextRequest {
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = false
        return request
    }
}
