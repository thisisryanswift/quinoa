# Pause/Resume Implementation

## Summary

Successfully implemented pause/resume functionality for Granola Linux audio recording application.

## Changes Made

### Rust Backend (`granola_audio/src/capture/session.rs`)

1. **Extended `AudioCommand` enum**:
   ```rust
   enum AudioCommand {
       Stop,
       Pause,   // NEW
       Resume,  // NEW
   }
   ```

2. **Added pause/resume events to `InternalAudioEvent`**:
   ```rust
   pub enum InternalAudioEvent {
       Started,
       Stopped,
       Paused,   // NEW
       Resumed,  // NEW
       Error(String),
       Levels { mic: f32, system: f32 },
       DeviceLost(String),
       PipeWireDisconnected,
   }
   ```

3. **Added `is_paused` state to `StreamUserData`**:
   - Shared `Arc<Mutex<bool>>` across all streams
   - Passed to `create_stream()` function
   - Checked in `.process()` callback before writing to encoder

4. **Modified audio processing callback**:
   - Still calculates levels when paused (for VU meters)
   - Only writes to encoder when `!is_paused`
   - Keeps PipeWire streams connected during pause

5. **Updated timer callback in `connect_and_run()`**:
   - Handles `AudioCommand::Pause` → sets `is_paused = true`, sends `Paused` event
   - Handles `AudioCommand::Resume` → sets `is_paused = false`, sends `Resumed` event
   - Continues sending level events during pause

6. **Added Python methods to `RecordingSession`**:
   ```rust
   fn pause(&self) -> PyResult<()>
   fn resume(&self) -> PyResult<()>
   ```

7. **Updated mock implementation**:
   - Simulates pause/resume in non-`real-audio` builds
   - Sends zero levels when paused
   - Properly handles command loop

### Python Frontend (`granola/ui/main_window.py`)

8. **Added pause state tracking**:
   - `self.is_paused` - Current pause state
   - `self.recording_paused_time` - Total time spent paused
   - `self.pause_start_time` - When current pause started

9. **Added pause/resume button**:
   - Orange "Pause" button next to "Stop Recording"
   - Changes to "Resume" when paused
   - Disabled when not recording
   - Styled with orange color (#f39c12)

10. **Added `toggle_pause()` method**:
    - Calls `session.pause()` or `session.resume()`
    - Waits for events to update UI (event-driven)

11. **Updated `update_timer()` to handle pause/resume**:
    - Calculates elapsed time excluding paused periods
    - Handles `"paused"` event:
      - Sets `is_paused = True`
      - Records `pause_start_time`
      - Updates button text to "Resume"
      - Changes status color to orange
    - Handles `"resumed"` event:
      - Sets `is_paused = False`
      - Accumulates paused time
      - Updates button text to "Pause"
      - Restores normal status color
    - Shows "⏸ Paused: MM:SS" in status label when paused

12. **Updated recording lifecycle**:
    - Enable pause button when recording starts
    - Disable pause button when recording stops
    - Reset pause state on stop

### Testing

13. **Created `test_pause_resume.py`**:
    - Records for 2 seconds
    - Pauses for 2 seconds
    - Resumes and records for 2 more seconds
    - Verifies:
      - Pause/resume events are received
      - Levels continue during pause (for monitoring)
      - Output file contains ~4 seconds (not 6)
      - File size is correct (~900KB for 4 sec @ 48kHz stereo)

## How It Works

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Python UI                                                    │
│  ├─ Pause button → session.pause()                          │
│  ├─ Resume button → session.resume()                        │
│  └─ Timer polls events and updates UI                       │
└─────────────────────────────────────────────────────────────┘
                              ▲
                              │ pause()/resume()
                              │ poll_events()
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ RecordingSession (Rust)                                      │
│  ├─ pause() → sends AudioCommand::Pause                     │
│  ├─ resume() → sends AudioCommand::Resume                   │
│  └─ poll_events() → returns Paused/Resumed events           │
└─────────────────────────────────────────────────────────────┘
                              ▲
                              │ commands
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Audio Thread                                                 │
│  ├─ Timer checks command channel every 100ms                │
│  ├─ On Pause: sets is_paused=true, sends Paused event       │
│  ├─ On Resume: sets is_paused=false, sends Resumed event    │
│  └─ Streams continue running (levels still calculated)      │
└─────────────────────────────────────────────────────────────┘
                              ▲
                              │ is_paused flag
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Stream Process Callback                                     │
│  ├─ Always calculates peak levels (for VU meters)           │
│  ├─ Only writes to encoder if !is_paused                    │
│  └─ PipeWire streams stay connected                         │
└─────────────────────────────────────────────────────────────┘
```

### Event Flow

1. **User clicks Pause**:
   - UI calls `session.pause()`
   - Rust sends `AudioCommand::Pause` to audio thread
   - Timer callback receives command
   - Sets `is_paused = true`
   - Sends `InternalAudioEvent::Paused`
   - UI polls and receives `"paused"` event
   - UI updates button to "Resume" and status to "⏸ Paused"

2. **During Pause**:
   - Stream callbacks continue running
   - Levels are calculated and sent to UI (VU meters still work)
   - Audio samples are NOT written to encoder
   - PipeWire connection stays alive
   - Timer continues ticking (but paused time is tracked)

3. **User clicks Resume**:
   - UI calls `session.resume()`
   - Rust sends `AudioCommand::Resume` to audio thread
   - Timer callback receives command
   - Sets `is_paused = false`
   - Sends `InternalAudioEvent::Resumed`
   - UI polls and receives `"resumed"` event
   - UI updates button to "Pause" and status to "Recording"
   - Audio writing resumes

## Design Decisions

### Why Keep Streams Connected During Pause?

- **Faster resume**: No need to reconnect to PipeWire
- **No audio glitches**: Streams don't drop/reconnect
- **VU meters still work**: Users can see if mic is working during pause
- **Simpler implementation**: Just a flag check, no stream lifecycle management

### Why Track Paused Time Separately?

- **Accurate duration**: Database stores actual recording duration (excluding pauses)
- **Better UX**: Timer shows real recording time, not wall-clock time
- **Transcription costs**: Only pay for actual audio recorded

### Why Event-Driven UI Updates?

- **Consistency**: All state changes go through events
- **Testability**: Easy to verify events are sent
- **Robustness**: UI always reflects actual audio thread state

## Testing

### Manual Test

```bash
# Run the test script
./test_pause_resume.py

# Expected output:
# - Recording starts
# - Levels show for 2 seconds
# - Pause event received
# - Levels continue (but not written to file)
# - Resume event received
# - Levels show for 2 more seconds
# - File created with ~4 seconds of audio
```

### Integration Test

```bash
# Run the full UI
.venv/bin/python -m granola

# In the UI:
# 1. Start recording
# 2. Click "Pause" - button should change to "Resume", status shows "⏸ Paused"
# 3. VU meters should still show levels
# 4. Click "Resume" - button changes back to "Pause", status shows "Recording"
# 5. Stop recording
# 6. Check file duration matches recording time (excluding paused time)
```

## Known Limitations

1. **No pause state persistence**: If app crashes during pause, recording is lost (same as before)
2. **No visual indicator of total paused time**: UI only shows current recording time
3. **Levels still calculated during pause**: Minor CPU usage, but needed for UX

## Benefits

✅ **Saves disk space**: Don't record silence during breaks  
✅ **Saves transcription costs**: Only transcribe actual content  
✅ **Better UX**: Users can pause during interruptions  
✅ **Maintains connection**: No audio glitches on resume  
✅ **Event-driven**: Robust state management  
✅ **Tested**: Comprehensive test script included  

## Files Modified

- `granola_audio/src/capture/session.rs` - Core pause/resume logic
- `granola/ui/main_window.py` - UI integration
- `test_pause_resume.py` - **NEW** - Test script

## Next Steps (Remaining P1 Tasks)

All P1 tasks are now complete! ✅

- ✅ Default Device Detection
- ✅ Device Hot-Plug Monitoring  
- ✅ Pause/Resume Functionality

Ready to move on to P2 tasks or other improvements!
