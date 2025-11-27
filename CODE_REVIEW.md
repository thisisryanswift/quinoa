# Granola Linux - Comprehensive Code Review

**Review Date:** 2025-11-26
**Reviewer:** Claude Code
**Review Scope:** Full implementation against IMPLEMENTATION_GUIDE.md
**Implementation Phase:** Phase 2 (Core Application) - Mostly Complete

---

## Executive Summary

The Granola Linux implementation has made substantial progress toward the goals outlined in the IMPLEMENTATION_GUIDE.md. The core audio capture functionality (Phase 1) and most of the application layer (Phase 2) have been implemented. The codebase demonstrates solid architectural decisions and generally follows the design patterns specified in the guide.

### Overall Assessment

- **Implemented Features:** ~75% of Phase 1 and Phase 2 complete
- **Code Quality:** Good - follows Rust/Python best practices
- **Architecture Adherence:** Strong - closely matches the guide
- **Critical Issues:** 4 found
- **Major Issues:** 8 found
- **Minor Issues:** 12 found
- **Recommendations:** 15 total

---

## 1. Architecture Review

### 1.1 High-Level Architecture ✅ GOOD

**Status:** Matches the guide's architecture diagram

The implementation correctly separates concerns:
- Rust layer (`granola_audio`) handles PipeWire integration
- Python layer (`granola`) provides application logic and GUI
- PyO3 provides clean bindings between the two

**Files Reviewed:**
- `granola_audio/src/lib.rs` - PyO3 module definition
- `granola/main.py` - Application entry point
- `granola/ui/main_window.py` - GUI implementation

**Evidence:**
```python
# Clean API usage as specified in guide
import granola_audio
devices = granola_audio.list_devices()
session = granola_audio.start_recording(config)
```

---

## 2. Rust Audio Layer (`granola_audio`)

### 2.1 PyO3 Bindings ✅ GOOD

**Location:** `granola_audio/src/lib.rs`

**Strengths:**
- Clean PyO3 class definitions for `Device`, `DeviceType`, `RecordingConfig`, `RecordingSession`
- Proper use of `#[pyclass]` and `#[pymethods]` macros
- Mock implementation for testing when `real-audio` feature is disabled
- Good separation of feature flags (`real-audio` vs `mock`)

**Issues Found:**

#### 🔴 CRITICAL: Missing Event Polling API
**Severity:** Critical
**Location:** `lib.rs:54-77`

The guide specifies (lines 201-208) a `poll_events()` method on `RecordingSession` for non-blocking event polling:

```rust
fn poll_events(&self) -> PyResult<Vec<AudioEvent>> {
    // Non-blocking poll for UI updates
}
```

**Current Implementation:** Missing entirely

**Impact:**
- Cannot implement VU meters (audio level monitoring)
- Cannot handle device disconnect events gracefully
- Cannot notify UI of PipeWire reconnection
- Missing critical error handling capability

**Recommendation:** Implement the event channel system as specified in the guide (lines 159-175).

---

#### 🔴 CRITICAL: Missing AudioLevels/VU Meter Support
**Severity:** Critical
**Location:** `capture/session.rs`

The guide specifies (lines 343-378) audio level monitoring for VU meters:

```rust
struct AudioLevels {
    mic_peak: f32,
    mic_rms: f32,
    system_peak: f32,
    system_rms: f32,
}
```

**Current Implementation:** Not implemented

**Impact:**
- Users have no visual feedback that audio is being captured
- Cannot detect silent recordings (mic muted, wrong device selected)
- Poor user experience during recording

**Recommendation:** Add level calculation in the stream process callback and expose via events.

---

### 2.2 Device Enumeration ⚠️ NEEDS IMPROVEMENT

**Location:** `granola_audio/src/device/enumerate.rs`

**Strengths:**
- Correctly uses PipeWire registry to enumerate nodes
- Properly identifies `Audio/Source` and `Audio/Sink`
- Detects Bluetooth devices via `device.api == "bluez5"`
- Uses stable node names for IDs

**Issues Found:**

#### 🟠 MAJOR: Default Device Detection Not Implemented
**Severity:** Major
**Location:** `enumerate.rs:69`

```rust
is_default: false, // TODO: Implement default device detection via Metadata
```

**Impact:**
- Users must manually select microphone every time
- Guide specifies `get_default_microphone()` function (line 330)
- Poor UX for first-time users

**Recommendation:** Implement PipeWire metadata API to detect default nodes. See PipeWire documentation on metadata objects.

---

#### 🟠 MAJOR: Hardcoded Sample Rate and Channel Count
**Severity:** Major
**Location:** `enumerate.rs:59-60`

```rust
let sample_rate = 48000;
let channels = 2;
```

**Current Behavior:** All devices reported as 48kHz stereo, regardless of actual capabilities

**Impact:**
- Misleading device information displayed to users
- May cause issues when recording from mono microphones
- Bluetooth HFP devices typically 16kHz mono, not 48kHz stereo

**Recommendation:** Query actual device formats via PipeWire param enumeration. This requires subscribing to param changes on the node object.

---

#### 🟡 MINOR: Bluetooth Profile Detection Missing
**Severity:** Minor
**Location:** `enumerate.rs:53-56`

The guide specifies detecting Bluetooth profile (A2DP, HFP, HSP) to warn users when mic is unavailable (lines 573-596).

**Current Implementation:** Only detects `is_bluetooth: bool`

**Impact:**
- Cannot warn users when Bluetooth headset is in A2DP mode (mic unavailable)
- Missing validation specified in guide (lines 602-621)

**Recommendation:** Parse PipeWire node properties to determine active profile. Look for `device.profile.name` property.

---

### 2.3 Recording Session ⚠️ PARTIAL

**Location:** `granola_audio/src/capture/session.rs`

**Strengths:**
- Correctly implements dedicated audio thread pattern (guide lines 117-149)
- Proper use of channels for command passing
- Releases GIL during blocking operations (lines 69-72)
- Good stream creation abstraction

**Issues Found:**

#### 🔴 CRITICAL: No Error Recovery or Watchdog
**Severity:** Critical
**Location:** `session.rs:252-328`

The guide extensively covers error handling and recovery (lines 902-1097):
- PipeWire disconnect detection
- Auto-reconnection logic
- Device loss handling
- Event emission to Python layer

**Current Implementation:** `run_audio_thread()` has no error handling beyond basic `Result` returns

**Example Missing:**
```rust
// Guide specifies (lines 989-1036):
fn run_with_watchdog(&mut self) {
    loop {
        match self.connect_pipewire() {
            Ok(core) => {
                match self.capture_loop(&core) {
                    Err(PipeWireError::Disconnected(reason)) => {
                        // Attempt reconnection
                    }
                }
            }
        }
    }
}
```

**Impact:**
- Recording will fail silently if PipeWire restarts
- No recovery from Bluetooth device disconnect
- Users lose recordings with no warning
- System sleep/wake will break recording

**Recommendation:** Implement full watchdog system with reconnection logic as specified in guide sections on Error Handling (lines 902-1097).

---

#### 🟠 MAJOR: Missing Pause/Resume Functionality
**Severity:** Major
**Location:** `session.rs:50-52`

```rust
enum AudioCommand {
    Stop,
}
```

The guide specifies (line 161-164) `Pause` and `Resume` commands.

**Impact:**
- Users cannot pause recording during breaks
- Wastes disk space and transcription costs
- Guide's API contract not fulfilled

**Recommendation:** Add `Pause` and `Resume` to `AudioCommand` enum and implement state tracking in the audio thread.

---

#### 🟠 MAJOR: System Audio Capture Uses Wrong Target
**Severity:** Major
**Location:** `session.rs:285-295`

```rust
let props = pw::properties::properties! {
    *pw::keys::STREAM_CAPTURE_SINK => "true",
};
```

**Current Behavior:** Attempts to capture from "default sink monitor" implicitly

**Issue:** This doesn't match the guide's specification for explicit monitor port targeting (lines 512-514):

```rust
let monitor_port = sink_node.get_monitor_port()?;
let system_stream = core.create_stream(StreamConfig {
    target: monitor_port,
    ...
});
```

**Impact:**
- May capture wrong audio if user has multiple outputs
- Cannot reliably record system audio
- Doesn't handle device switching during recording

**Recommendation:** Explicitly enumerate and target the monitor port of the selected sink device.

---

#### 🟡 MINOR: No Timestamp Metadata Generation
**Severity:** Minor
**Location:** `session.rs`

The guide specifies (lines 746-772) generating `metadata.json` with precise timestamps for synchronization.

**Current Implementation:** No metadata file generation

**Impact:**
- Cannot determine exact start time of each track
- Cannot align mic and system audio if they start at slightly different times
- Missing feature for future analysis tools

**Recommendation:** Track start timestamps and write metadata.json on session completion.

---

### 2.4 Audio Encoding ✅ GOOD

**Location:** `granola_audio/src/capture/encoder.rs`

**Strengths:**
- Clean use of `hound` crate for WAV encoding
- Proper f32 to i16 conversion with clamping
- Thread-safe via Arc<Mutex<>>
- Finalize method properly closes WAV files

**Issues Found:**

#### 🟡 MINOR: Sample Format Mismatch with PipeWire
**Severity:** Minor
**Location:** `encoder.rs:14-20`, `session.rs:220`

```rust
// encoder.rs
bits_per_sample: 16,
sample_format: hound::SampleFormat::Int,

// session.rs
audio_info.set_format(pw::spa::param::audio::AudioFormat::F32LE);
```

**Issue:** PipeWire delivers F32LE samples, encoder converts to 16-bit PCM. This is fine for storage, but the guide mentions FLAC as an option for better quality.

**Recommendation:** Consider adding FLAC encoding option to preserve full 32-bit float dynamic range.

---

### 2.5 Threading Model ✅ EXCELLENT

**Overall Assessment:** The threading implementation closely matches the guide's specification.

**Strengths:**
- Dedicated audio thread spawned in `start_recording_impl()` (line 84)
- GIL properly released in blocking operations (lines 69-72)
- Channel-based communication (line 80)
- Timer-based command polling (lines 298-311)

**Gap:** Missing the event channel for Python <- Rust communication (audio levels, errors, etc.)

---

## 3. Python Application Layer

### 3.1 Main Application ✅ GOOD

**Location:** `granola/main.py`

**Strengths:**
- Simple, clean entry point
- Test mode for automated testing
- Proper QApplication lifecycle management

**Issues Found:**

#### 🟡 MINOR: No Command-Line Arguments
**Severity:** Minor
**Location:** `main.py:10-12`

The guide mentions settings for output directory, but CLI doesn't support `--output-dir` or similar.

**Recommendation:** Add argparse arguments for common settings (output dir, device selection, etc.) for power users and automation.

---

### 3.2 Configuration Management ✅ EXCELLENT

**Location:** `granola/config.py`

**Strengths:**
- Proper use of system keyring for API key storage
- Separation of sensitive data from JSON config
- Clean singleton pattern with global `config` instance
- Good defaults

**No issues found.** This is well-implemented and follows security best practices.

---

### 3.3 Main Window GUI ⚠️ NEEDS IMPROVEMENT

**Location:** `granola/ui/main_window.py`

**Strengths:**
- Clean PyQt6 implementation
- Good separation of Record and History tabs
- System tray integration
- Minimize to tray functionality
- Real-time recording timer
- Transcription worker thread (non-blocking UI)
- Database integration for persistence

**Issues Found:**

#### 🟠 MAJOR: No Audio Level Meters (VU Meters)
**Severity:** Major
**Location:** `main_window.py`

The guide shows VU meters in the UI mockup (lines 444-445):
```
│  Mic: Sony WH-1000XM4          [====|====]              │
│  System Audio: Active          [==|======]              │
```

**Current Implementation:** Status text only, no visual meters

**Impact:**
- Users cannot verify audio is being captured
- Cannot detect silent recordings until after stopping
- Poor UX during recording

**Recommendation:** Add QProgressBar widgets for mic/system levels, poll `session.get_levels()` every 100ms during recording.

---

#### 🟠 MAJOR: No Device Change Monitoring
**Severity:** Major
**Location:** `main_window.py:421-437`

The `refresh_devices()` method is only called at startup.

**Issue:** If user connects/disconnects Bluetooth headset during app runtime, device list becomes stale.

**Guide Specification:** Lines 334 shows `subscribe_device_changes()` callback API

**Impact:**
- Users must restart app to see new devices
- Cannot handle device hot-plug gracefully
- Confusing UX

**Recommendation:** Implement device change subscription and refresh UI when devices change.

---

#### 🟡 MINOR: No Bluetooth Profile Warning
**Severity:** Minor
**Location:** `main_window.py:472-476` (`start_recording()`)

The guide specifies (lines 602-621) warning users when Bluetooth device is in wrong profile (A2DP mode = no mic).

**Current Implementation:** No validation before recording starts

**Recommendation:** Add pre-recording validation using `validate_device_ready()` pattern from guide.

---

#### 🟡 MINOR: Timer Resolution Too Coarse for VU Meters
**Severity:** Minor
**Location:** `main_window.py:99-100, 538`

```python
self.timer = QTimer()
self.timer.start(100)  # 100ms
```

**Issue:** 100ms is fine for time display but may be too slow for smooth VU meters (guide suggests polling events every 100ms for general updates, but VU meters typically need 30-60 FPS for smooth animation).

**Recommendation:** Separate timer for VU meter updates (30-50ms) if implementing visual meters.

---

#### 🟡 MINOR: No Disk Space Pre-Check
**Severity:** Minor
**Location:** `main_window.py:443-464`

There's a `check_disk_space()` method that warns at 500MB threshold, but it only checks before recording starts.

**Gap:** No ongoing monitoring during long recordings

**Recommendation:** Periodically check disk space during recording and stop gracefully if running low.

---

### 3.4 Settings Dialog ✅ GOOD

**Location:** `granola/ui/settings_dialog.py`

**Strengths:**
- Clean, simple dialog
- API key properly masked
- Directory browser integration

**Issues Found:**

#### 🟡 MINOR: No Input Validation
**Severity:** Minor
**Location:** `settings_dialog.py:53-56`

```python
def save_settings(self):
    config.set("api_key", self.api_key_edit.text())
    config.set("output_dir", self.output_dir_edit.text())
```

**Missing Validation:**
- API key format (should be alphanumeric, specific length?)
- Output directory exists and is writable
- Output directory has sufficient space

**Recommendation:** Add validation before accepting settings. Show error dialog if invalid.

---

### 3.5 Database Schema ⚠️ PARTIAL

**Location:** `granola/storage/database.py`

**Strengths:**
- Clean SQLite implementation
- Proper use of context managers
- Schema matches guide (lines 1124-1176) reasonably well

**Issues Found:**

#### 🟠 MAJOR: Missing Schema Fields
**Severity:** Major
**Location:** `database.py:20-50`

**Guide Specifies (lines 1127-1138):**
```sql
CREATE TABLE recordings (
    id TEXT PRIMARY KEY,
    title TEXT,
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    duration_seconds INTEGER,
    mic_device_id TEXT,
    mic_device_name TEXT,
    directory_path TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Current Implementation Missing:**
- `ended_at` timestamp
- `mic_device_id` (stores path but not device ID)
- `mic_device_name` (useful for display)
- `directory_path` (stores individual file paths instead)
- `created_at` timestamp

**Impact:**
- Cannot query recordings by device
- Cannot distinguish recording time from creation time
- Less flexible for future features (device-specific history, etc.)

**Recommendation:** Add missing fields to match guide schema. Migration script needed for existing DBs.

---

#### 🟡 MINOR: No Foreign Key Enforcement
**Severity:** Minor
**Location:** `database.py:18`

```python
conn.execute(...)  # No PRAGMA foreign_keys = ON
```

**Issue:** SQLite doesn't enforce foreign keys by default

**Recommendation:** Add `conn.execute("PRAGMA foreign_keys = ON")` in `_init_db()`.

---

#### 🟡 MINOR: Missing Indexes
**Severity:** Minor
**Location:** `database.py`

**Issue:** No indexes on commonly queried fields:
- `recordings.started_at` (used in ORDER BY)
- `transcripts.recording_id` (foreign key)
- `action_items.recording_id` (foreign key)

**Impact:** Slow queries as database grows (100+ recordings)

**Recommendation:** Add indexes on these fields.

---

### 3.6 Transcription Integration ✅ GOOD

**Location:** `granola/transcription/gemini.py`

**Strengths:**
- Clean Gemini API integration
- Proper file upload handling
- JSON response format specified
- Good error handling (raises exceptions for missing API key, upload failures)

**Issues Found:**

#### 🟡 MINOR: Hardcoded Model Name
**Severity:** Minor
**Location:** `gemini.py:41`

```python
model="gemini-2.0-flash",
```

**Issue:** Model is hardcoded, should be configurable

**Guide Specifies (lines 1194-1196):**
```toml
[transcription]
provider = "gemini"
model = "gemini-1.5-pro"
```

**Recommendation:** Make model configurable via config.py, default to `gemini-2.0-flash`.

---

#### 🟡 MINOR: No File Upload Cleanup
**Severity:** Minor
**Location:** `gemini.py:18`

```python
audio_file = self.client.files.upload(file=audio_path)
```

**Issue:** Uploaded files remain in Gemini's storage indefinitely

**Recommendation:** Delete uploaded file after transcription completes to avoid accumulating storage charges. Use `client.files.delete(audio_file.name)`.

---

### 3.7 Audio Processing ✅ EXCELLENT

**Location:** `granola/transcription/processor.py`

**Strengths:**
- Correct implementation of stereo mixing (guide lines 774-801)
- Proper channel extraction for mono sources
- Handles sample rate/width validation
- Padding for length differences
- Clean, understandable code

**No significant issues found.** This is well-implemented per the guide.

---

## 4. Missing Components

### 4.1 Phase 1 Gaps

These were specified in the guide but not implemented:

#### 🔴 CRITICAL: `get_default_microphone()` API Missing
**Location:** Guide line 330
**Impact:** Users must manually select microphone every time
**Recommendation:** Implement in `device/enumerate.rs`

#### 🔴 CRITICAL: Device Monitoring/Callbacks Missing
**Location:** Guide lines 334
**Function:** `subscribe_device_changes(callback: Fn(DeviceEvent)) -> Subscription`
**Impact:** Cannot handle hot-plug events
**Recommendation:** Implement using PipeWire registry listener

#### 🟠 MAJOR: Audio Level Monitoring Missing
**Location:** Guide lines 343-378
**Function:** `get_levels(&self) -> AudioLevels`
**Impact:** No VU meters possible
**Recommendation:** Calculate RMS/peak in stream process callback

---

### 4.2 Phase 2 Gaps

#### 🟠 MAJOR: No Recording Title Editing
**Location:** Guide UI mockup shows recording titles
**Current:** Auto-generated "Recording 20241126_143022"
**Impact:** Poor UX, can't distinguish recordings
**Recommendation:** Add title input field or edit capability in history view

#### 🟡 MINOR: No Keyboard Shortcuts
**Location:** Guide Phase 4 mentions keyboard shortcuts
**Impact:** Power users can't quickly start/stop recording
**Recommendation:** Add common shortcuts (Ctrl+R for record, Ctrl+S for stop, etc.)

---

### 4.3 Not Yet Implemented (Phase 3+)

These are expected to be missing (future work):

- Summary generation (Phase 4 - lines 1277)
- Export functionality (Phase 4 - lines 1279)
- Auto-start with system (Phase 4 - lines 1282)

---

## 5. Code Quality Assessment

### 5.1 Rust Code Quality ✅ GOOD

**Strengths:**
- Idiomatic Rust patterns
- Good use of `Result<T, E>` for error handling
- Proper lifetimes and ownership
- Clean module organization
- Feature flags well-used

**Areas for Improvement:**
- Error types could be more specific (currently using `String` for errors)
- Some `unwrap()` calls that should be handled (e.g., `session.rs:234`)
- Missing documentation comments on public APIs

**Recommendation:**
- Define custom error types using `thiserror`
- Add `#![warn(missing_docs)]` and document public APIs
- Replace `.unwrap()` with proper error propagation

---

### 5.2 Python Code Quality ✅ GOOD

**Strengths:**
- Clean, readable code
- Good separation of concerns
- Type hints would improve IDE support
- Exception handling is adequate

**Areas for Improvement:**
- No type hints (PEP 484)
- Some long methods (e.g., `main_window.py:start_recording()` is 70 lines)
- Hardcoded strings could be constants

**Recommendation:**
- Add type hints for better IDE support and documentation
- Extract complex UI setup into separate methods
- Define constants for magic numbers (timer intervals, thresholds, etc.)

---

## 6. Testing

### 6.1 Automated Tests ❌ MISSING

**Status:** Test directories exist (`tests/rust/`, `tests/python/`) but are empty

**Guide Mentions:**
- Line 1320: `cargo test` (Rust tests)
- Line 1322: `pytest tests/python/` (Python tests)

**Impact:**
- No regression testing
- Difficult to verify PipeWire integration without manual testing
- Risky refactoring

**Recommendation:**
Priority test areas:
1. Rust: Device enumeration mocking
2. Rust: Audio encoder (WAV file validation)
3. Python: Database operations
4. Python: Stereo mixing logic
5. Integration: End-to-end recording test with mock audio

---

### 6.2 Test Scripts ✅ PRESENT

**Found:**
- `test_audio.py`
- `test_config.py`
- `test_mixing.py`
- `test_recording.py`

**Status:** These appear to be manual test scripts, not automated tests

**Recommendation:** Move these into `tests/python/` as proper pytest tests

---

## 7. Documentation

### 7.1 Implementation Guide ✅ EXCELLENT

**File:** `IMPLEMENTATION_GUIDE.md`

This is comprehensive and well-structured. It clearly guided the implementation.

---

### 7.2 Code Comments ⚠️ SPARSE

**Rust:** Minimal inline comments, no doc comments
**Python:** Minimal inline comments, some docstrings

**Recommendation:** Add documentation comments for all public APIs, especially PyO3-exported items.

---

### 7.3 README ❓ NOT REVIEWED

**Note:** README.md exists but wasn't reviewed in this pass

**Recommendation:** Ensure README covers:
- Installation instructions (dependencies, build process)
- Quick start guide
- Configuration (API key setup)
- Troubleshooting (PipeWire issues, Bluetooth headset setup)

---

## 8. Dependency Management

### 8.1 Rust Dependencies ✅ GOOD

**Location:** `granola_audio/Cargo.toml`

**Dependencies:**
- `pyo3 = "0.23"` - Latest stable ✅
- `pipewire = "0.8"` - Current stable ✅
- `hound = "3.5"` - Mature, stable ✅
- `thiserror = "1.0"` - Good choice ✅
- `tokio` - **⚠️ Included but not used**

**Issue:** Tokio is listed as a dependency but not imported anywhere

**Recommendation:** Remove tokio dependency if unused, or document why it's needed.

---

### 8.2 Python Dependencies ✅ GOOD

**Location:** `pyproject.toml`

**Dependencies:**
- `PyQt6>=6.6.0` ✅
- `google-genai>=0.3.0` ✅
- `keyring>=24.0.0` ✅

**Note:** Missing `scipy` or `numpy` which are mentioned in guide's mixing example (lines 780-781). Current implementation uses `wave` module instead, which is fine.

---

## 9. Build System

### 9.1 Maturin Configuration ✅ GOOD

**Location:** `pyproject.toml`

```toml
[tool.maturin]
features = ["pyo3/extension-module", "real-audio"]
module-name = "granola_audio"
manifest-path = "granola_audio/Cargo.toml"
```

**Correct use of:**
- Features to enable real PipeWire integration
- Proper module naming
- Manifest path pointing to Rust crate

---

## 10. Security Review

### 10.1 API Key Storage ✅ EXCELLENT

**Location:** `granola/config.py`

Uses system keyring for secure API key storage. Properly prevents accidental leakage to JSON config.

**No issues found.**

---

### 10.2 Input Validation ⚠️ NEEDS IMPROVEMENT

**Issues:**
- No validation on recording directory path (could be `/root/`, etc.)
- No validation on mic device ID (could cause crashes if malformed)
- No sanitization of user-provided recording titles (if added)

**Recommendation:** Add input validation for all user-provided data.

---

## 11. Performance Considerations

### 11.1 Audio Thread ✅ GOOD

The dedicated audio thread with 100ms command polling is appropriate and won't cause latency issues.

---

### 11.2 Database Operations ⚠️ MINOR

Database operations are synchronous and happen on main thread.

**Potential Issue:** For large history lists (100+ recordings), loading history could block UI briefly.

**Recommendation:** Consider loading history asynchronously in a QThread for large databases.

---

### 11.3 Transcription Worker ✅ EXCELLENT

Properly uses QThread for long-running transcription, preventing UI freeze.

---

## 12. Platform Compatibility

### 12.1 Linux ✅ EXCELLENT

Well-designed for Linux with PipeWire. Should work on modern distributions (Fedora 34+, Ubuntu 22.04+).

---

### 12.2 PipeWire Version ⚠️ UNKNOWN

**Issue:** No minimum PipeWire version documented

**Recommendation:** Test with PipeWire 0.3.40+ (common baseline) and document minimum version.

---

## 13. User Experience

### 13.1 First-Run Experience ⚠️ NEEDS IMPROVEMENT

**Current Flow:**
1. User runs app
2. Must manually configure output directory
3. Must manually configure API key
4. Must manually select microphone

**Recommendation:** Add first-run wizard or better defaults (~/Music/Granola, auto-select default mic).

---

### 13.2 Error Messages ⚠️ INCONSISTENT

Some errors are user-friendly ("Please set your Gemini API Key"), others are technical ("Failed to connect to core: XYZ").

**Recommendation:** Standardize error messages - technical details in logs, user-friendly messages in dialogs.

---

## 14. Summary of Issues by Severity

### Critical Issues (4)

1. ❌ Missing event polling API for audio levels and errors
2. ❌ No audio level (VU meter) support
3. ❌ No error recovery/watchdog for PipeWire disconnects
4. ❌ Missing `get_default_microphone()` API

### Major Issues (8)

1. ⚠️ Default device detection not implemented
2. ⚠️ Hardcoded sample rate and channel count in device enumeration
3. ⚠️ Missing pause/resume functionality
4. ⚠️ System audio capture doesn't explicitly target monitor port
5. ⚠️ No audio level meters in GUI
6. ⚠️ No device hot-plug monitoring
7. ⚠️ Database schema missing fields from guide
8. ⚠️ No recording title editing

### Minor Issues (12)

1. 🟡 Bluetooth profile detection missing
2. 🟡 No timestamp metadata generation
3. 🟡 Sample format could be FLAC for better quality
4. 🟡 No command-line arguments
5. 🟡 No Bluetooth profile warning before recording
6. 🟡 Timer resolution may be too coarse for smooth VU meters
7. 🟡 No ongoing disk space monitoring during recording
8. 🟡 No input validation in settings dialog
9. 🟡 No foreign key enforcement in SQLite
10. 🟡 Missing database indexes
11. 🟡 Hardcoded Gemini model name
12. 🟡 No Gemini file upload cleanup

---

## 15. Recommendations Priority List

### P0 - Critical (Must Fix Before Release)

1. **Implement event polling system** - Required for robust error handling and UX
2. **Add audio level monitoring** - Essential user feedback during recording
3. **Implement PipeWire disconnect recovery** - Prevents data loss
4. **Add automated tests** - Critical for reliability

### P1 - High Priority (Should Fix Soon)

1. **Implement default device detection** - Major UX improvement
2. **Add device hot-plug monitoring** - Handles common user scenario
3. **Fix device enumeration to report real formats** - Accurate device info
4. **Add VU meters to GUI** - Major UX improvement
5. **Implement pause/resume** - Common user request
6. **Complete database schema** - Enables future features

### P2 - Medium Priority (Nice to Have)

1. **Add recording title editing** - UX improvement
2. **Implement Bluetooth profile validation** - Prevents user confusion
3. **Add keyboard shortcuts** - Power user feature
4. **Improve error messages** - UX polish
5. **Add input validation** - Robustness

### P3 - Low Priority (Future Enhancement)

1. **Add FLAC encoding option** - Quality improvement for audiophiles
2. **Generate metadata.json** - Enables future analysis tools
3. **Add CLI arguments** - Power user feature
4. **Optimize database queries** - Performance for heavy users
5. **Add first-run wizard** - Onboarding improvement

---

## 16. Phase Completion Status

### Phase 1: Foundation (Audio Capture) - 70% Complete ✅

**Completed:**
- ✅ Rust project setup with PipeWire
- ✅ Device enumeration (partial)
- ✅ Basic recording (mic + system)
- ✅ WAV encoding
- ✅ PyO3 bindings
- ✅ Python test scripts

**Missing:**
- ❌ Device monitoring callbacks
- ❌ Audio level monitoring
- ❌ Error recovery
- ❌ Default device detection

---

### Phase 2: Core Application - 75% Complete ✅

**Completed:**
- ✅ Python project with maturin
- ✅ Recording session management
- ✅ SQLite database (partial schema)
- ✅ Main window UI
- ✅ Recording controls
- ✅ Device selection UI
- ✅ Recording history view
- ✅ Settings dialog
- ✅ System tray integration

**Missing:**
- ❌ VU meters
- ❌ Device hot-plug handling
- ❌ Complete database schema
- ❌ Recording title editing
- ❌ Keyboard shortcuts

---

### Phase 3: Transcription - 90% Complete ✅

**Completed:**
- ✅ Gemini API client
- ✅ Audio preprocessing (stereo mixing)
- ✅ Transcript viewer UI
- ✅ Speaker labeling (via Gemini)

**Missing:**
- ❌ Transcript search (not yet needed)

---

### Phase 4: Analysis & Polish - 0% Complete ⏸️

**Not Started:**
- ❌ Summary generation (Gemini prompt exists, but not explicitly separated)
- ❌ Action item extraction (implemented via Gemini)
- ❌ Export functionality (markdown, PDF)
- ❌ Auto-start with system
- ❌ Performance optimization
- ❌ Distribution packages

**Note:** Some Phase 4 items (action items) are partially implemented as part of transcription.

---

## 17. Conclusion

### Overall Assessment: **GOOD PROGRESS** ⭐⭐⭐⭐☆

The Granola Linux implementation has achieved ~75% of the planned Phase 1 and Phase 2 functionality. The core architecture is sound and follows the implementation guide closely. The codebase is well-organized and demonstrates good engineering practices.

### Key Strengths

1. **Solid architecture** - Clean separation between Rust and Python layers
2. **PyO3 integration** - Well-executed native module
3. **Good UX foundation** - GUI is functional and intuitive
4. **Proper security** - API keys stored securely in system keyring
5. **Transcription works** - Core value proposition is functional

### Critical Gaps

The main gaps are in **robustness and user feedback**:
- Lack of error recovery makes the app fragile to common scenarios (PipeWire restart, device disconnect)
- Missing audio level monitoring means users have no feedback during recording
- Device enumeration is incomplete (default device, hot-plug, accurate formats)

### Next Steps

To reach production quality, focus on:
1. **P0 items** (event system, audio levels, error recovery, tests)
2. **User testing** with real Bluetooth headsets and various PipeWire configurations
3. **Edge case handling** (low disk space, bad network, API quota limits)
4. **Documentation** (README, installation guide, troubleshooting)

### Final Recommendation

**The implementation is in good shape for continued development.** Address the P0 critical issues before any public release. The architecture is sound enough that adding missing features will be straightforward.

---

**End of Review**

---

## Appendix A: Testing Checklist

### Manual Testing Scenarios

Before release, test these scenarios:

- [ ] Record with wired headset
- [ ] Record with Bluetooth headset (HFP mode)
- [ ] Record with Bluetooth headset (A2DP mode) - should warn or fail gracefully
- [ ] Record with system audio only (no mic)
- [ ] Record with mic only (no system audio)
- [ ] Hot-plug USB microphone during recording
- [ ] Disconnect Bluetooth headset during recording
- [ ] System sleep/wake during recording
- [ ] PipeWire restart during recording (systemctl restart pipewire)
- [ ] Low disk space scenario
- [ ] Very long recording (1+ hour)
- [ ] Quick successive recordings (start/stop/start)
- [ ] Transcribe mono recording (mic only)
- [ ] Transcribe stereo recording (mic + system)
- [ ] Export workflow (when implemented)
- [ ] Settings persistence across app restarts
- [ ] System tray minimize/restore
- [ ] Multiple recordings in history
- [ ] API key validation (invalid key, network error)

---

## Appendix B: Code Metrics

**Rust:**
- Files: 6
- Total Lines: ~500 (excluding generated code)
- Complexity: Low-Medium

**Python:**
- Files: 9
- Total Lines: ~1000
- Complexity: Medium

**Test Coverage:** 0% (no tests implemented yet)

---

## Appendix C: Future Feature Ideas

Ideas not in the current guide but worth considering:

1. **Hotkey recording** - Global hotkey to start/stop (would require X11/Wayland integration)
2. **Recording templates** - Save device/settings presets ("Daily Standup", "Interview", etc.)
3. **Cloud backup** - Optional backup of recordings to cloud storage
4. **Real-time transcription** - Live captions during meeting (challenging latency requirements)
5. **Speaker identification** - Learn voices and auto-label known participants
6. **Noise reduction** - Pre-process audio before transcription for better accuracy
7. **Meeting calendar integration** - Auto-name recordings from calendar events
8. **Teams/Slack integration** - Post summaries directly to chat
9. **Searchable transcript archive** - Full-text search across all recordings
10. **Waveform visualization** - Visual representation of audio during playback

---

**Review Complete - Generated by Claude Code on 2025-11-26**
