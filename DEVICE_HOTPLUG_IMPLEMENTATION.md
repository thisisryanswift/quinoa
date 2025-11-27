# Device Hot-Plug Monitoring Implementation

## Summary

Successfully implemented device hot-plug monitoring for Granola Linux audio recording application.

## Changes Made

### Rust Backend (`granola_audio/`)

1. **Created `src/device/monitor.rs`**:
   - `DeviceEvent` struct with fields: `type_`, `device_id`, `device_name`
   - `DeviceMonitor` class with `poll()` and `stop()` methods
   - `start_monitoring()` function that spawns background thread
   - `run_monitor_thread()` that listens to PipeWire registry events:
     - `global` event → device added
     - `global_remove` event → device removed
   - Watchdog timer (200ms) to check for stop signal
   - Mock implementation for non-`real-audio` builds

2. **Updated `src/device/mod.rs`**:
   - Added `pub mod monitor;` to include the monitor module

3. **Updated `src/lib.rs`**:
   - Moved `DeviceEvent` and `DeviceMonitor` to top level (always available)
   - Added `subscribe_device_changes()` Python function
   - Registered `DeviceMonitor` and `DeviceEvent` classes in Python module
   - Removed `#[cfg(feature = "real-audio")]` from `mod device;` declaration

### Python Frontend (`granola/`)

4. **Updated `granola/ui/main_window.py`**:
   - Added `self.device_monitor` field to `__init__`
   - Start device monitor in `__init__` after `refresh_devices()`
   - Poll device events in `update_timer()` method
   - Call `refresh_devices()` when "added" or "removed" events detected
   - Stop monitor in `closeEvent()` when app quits

### Testing

5. **Created `test_device_monitor.py`**:
   - Standalone test script for device monitoring
   - Polls every 200ms and prints device events
   - Can be used to manually test hot-plug by connecting/disconnecting USB audio devices

## How It Works

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Python UI (main_window.py)                                  │
│  ├─ update_timer() [every 100ms]                            │
│  │   ├─ Poll recording session events (levels, errors)      │
│  │   └─ Poll device monitor events (added, removed)         │
│  └─ refresh_devices() when device event detected            │
└─────────────────────────────────────────────────────────────┘
                              ▲
                              │ poll()
                              │
┌─────────────────────────────────────────────────────────────┐
│ DeviceMonitor (Rust)                                         │
│  ├─ Background thread running PipeWire main loop            │
│  ├─ Registry listener for global/global_remove events       │
│  ├─ Channel (event_tx → event_rx) for event queue           │
│  └─ Watchdog timer (200ms) to check stop signal             │
└─────────────────────────────────────────────────────────────┘
                              ▲
                              │ registry events
                              │
┌─────────────────────────────────────────────────────────────┐
│ PipeWire                                                     │
│  └─ Emits "global" and "global_remove" when devices change  │
└─────────────────────────────────────────────────────────────┘
```

### Event Flow

1. **Device Added**:
   - User plugs in USB microphone
   - PipeWire emits `global` event with device properties
   - Monitor thread filters for `Audio/Source` or `Audio/Sink`
   - Creates `DeviceEvent { type_: "added", device_id, device_name }`
   - Sends event through channel
   - Python UI polls `monitor.poll()` in timer
   - Receives event and calls `refresh_devices()`
   - Device list updates with new device

2. **Device Removed**:
   - User unplugs USB microphone
   - PipeWire emits `global_remove` event with device ID
   - Monitor thread creates `DeviceEvent { type_: "removed", device_id, device_name: None }`
   - Python UI receives event and refreshes device list
   - Device disappears from dropdown

## Testing

### Manual Test

```bash
# Terminal 1: Run the test script
./test_device_monitor.py

# Terminal 2: Simulate device changes
# Plug in a USB microphone or Bluetooth headset
# You should see "added" events in Terminal 1

# Unplug the device
# You should see "removed" events in Terminal 1
```

### Integration Test

```bash
# Run the full UI
.venv/bin/python -m granola

# In the UI:
# 1. Note the current microphone list
# 2. Plug in a USB microphone
# 3. The dropdown should automatically update with the new device
# 4. Unplug the device
# 5. The dropdown should update again
```

## Known Limitations

1. **Initial Device Scan**: When the monitor starts, PipeWire sends `global` events for all existing devices. This is expected behavior and filtered out by only refreshing when events occur during runtime.

2. **Default Device Changes**: Currently only detects add/remove events. Default device changes are handled separately by the `enumerate` module.

3. **Type Checker Warnings**: PyLance/Pyright don't know about Rust module exports, so you'll see warnings in the IDE. These are cosmetic and don't affect runtime.

## Next Steps (P1 Tasks)

- [ ] Implement Pause/Resume functionality
- [ ] Add device selection persistence (remember last used device)
- [ ] Handle device removal during active recording (graceful degradation)

## Files Modified

- `granola_audio/src/device/mod.rs` - Added monitor module
- `granola_audio/src/device/monitor.rs` - **NEW** - Device monitoring implementation
- `granola_audio/src/lib.rs` - Exported DeviceMonitor and subscribe_device_changes
- `granola/ui/main_window.py` - Integrated device monitor into UI
- `test_device_monitor.py` - **NEW** - Standalone test script

## Build Commands

```bash
# Build Rust library
cd granola_audio && cargo check

# Build Python package
cd .. && maturin develop --release

# Run tests
.venv/bin/python test_device_monitor.py
.venv/bin/python -m granola
```
