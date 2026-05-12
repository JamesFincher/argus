import ArgusCore
import SwiftUI

@main
struct ArgusSensorMacApp: App {
    @StateObject private var model = SensorDashboardModel()

    var body: some Scene {
        WindowGroup(ArgusBrand.sensorName) {
            SensorDashboardView(model: model)
                .frame(minWidth: 720, minHeight: 520)
        }
        .commands {
            CommandMenu("Argus") {
                Button(model.isPaused ? "Resume Sensor" : "Pause Sensor") {
                    model.togglePause()
                }
                .keyboardShortcut("p", modifiers: [.command, .shift])

                Button("Capture Snapshot") {
                    model.captureSnapshot()
                }
                .keyboardShortcut("r", modifiers: [.command])
            }
        }
    }
}
