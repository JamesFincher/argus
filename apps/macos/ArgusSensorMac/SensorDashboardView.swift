import ArgusCore
import SwiftUI

struct SensorDashboardView: View {
    @ObservedObject var model: SensorDashboardModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            header
            permissionGrid
            Divider()
            eventList
            Spacer(minLength: 0)
        }
        .padding(24)
        .onAppear {
            model.refreshPermissions()
        }
    }

    private var header: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 6) {
                Text(ArgusBrand.sensorName)
                    .font(.system(size: 30, weight: .semibold))
                Text(model.status)
                    .font(.callout)
                    .foregroundStyle(model.isPaused ? Color.secondary : Color.green)
            }

            Spacer()

            Button(model.isPaused ? "Resume" : "Pause") {
                model.togglePause()
            }
            .buttonStyle(.borderedProminent)

            Button("Snapshot") {
                model.captureSnapshot()
            }
            .disabled(model.isPaused)
        }
    }

    private var permissionGrid: some View {
        Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 10) {
            GridRow {
                PermissionStatusView(
                    title: "Accessibility",
                    isGranted: model.permissionSnapshot.accessibilityTrusted
                )
                Button("Request") {
                    model.refreshPermissions(promptAccessibility: true)
                }
            }

            GridRow {
                PermissionStatusView(
                    title: "Screen Recording",
                    isGranted: model.permissionSnapshot.screenRecordingGranted
                )
                Button("Request") {
                    model.requestScreenRecording()
                }
            }
        }
    }

    private var eventList: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Recent Events")
                .font(.headline)

            if model.events.isEmpty {
                ContentUnavailableView(
                    "No Events",
                    systemImage: "eye.slash",
                    description: Text("Resume Argus Sensor and capture a snapshot.")
                )
            } else {
                List(model.events) { event in
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Text(event.kind.rawValue)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Spacer()
                            Text(event.sensitivity.rawValue)
                                .font(.caption)
                                .foregroundStyle(event.sensitivity >= .high ? .red : .secondary)
                        }
                        Text(event.summary)
                            .font(.body)
                            .lineLimit(2)
                    }
                    .padding(.vertical, 3)
                }
                .listStyle(.inset)
            }
        }
    }
}

private struct PermissionStatusView: View {
    var title: String
    var isGranted: Bool

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: isGranted ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                .foregroundStyle(isGranted ? .green : .orange)
            Text(title)
                .frame(width: 150, alignment: .leading)
            Text(isGranted ? "Granted" : "Needed")
                .foregroundStyle(.secondary)
        }
    }
}
