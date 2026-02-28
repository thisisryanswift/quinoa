---
id: quinoa-3dm
status: open
deps: []
links: []
created: 2025-12-09T14:49:01.349216731-05:00
type: epic
priority: 2
---
# Meeting Notifications & Recording Reminders

Pass through Google Calendar notifications to the system and add recording reminders.

## Features

### 1. Calendar Notification Pass-through
- Mirror Google Calendar's notification settings from the API
- Use system notifications (D-Bus / libnotify on Fedora KDE)
- Show meeting title, time, and attendees in notification
- Click notification to open Quinoa and select that meeting

### 2. Recording Reminder
- If a meeting has started (based on calendar time) and recording hasn't begun:
  - Show a **persistent** notification (user must dismiss)
  - 'Your meeting "Weekly 1:1" started 2 minutes ago. Start recording?'
  - **Action button: 'Start Recording'** - starts recording directly from notification
  - No repeated reminders, just one persistent notification
- Configurable grace period in settings

### 3. Settings
- Toggle: Enable/disable meeting notifications
- Toggle: Enable/disable recording reminders  
- Toggle: Notify for all meetings vs only meetings with video links (Meet/Zoom/Teams)
- Configure reminder delay (how long after meeting start before warning)

## Technical Considerations
- Use D-Bus notifications for KDE integration (supports action buttons)
- Fallback to QSystemTrayIcon.showMessage() for cross-platform
- Poll calendar events via CalendarSyncWorker or dedicated NotificationWorker
- Parse Google Calendar reminder settings from API response

## Notification Flow
1. Calendar sync pulls events with their reminder settings
2. NotificationWorker schedules timers based on reminder times
3. At reminder time: show system notification
4. At meeting start + grace period: if not recording, show persistent 'Start Recording?' notification
5. User clicks 'Start Recording' → Quinoa starts recording for that meeting

## Sub-tasks
- [ ] Research D-Bus notification API for KDE (with action buttons)
- [ ] Add notification settings to SettingsDialog
- [ ] Create NotificationWorker to schedule/trigger notifications
- [ ] Implement pre-meeting reminder notifications
- [ ] Implement 'recording not started' persistent warning
- [ ] Add 'Start Recording' action button handler
- [ ] Parse Google Calendar reminder settings from sync
- [ ] Store notification preferences in config


