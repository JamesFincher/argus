import AppKit
import ApplicationServices
import ArgusCore
import Foundation

struct FrontmostWindowInfo: Codable, Equatable {
    var bundleID: String?
    var appName: String
    var title: String?
}

struct FocusedFieldSnapshot: Codable, Equatable {
    var role: String?
    var label: String?
    var value: String?
}

final class FrontmostWindowSensor {
    private let privacyFilter = ArgusPrivacyFilter()

    func captureFocusedWindowEvent(promptForAccessibility: Bool = false) -> ArgusEventEnvelope? {
        guard let info = currentFrontmostWindow(promptForAccessibility: promptForAccessibility) else {
            return nil
        }

        let title = info.title?.isEmpty == false ? " - \(info.title!)" : ""
        let summary = "Frontmost app: \(info.appName)\(title)"

        return privacyFilter.sanitizedEnvelope(
            platform: .macOS,
            source: "nsworkspace.ax",
            kind: .frontmostWindow,
            summary: summary,
            payload: [
                "bundle_id": info.bundleID.map(ArgusJSONValue.string) ?? .null,
                "app_name": .string(info.appName),
                "window_title": info.title.map(ArgusJSONValue.string) ?? .null
            ]
        )
    }

    func currentFrontmostWindow(promptForAccessibility: Bool = false) -> FrontmostWindowInfo? {
        guard isAccessibilityTrusted(prompt: promptForAccessibility) else {
            return nil
        }

        guard let app = NSWorkspace.shared.frontmostApplication else {
            return nil
        }

        let appElement = AXUIElementCreateApplication(app.processIdentifier)
        var windowRef: CFTypeRef?
        let status = AXUIElementCopyAttributeValue(
            appElement,
            kAXFocusedWindowAttribute as CFString,
            &windowRef
        )

        var title: String?
        if status == .success, let windowRef {
            let windowElement = windowRef as! AXUIElement
            title = copyStringAttribute(windowElement, kAXTitleAttribute as CFString)
        }

        return FrontmostWindowInfo(
            bundleID: app.bundleIdentifier,
            appName: app.localizedName ?? "Unknown",
            title: title
        )
    }

    func readFocusedField() -> FocusedFieldSnapshot? {
        let system = AXUIElementCreateSystemWide()
        var focusedRef: CFTypeRef?
        guard AXUIElementCopyAttributeValue(
            system,
            kAXFocusedUIElementAttribute as CFString,
            &focusedRef
        ) == .success,
        let focusedRef else {
            return nil
        }

        let focusedElement = focusedRef as! AXUIElement
        return FocusedFieldSnapshot(
            role: copyStringAttribute(focusedElement, kAXRoleAttribute as CFString),
            label: copyStringAttribute(focusedElement, kAXDescriptionAttribute as CFString)
                ?? copyStringAttribute(focusedElement, kAXTitleAttribute as CFString),
            value: copyStringAttribute(focusedElement, kAXValueAttribute as CFString)
        )
    }

    private func isAccessibilityTrusted(prompt: Bool) -> Bool {
        AXIsProcessTrustedWithOptions([
            "AXTrustedCheckOptionPrompt": prompt
        ] as CFDictionary)
    }

    private func copyStringAttribute(_ element: AXUIElement, _ attribute: CFString) -> String? {
        var valueRef: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute, &valueRef) == .success else {
            return nil
        }
        return valueRef as? String
    }
}
