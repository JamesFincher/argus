import ArgusCore
import Foundation

@MainActor
final class SensorDashboardModel: ObservableObject {
    @Published private(set) var isPaused = true
    @Published private(set) var permissionSnapshot = MacPermissionSnapshot.current()
    @Published private(set) var events: [ArgusEventEnvelope] = []
    @Published private(set) var status = "Paused"

    private let frontmostWindowSensor = FrontmostWindowSensor()
    private let screenOCRSensor = MacScreenOCRSensor()
    private let appLifecycleSensor = AppLifecycleSensor()
    private let eventRecorder: ArgusRuntimeEventRecorder
    private var lastScreenOCRCapturedAt: Date?
    private lazy var runtimeController = ArgusSensorRuntimeController(
        lifecycleObserver: appLifecycleSensor,
        emit: emit,
        captureSnapshot: captureSnapshot
    )

    init() {
        var sinks: [any ArgusEventSink] = []
        if let spool = try? LocalEventSpool.defaultMacSpool() {
            sinks.append(spool)
        }
        if let gateway = try? LoopbackEventGatewaySink.defaultLocalGateway() {
            sinks.append(gateway)
        }

        if sinks.count == 1 {
            self.eventRecorder = ArgusRuntimeEventRecorder(sink: sinks[0])
        } else if sinks.isEmpty {
            self.eventRecorder = ArgusRuntimeEventRecorder(sink: nil)
        } else {
            self.eventRecorder = ArgusRuntimeEventRecorder(sink: CompositeEventSink(sinks))
        }
    }

    func togglePause() {
        isPaused.toggle()
        status = isPaused ? "Paused" : "Active"
        emit(ArgusEventFactory.sensorControl(action: isPaused ? "pause" : "resume"))
        if !isPaused {
            runtimeController.resume()
        } else {
            runtimeController.pause()
        }
    }

    func refreshPermissions(promptAccessibility: Bool = false) {
        permissionSnapshot = MacPermissionSnapshot.current(promptAccessibility: promptAccessibility)
        emit(permissionSnapshot.event())
    }

    func requestScreenRecording() {
        _ = MacPermissionSnapshot.requestScreenRecording()
        refreshPermissions()
    }

    func captureSnapshot() {
        refreshPermissions()
        guard !isPaused else {
            status = "Paused"
            return
        }

        guard let event = frontmostWindowSensor.captureFocusedWindowEvent() else {
            status = "Waiting for Accessibility permission"
            return
        }

        emit(event)

        let focusedFieldEvent = frontmostWindowSensor.captureFocusedFieldEvent()
        if let focusedFieldEvent {
            emit(focusedFieldEvent)
        }

        captureScreenOCRFallback(
            appName: event.payload.stringValue(for: "app_name"),
            windowTitle: event.payload.stringValue(for: "window_title"),
            structuralSignalsAvailable: focusedFieldEvent != nil
        )

        Task {
            events = await eventRecorder.recent(limit: 12)
            status = "Captured \(event.kind.rawValue)"
        }
    }

    func emit(_ event: ArgusEventEnvelope) {
        Task {
            let result = await eventRecorder.append(event)
            if let errorMessage = result.sinkErrorMessage {
                status = "Sink error: \(errorMessage)"
            }
            events = await eventRecorder.recent(limit: 12)
        }
    }

    private func captureScreenOCRFallback(
        appName: String?,
        windowTitle: String?,
        structuralSignalsAvailable: Bool
    ) {
        let policy = ScreenOCRPolicy(
            userConsented: !isPaused,
            screenRecordingGranted: permissionSnapshot.screenRecordingGranted,
            structuralSignalsAvailable: structuralSignalsAvailable
        )

        Task {
            do {
                let capturedAt = Date()
                guard let event = try await screenOCRSensor.captureOCREvent(
                    policy: policy,
                    lastCapturedAt: lastScreenOCRCapturedAt,
                    appName: appName,
                    windowTitle: windowTitle
                ) else {
                    return
                }
                lastScreenOCRCapturedAt = capturedAt
                emit(event)
                status = "Captured \(event.kind.rawValue)"
            } catch {
                status = "Screen OCR unavailable: \(error)"
            }
        }
    }
}

private extension Dictionary where Key == String, Value == ArgusJSONValue {
    func stringValue(for key: String) -> String? {
        guard case .string(let value) = self[key] else {
            return nil
        }
        return value
    }
}
