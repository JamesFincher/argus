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

        MenuBarExtra(ArgusBrand.sensorName, systemImage: model.isPaused ? "eye.slash" : "eye") {
            Button(model.isPaused ? "Resume Sensor" : "Pause Sensor") {
                model.togglePause()
            }
            Button("Capture Snapshot") {
                model.captureSnapshot()
            }
            .disabled(model.isPaused)
            Divider()
            Text(model.status)
        }
    }
}
