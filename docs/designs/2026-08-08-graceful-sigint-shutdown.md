---
status: approved
approved_at: 2026-08-08T15:19:19-04:00
approved_body_sha256: 38a8ed2a14a8abd1b6efd78b517c8b3301f4f0d34588a4acf546962742c76ac2
execution_authorized: true
---

# Graceful SIGINT Shutdown Design

## Goal

Make every explicit application quit request—including terminal `Ctrl+C`—follow one idempotent Qt shutdown path that finalizes an active recording, saves its state, cancels workers with existing bounded/cooperative behavior, and exits without starting new background work.

A window-manager close may continue minimizing Quinoa to the system tray. Repeated SIGINT signals are coalesced rather than escalating to forced termination.

## Context

Quinoa currently installs `SIG_DFL` for SIGINT in `quinoa/main.py`, so `Ctrl+C` terminates the process without Qt cleanup. `MainWindow.closeEvent()` saves window state and stops background workers, but it does not explicitly stop/finalize `MiddlePanel.recording_session`. Tray Quit sets `_quitting` and calls `QApplication.quit()` directly, Ctrl+Q calls `window.close()`, and smoke-test exit also calls `app.quit()`, so explicit quit entrypoints are not centralized.

`MiddlePanel._stop_recording()` already provides the required recording semantics: it calls the Rust session's blocking finalizer, saves notes and duration, records `completed` or `failed` status, resets timers/UI state, and suppresses auto-transcription after a stop error. Its normal clean-stop behavior intentionally schedules auto-transcription, which must not happen while the process is shutting down.

Current worker cleanup is cooperative and bounded. Timed-out UI workers are kept alive in `_PENDING_WORKERS` until their terminal signal; no thread termination is used. The implementation must preserve that behavior.

The repository is clean on `main` at `b038a2138af6bff21abc18d5ed2e7c02051bb7b8`, with `qui-hnvy` open and no in-progress Ticket.

## Decisions

1. **Use one explicit window quit entrypoint.** `MainWindow.request_quit()` sets the quit intent once and closes the window, ensuring tray-aware `closeEvent()` takes the actual-cleanup branch.
2. **Centralize idempotent cleanup.** Extract the existing close cleanup into a guarded method so duplicate close/quit requests cannot repeat recording finalization or worker shutdown.
3. **Finalize recording before workers and devices.** Shutdown first stops any active recording through a dedicated `MiddlePanel.stop_recording_for_shutdown()` method, then runs the existing worker/device/tray cleanup order.
4. **Do not launch work while exiting.** Shutdown recording finalization cancels any pending auto-transcription timer, suppresses clean-stop auto-transcription, and suppresses modal recording-error dialogs while retaining logs and failed recording status.
5. **Bridge SIGINT through Qt's event loop using CPython's wakeup fd.** A process-lifetime `SigintBridge` registers a nonblocking self-pipe write descriptor with `signal.set_wakeup_fd(..., warn_on_full_buffer=False)` and uses a no-op Python SIGINT handler. CPython's low-level signal machinery writes the signal byte immediately even while `app.exec()` is idle in C++; `QSocketNotifier` observes the read descriptor and requests window quit in the Qt thread.
6. **Coalesce repeated SIGINT.** The bridge emits one quit request, ignores later SIGINTs, and never force-terminates the process.
7. **Unify explicit quit paths.** SIGINT, tray Quit, Ctrl+Q, successful smoke-test exit, and no-device smoke-test exit call `MainWindow.request_quit()`. A regular window close retains minimize-to-tray behavior when tray support is active.
8. **Retain current failure truthfulness.** If Rust recording finalization fails, the recording remains marked `failed` with best-effort duration/notes and shutdown continues. Unexpected shutdown-recording exceptions are logged before the remaining cleanup proceeds.

Alternatives rejected:

- Keeping `SIG_DFL` preserves terminal responsiveness by sacrificing recording integrity.
- Calling application quit directly from a Python signal callback performs too much work at the signal boundary and does not provide one explicit idempotent window entrypoint.
- Polling a flag with a periodic timer is simpler but adds continuous wakeups and signal-handling latency; the self-pipe integrates directly with Qt's event loop.
- A second SIGINT force-exit would reintroduce the data-loss path this change is intended to remove.

## Behavior

### Explicit quit

On the first explicit quit request:

1. `MainWindow.request_quit()` records quit intent and calls `close()`.
2. `closeEvent()` bypasses minimize-to-tray behavior and enters guarded shutdown.
3. Any active recording is stopped/finalized synchronously. Notes, duration, end timestamp, signals, and completed/failed database status follow existing behavior.
4. Pending auto-transcription is canceled and no new transcription is scheduled.
5. Sync, transcription, calendar, notification, compression, enhancement, chat, device-monitor, D-Bus, and tray cleanup follows existing cooperative/bounded behavior.
6. The close event is accepted and the Qt event loop exits.

If no recording is active, shutdown still cancels a pending auto-transcription timer before cleaning workers.

### SIGINT

- CPython writes the SIGINT byte to the registered nonblocking wakeup descriptor from its low-level signal machinery; the Python handler itself is a no-op.
- `QSocketNotifier` drains pending bytes, marks the request emitted, unregisters the wakeup descriptor for the remainder of shutdown, disables further notification, and emits one quit request on the Qt thread.
- Additional SIGINTs before or during shutdown are ignored/coalesced.
- No forced-exit fallback is installed.

### Non-quit close

Clicking the window close control while the system tray is available and no explicit quit was requested continues hiding the window and leaves any recording running.

## Architecture

### `quinoa/main.py`

Add a small `SigintBridge(QObject)` that:

- runs setup from `main()` on Python's main thread, creates nonblocking read/write pipe descriptors, and treats any `set_wakeup_fd()`/handler/notifier setup exception as a visible startup failure with no fallback;
- stores the previous wakeup descriptor, registers the write descriptor with `signal.set_wakeup_fd(..., warn_on_full_buffer=False)`, then preserves and replaces the previous SIGINT handler with a no-op callback that neither logs nor raises;
- owns a `QSocketNotifier` that monitors the read descriptor;
- marks the quit request emitted before draining all readable bytes, unregisters the wakeup descriptor for the remainder of shutdown, disables the notifier, and emits a Qt signal once; because the bridge and window live on the Qt main thread, the connected quit request runs synchronously in that thread;
- restores the previous wakeup descriptor first and then the previous SIGINT handler, disables the notifier, and closes both descriptors through an idempotent disposal method; disposal catches/logs restoration or close errors and never raises from `aboutToQuit`;
- rolls back setup in reverse acquisition order if any later step fails: restore an installed handler, restore an installed wakeup descriptor, disable/delete a created notifier, then close opened descriptors. Rollback is best-effort, preserves the original setup exception, and does not attempt fallback signal behavior.

`main()` creates the bridge after the window, connects its Qt signal to `window.request_quit`, keeps it alive for the application lifetime, and disposes it from `aboutToQuit`. Remove the `SIG_DFL` assignment and stale TODO.

Update smoke-test helpers so successful, no-device, and failed-start exits call `window.request_quit()` rather than `app.quit()`. The stop helper checks `middle_panel.is_recording` before toggling, so a failed initial start cannot accidentally begin a new recording during shutdown.

### `quinoa/ui/main_window.py`

Add `_shutdown_started = False` during initialization.

Add `request_quit()` as the sole explicit quit entrypoint. It coalesces duplicate requests by checking `_quitting`, sets `_quitting = True`, and calls `close()`.

Extract the actual cleanup branch into an idempotent `_cleanup_for_exit()` method. Its first operation checks `_shutdown_started`; if true it returns immediately, otherwise it sets the flag before touching any resource. It calls `middle_panel.stop_recording_for_shutdown()` before existing worker cleanup. An unexpected exception from that recording-shutdown call is logged, then remaining cleanup continues. The device monitor remains later in the sequence because it only reports hot-plug events and does not own the active recording session.

`closeEvent()` keeps current minimize-to-tray behavior for an ordinary close. If `_shutdown_started` is already true, it accepts the event without further work. Otherwise an actual-close path sets quit intent, invokes `_cleanup_for_exit()`, and accepts the event.

Connect Ctrl+Q to `request_quit()` rather than `close()`.

### `quinoa/ui/middle_panel.py`

Add `stop_recording_for_shutdown()` that sets the existing `_shutting_down` flag before any callbacks can run, always stops `_auto_transcribe_timer`, calls `_stop_recording(shutting_down=True)` when a session exists, and ensures the timer remains stopped.

Add a keyword-only `shutting_down: bool = False` parameter to `_stop_recording()`. In shutdown mode it:

- preserves finalization, notes, duration, status, state reset, and emitted signals;
- does not show a modal recording-error dialog;
- unconditionally skips auto-transcription regardless of configuration or API-key state.

While `_shutting_down` is true, asynchronous audio, transcription, and enhancement error callbacks log/update noninteractive state as appropriate but do not open modal dialogs that could block process exit. All existing recording-stop callers retain current behavior through the default value.

### `quinoa/ui/tray_icon.py`

Route tray Quit only to `parent_window.request_quit()`. Remove its direct `_quitting` mutation, direct `QApplication.quit()` call, and now-unused `QApplication` dependency.

### Tests

Add focused regression tests in a new `tests/python/test_shutdown.py` module so process/quit routing remains separate from worker lifecycle regressions:

1. A `SigintBridge` test writes representative signal bytes directly to its pipe without sending a real OS signal, processes Qt events, and proves exactly one queued quit request for repeated bytes. It verifies wakeup-descriptor and handler restoration on disposal.
2. `MainWindow.request_quit()` sets intent, closes once, and coalesces duplicates.
3. The actual-close cleanup path calls recording shutdown before worker/device cleanup and remains idempotent.
4. Clean shutdown recording finalization uses existing database/status behavior but leaves auto-transcription inactive.
5. Tray Quit delegates to the shared window entrypoint.

No test records audio, calls live APIs, or force-terminates the test process.

## Failure And Recovery

- `warn_on_full_buffer=False` suppresses wakeup-fd overflow warnings because signal-byte identity is irrelevant and one pending byte is sufficient to request shutdown.
- The wakeup descriptor is unregistered after the first notifier activation, so repeated SIGINT cannot fill the pipe during a long synchronous cleanup.
- Disposal is idempotent. It restores the previous wakeup descriptor and SIGINT handler, disables notification, and closes descriptors once.
- Recording finalization errors continue producing failed recording status and logs. Shutdown-mode UI does not block on a modal dialog.
- An unexpected exception around shutdown recording handling is logged and does not prevent remaining worker/device cleanup.
- Existing bounded waits and process-lifetime pending-worker retention remain unchanged.
- If the pipe, wakeup descriptor, handler, or notifier cannot be installed at startup, reverse-order rollback runs and initialization re-raises the original error visibly rather than silently restoring unsafe `SIG_DFL` behavior.

## Safety

- CPython's wakeup-fd mechanism performs the nonblocking pipe write at low-level signal delivery; the Python callback is a no-op and application cleanup runs in the Qt main thread.
- Repeated SIGINT never bypasses recording finalization.
- Unit tests write directly to the isolated pipe and mock recording sessions; they do not send process signals or create user recordings.
- No database migration, credential, MCP, network, publishing, or dependency change is involved.
- No commit, push, or public write occurs without the already established human authorization boundary for this workstream.

## Testing And Verification

Fresh completion evidence must include:

1. Red regression evidence showing the current SIGINT/default-quit path does not request graceful window cleanup and current close cleanup omits active recording stop.
2. Focused SIGINT bridge, quit coalescing, recording shutdown, close cleanup, and tray delegation tests passing.
3. Existing recording failure/lifecycle and worker cleanup regression tests passing.
4. `./scripts/check.sh` exiting zero, including Python tests against mock audio, mock/real Cargo checks and tests, and real extension restoration.
5. `git diff --check` and clean review of all changed files.
6. Independent read-only integrated review against this design, followed by focused re-review for any material fixes.
7. A bounded inline shell diagnostic starts `QT_QPA_PLATFORM=offscreen uv run python -c ...` with only `QApplication` plus `SigintBridge`, waits for a flushed `ready` marker, sends SIGINT to that child PID, and requires a flushed `quit-requested` marker plus exit status 0 within two seconds. On timeout it terminates only the child it created and fails the diagnostic. It uses no fallback timer, Quinoa window, recording, database, or user data.
8. Hosted CI success after an authorized push.

Manual real-recording SIGINT testing is excluded unless separately requested; automated mocks plus the isolated child diagnostic prove signal delivery and shutdown routing without risking user data.

## Rollout And Rollback

No data migration is required. The change affects process signal routing and existing quit entrypoints.

Rollback is file-scoped: restore the previous quit connections and remove the bridge/recording-shutdown seam. Existing recording/database formats are unchanged.

## Non-Goals

- Adding a force-exit-on-second-SIGINT path.
- Changing normal minimize-to-tray behavior.
- Redesigning worker cancellation timeouts or pending-worker ownership.
- Fixing unrelated recording, worker, notification, or tray behavior.
- Running a real recording or live API during automated verification.
- Handling non-SIGINT Unix signals.
- Cross-platform support beyond Quinoa's current Linux target.

## Acceptance Criteria

- Terminal Ctrl+C requests the same explicit graceful window shutdown as tray Quit, Ctrl+Q, and smoke-test exit.
- Repeated SIGINT and repeated explicit quit requests cause exactly one cleanup sequence and never force termination.
- An active recording is finalized before worker/device cleanup; notes and best-effort duration persist with truthful completed/failed status.
- Shutdown never schedules auto-transcription or blocks on a recording-error modal.
- Ordinary window close still minimizes to tray when available.
- Existing cooperative/bounded worker cleanup and pending-worker retention are preserved.
- Signal bridge resources, the previous wakeup descriptor, and the previous handler are released/restored on exit.
- Focused regression tests and the canonical local/hosted CI gates pass without real recordings or live APIs.
