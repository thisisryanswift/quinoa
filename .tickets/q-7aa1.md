---
id: q-7aa1
status: closed
deps: [quinoa-3dm]
links: []
created: 2026-02-28T14:16:22Z
type: feature
priority: 3
assignee: Ryan Swift
---
# D-Bus rich notification actions (Start Recording button in notifications)

Upgrade meeting notifications from QSystemTrayIcon.showMessage() to D-Bus
notifications (org.freedesktop.Notifications) to support action buttons.

## Goal
- "Start Recording" button directly in the notification when a meeting starts
- Click the button to start recording without switching to the Quinoa window

## Technical Notes
- Use `dbus-python` or `dasbus` for D-Bus integration
- D-Bus notifications support custom actions via the `actions` parameter
- KDE Plasma supports action buttons in notifications
- Falls back to QSystemTrayIcon on non-Linux platforms
- Depends on quinoa-3dm (basic notifications) being implemented first
