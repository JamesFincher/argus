import ArgusCore
import Foundation

@MainActor
final class SensorDashboardModel: ObservableObject {
    @Published private(set) var isPaused = true
    @Published private(set) var permissionSnapshot = MacPermissionSnapshot.current()
    @Published private(set) var events: [ArgusEventEnvelope] = []
    @Published private(set) var status = "Paused"

    private let buffer = LocalEventBuffer(limit: 250)
    private let eventSink: (any ArgusEventSink)?
    private let frontmostWindowSensor = FrontmostWindowSensor()
    private let appLifecycleSensor = AppLifecycleSensor()

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
            appLifecycleSensor.start(emit: emit)
            captureSnapshot()
        } else {
            appLifecycleSensor.stop()
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
            try? await eventSink?.append(event)
            events = await buffer.recent(limit: 12)
        }
    }
}
