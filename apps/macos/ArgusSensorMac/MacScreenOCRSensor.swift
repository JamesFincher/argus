import ArgusCore
import CoreMedia
import Foundation
@preconcurrency import ScreenCaptureKit
@preconcurrency import Vision

@available(macOS 14.0, *)
@MainActor
final class MacScreenOCRSensor {
    enum CaptureError: Error {
        case noDisplayAvailable
        case noFrameCaptured
    }

    private let eventBuilder: ScreenOCREventBuilder
    private let observationProcessor: ScreenOCRObservationProcessor

    init(
        eventBuilder: ScreenOCREventBuilder = ScreenOCREventBuilder(),
        observationProcessor: ScreenOCRObservationProcessor = ScreenOCRObservationProcessor()
    ) {
        self.eventBuilder = eventBuilder
        self.observationProcessor = observationProcessor
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

        let pixelBuffer = try await captureOneFrame(decision: decision)
        let observations = try recognizeText(in: pixelBuffer)
        return eventBuilder.event(
            observations: observations,
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
        configuration.queueDepth = 1
        return configuration
    }

    private func availableShareableContent() async throws -> SCShareableContent {
        try await SCShareableContent.excludingDesktopWindows(
            false,
            onScreenWindowsOnly: true
        )
    }

    private func captureOneFrame(decision: ScreenOCRPolicyDecision) async throws -> CVPixelBuffer {
        let content = try await availableShareableContent()
        guard let display = content.displays.first else {
            throw CaptureError.noDisplayAvailable
        }

        let filter = SCContentFilter(display: display, excludingWindows: [])
        let configuration = makeStreamConfiguration(decision: decision)
        configuration.width = display.width
        configuration.height = display.height

        let output = OneShotScreenFrameOutput()
        let stream = SCStream(filter: filter, configuration: configuration, delegate: nil)
        try stream.addStreamOutput(
            output,
            type: .screen,
            sampleHandlerQueue: DispatchQueue(label: "com.argus.sensor-mac.screen-ocr")
        )

        try await stream.startCapture()
        do {
            let frame = try await output.nextFrame(timeoutSeconds: 3)
            try await stream.stopCapture()
            return frame
        } catch {
            try? await stream.stopCapture()
            throw error
        }
    }

    private func recognizeText(in pixelBuffer: CVPixelBuffer) throws -> [ScreenOCRTextObservation] {
        let request = makeTextRecognitionRequest()
        let handler = VNImageRequestHandler(
            cvPixelBuffer: pixelBuffer,
            orientation: .up,
            options: [:]
        )
        try handler.perform([request])

        let candidates = (request.results ?? []).compactMap { observation in
            observation.topCandidates(1).first.map {
                ScreenOCRRecognizedTextCandidate(
                    text: $0.string,
                    confidence: Double($0.confidence)
                )
            }
        }
        return observationProcessor.observations(from: candidates)
    }

    private func makeTextRecognitionRequest() -> VNRecognizeTextRequest {
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = false
        return request
    }
}

@available(macOS 14.0, *)
private final class OneShotScreenFrameOutput: NSObject, SCStreamOutput, @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<CapturedScreenFrame, Error>?
    private var pendingResult: Result<CapturedScreenFrame, Error>?
    private var didComplete = false

    func nextFrame(timeoutSeconds: UInt64) async throws -> CVPixelBuffer {
        if let pendingResult = lock.withLock({ self.pendingResult }) {
            return try pendingResult.get().pixelBuffer
        }

        let frame: CapturedScreenFrame = try await withCheckedThrowingContinuation { continuation in
            let pendingResult: Result<CapturedScreenFrame, Error>? = lock.withLock {
                if let pendingResult = self.pendingResult {
                    return pendingResult
                }
                self.continuation = continuation
                return nil
            }

            if let pendingResult {
                Self.resume(continuation, with: pendingResult)
                return
            }

            Task {
                try? await Task.sleep(nanoseconds: timeoutSeconds * 1_000_000_000)
                self.finish(.failure(MacScreenOCRSensor.CaptureError.noFrameCaptured))
            }
        }
        return frame.pixelBuffer
    }

    func stream(
        _ stream: SCStream,
        didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
        of outputType: SCStreamOutputType
    ) {
        guard outputType == .screen,
              sampleBuffer.isValid,
              isCompleteFrame(sampleBuffer),
              let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else {
            return
        }

        finish(.success(CapturedScreenFrame(pixelBuffer: pixelBuffer)))
    }

    private func isCompleteFrame(_ sampleBuffer: CMSampleBuffer) -> Bool {
        guard let attachments = CMSampleBufferGetSampleAttachmentsArray(
            sampleBuffer,
            createIfNecessary: false
        ) as? [[SCStreamFrameInfo: Any]],
        let statusRawValue = attachments.first?[.status] as? Int,
        let status = SCFrameStatus(rawValue: statusRawValue) else {
            return true
        }
        return status == .complete
    }

    private func finish(_ result: Result<CapturedScreenFrame, Error>) {
        let continuation = lock.withLock {
            guard !didComplete else {
                return nil as CheckedContinuation<CapturedScreenFrame, Error>?
            }
            didComplete = true
            let continuation = self.continuation
            self.continuation = nil
            if continuation == nil {
                pendingResult = result
            }
            return continuation
        }

        if let continuation {
            Self.resume(continuation, with: result)
        }
    }

    private static func resume(
        _ continuation: CheckedContinuation<CapturedScreenFrame, Error>,
        with result: Result<CapturedScreenFrame, Error>
    ) {
        switch result {
        case .success(let frame):
            continuation.resume(returning: frame)
        case .failure(let error):
            continuation.resume(throwing: error)
        }
    }
}

private struct CapturedScreenFrame: @unchecked Sendable {
    var pixelBuffer: CVPixelBuffer
}

private extension NSLock {
    func withLock<T>(_ body: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try body()
    }
}
