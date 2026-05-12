import ArgusCore
import Foundation

@MainActor
final class SensorDashboardModel: ObservableObject {
    @Published private(set) var isPaused = true
    @Published private(set) var permissionSnapshot = MacPermissionSnapshot.current()
    @Published private(set) var events: [ArgusEventEnvelope] = []
    @Published private(set) var status = "Paused"

    private let buffer = LocalEventBuffer(limit: 250)
    private let eventSink: LocalEventSpool?
    private let frontmostWindowSensor = FrontmostWindowSensor()

    init() {
        self.eventSink = try? LocalEventSpool.defaultMacSpool()
    }

    func togglePause() {
        isPaused.toggle()
        status = isPaused ? "Paused" : "Active"
        if !isPaused {
            captureSnapshot()
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

    private func emit(_ event: ArgusEventEnvelope) {
        Task {
            await buffer.append(event)
            try? await eventSink?.append(event)
            events = await buffer.recent(limit: 12)
        }
    }
}
