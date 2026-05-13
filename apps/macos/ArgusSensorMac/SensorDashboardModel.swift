import ArgusCore
import Foundation

@MainActor
final class SensorDashboardModel: ObservableObject {
    @Published private(set) var isPaused = true
    @Published private(set) var permissionSnapshot = MacPermissionSnapshot.current()
    @Published private(set) var events: [ArgusEventEnvelope] = []
    @Published private(set) var status = "Paused"

    private let heartbeatIntervalSeconds = 30
    private let captureIntervalSeconds = 5
    private let buffer = LocalEventBuffer(limit: 250)
    private let eventSink: (any ArgusEventSink)?
    private let frontmostWindowSensor = FrontmostWindowSensor()
    private let appLifecycleSensor = AppLifecycleSensor()
    private var heartbeatTimer: Timer?
    private var captureTimer: Timer?

    init() {
        var sinks: [any ArgusEventSink] = []
        if let spool = try? LocalEventSpool.defaultMacSpool() {
            sinks.append(spool)
        }
        if let gateway = try? LoopbackEventGatewaySink.defaultLocalGateway() {
            sinks.append(gateway)
        }

        if sinks.count == 1 {
            self.eventSink = sinks[0]
        } else if sinks.isEmpty {
            self.eventSink = nil
        } else {
            self.eventSink = CompositeEventSink(sinks)
        }
    }

    func togglePause() {
        isPaused.toggle()
        status = isPaused ? "Paused" : "Active"
        emit(ArgusEventFactory.sensorControl(action: isPaused ? "pause" : "resume"))
        if !isPaused {
            startRuntime()
        } else {
            stopRuntime()
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

        if let focusedFieldEvent = frontmostWindowSensor.captureFocusedFieldEvent() {
            emit(focusedFieldEvent)
        }

        Task {
            events = await buffer.recent(limit: 12)
            status = "Captured \(event.kind.rawValue)"
        }
    }

    func emit(_ event: ArgusEventEnvelope) {
        Task {
            await buffer.append(event)
            do {
                try await eventSink?.append(event)
            } catch {
                await recordSinkError(error)
            }
            events = await buffer.recent(limit: 12)
        }
    }

    private func startRuntime() {
        stopTimers()
        appLifecycleSensor.start(emit: emit)
        emitHeartbeat(status: "ok", mode: "active")
        heartbeatTimer = Timer.scheduledTimer(withTimeInterval: TimeInterval(heartbeatIntervalSeconds), repeats: true) {
            [weak self] _ in
            Task { @MainActor [weak self] in
                self?.emitHeartbeat(status: "ok", mode: "active")
            }
        }
        captureTimer = Timer.scheduledTimer(withTimeInterval: TimeInterval(captureIntervalSeconds), repeats: true) {
            [weak self] _ in
            Task { @MainActor [weak self] in
                self?.captureSnapshot()
            }
        }
        captureSnapshot()
    }

    private func stopRuntime() {
        stopTimers()
        appLifecycleSensor.stop()
        emitHeartbeat(status: "paused", mode: "paused")
    }

    private func stopTimers() {
        heartbeatTimer?.invalidate()
        captureTimer?.invalidate()
        heartbeatTimer = nil
        captureTimer = nil
    }

    private func emitHeartbeat(status: String, mode: String) {
        emit(
            ArgusEventFactory.sensorHeartbeat(
                status: status,
                intervalSeconds: heartbeatIntervalSeconds,
                mode: mode
            )
        )
    }

    private func recordSinkError(_ error: Error) async {
        let message = String(describing: error)
        status = "Sink error: \(message)"
        let errorEvent = ArgusEventFactory.systemError(message: message, stage: "event_sink")
        await buffer.append(errorEvent)
        try? await eventSink?.append(errorEvent)
    }
}
