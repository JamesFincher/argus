import AppKit
import ArgusCore
import Foundation

final class AppLifecycleSensor {
    private var tokens: [NSObjectProtocol] = []

    func start(emit: @escaping @MainActor (ArgusEventEnvelope) -> Void) {
        guard tokens.isEmpty else {
            return
        }

        let workspace = NSWorkspace.shared.notificationCenter
        tokens.append(
            workspace.addObserver(
                forName: NSWorkspace.didLaunchApplicationNotification,
                object: nil,
                queue: .main
            ) { notification in
                Self.emitLifecycle("launched", notification: notification, emit: emit)
            }
        )
        tokens.append(
            workspace.addObserver(
                forName: NSWorkspace.didTerminateApplicationNotification,
                object: nil,
                queue: .main
            ) { notification in
                Self.emitLifecycle("terminated", notification: notification, emit: emit)
            }
        )
    }

    func stop() {
        let workspace = NSWorkspace.shared.notificationCenter
        for token in tokens {
            workspace.removeObserver(token)
        }
        tokens.removeAll()
    }

    private static func emitLifecycle(
        _ lifecycle: String,
        notification: Notification,
        emit: @escaping @MainActor (ArgusEventEnvelope) -> Void
    ) {
        guard let app = notification.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication else {
            return
        }

        let event = ArgusEventFactory.appLifecycle(
            bundleID: app.bundleIdentifier,
            appName: app.localizedName ?? "Unknown",
            lifecycle: lifecycle
        )
        Task { @MainActor in
            emit(event)
        }
    }
}
