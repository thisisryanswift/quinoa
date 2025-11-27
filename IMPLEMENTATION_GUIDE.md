# Granola Linux - Implementation Guide

A meeting recording and transcription app for Linux, built with Rust (audio capture) and Python (application logic, GUI, transcription).

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Threading Model](#threading-model)
4. [Project Structure](#project-structure)
5. [Component Details](#component-details)
6. [PipeWire Integration](#pipewire-integration)
7. [Bluetooth Audio Handling](#bluetooth-audio-handling)
8. [Non-Invasive Recording](#non-invasive-recording)
9. [Audio Synchronization](#audio-synchronization)
10. [Data Flow](#data-flow)
11. [Error Handling & Recovery](#error-handling--recovery)
12. [Storage Schema](#storage-schema)
13. [Implementation Phases](#implementation-phases)
14. [Known Limitations & Future Work](#known-limitations--future-work)

---

## Overview

### Goals

- Record system audio (meeting participants) and microphone (local user) simultaneously
- Operate non-invasively alongside video conferencing apps (Google Meet, Zoom, etc.)
- Support Bluetooth headsets as primary audio devices
- Transcribe recordings using Gemini Cloud API (post-recording)
- Generate meeting summaries and action items
- Provide a full desktop GUI for managing recordings

### Technology Choices

| Component | Technology | Rationale |
|-----------|------------|-----------|
| Audio Capture | Rust + PipeWire | Direct PipeWire integration, low-level control, safety |
| Python Bindings | PyO3 + maturin | Native Python module, clean API, single package |
| Application Logic | Python | Rapid development, rich ecosystem, developer familiarity |
| GUI Framework | PyQt6 / PySide6 | Mature, full-featured, cross-desktop compatibility |
| Transcription | Gemini Cloud API | Cloud-based, high accuracy, speaker diarization |
| Local Storage | SQLite + filesystem | Simple, portable, no external dependencies |

---

## Architecture

### High-Level Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      Python Application                          │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │     GUI      │  │ Transcription│  │  Meeting Analysis    │  │
│  │   (PyQt6)    │  │   (Gemini)   │  │  (Summaries, etc.)   │  │
│  └──────┬───────┘  └──────────────┘  └──────────────────────┘  │
│         │                                                        │
│         ▼                                                        │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              Recording Manager (Python)                  │    │
│  │         Orchestrates sessions, handles storage          │    │
│  └──────────────────────────┬──────────────────────────────┘    │
│                             │                                    │
│                             ▼                                    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │            granola_audio (Rust + PyO3)                  │    │
│  │         PipeWire capture, device management             │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                ┌───────────────────────┐
                │       PipeWire        │
                │  (System Audio Daemon)│
                └───────────────────────┘
```

### Rust-Python Integration (PyO3)

The Rust audio library is exposed to Python as a native module via PyO3:

```python
# From Python, usage looks like:
import granola_audio

# List available devices
devices = granola_audio.list_devices()

# Start recording
session = granola_audio.start_recording(
    mic_device="bluez_input.XX_XX_XX_XX_XX_XX",
    output_dir="/home/user/Granola/recordings/2024-01-15_standup"
)

# Stop recording
session.stop()
```

This approach provides:
- Native performance for audio capture
- Clean, Pythonic API
- Single package distribution (maturin builds both)
- No IPC complexity

---

## Threading Model

### The Challenge

PipeWire requires its own event loop to process audio buffers and handle events. Running this alongside Python's Global Interpreter Lock (GIL) and PyQt's event loop requires careful design to avoid blocking the UI.

### Solution: Dedicated Audio Thread

The Rust `RecordingSession` spawns a dedicated background thread for PipeWire operations:

```
┌─────────────────────────────────────────────────────────────────┐
│                    Python Main Thread                            │
│                    (PyQt Event Loop)                             │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  UI Updates, User Input, Business Logic                  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              │  Calls via PyO3                   │
│                              │  (GIL released)                   │
│                              ▼                                   │
└─────────────────────────────────────────────────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
          ▼                    │                    ▼
┌──────────────────┐           │          ┌──────────────────┐
│  Event Channel   │◄──────────┴─────────►│ Command Channel  │
│  (Rust → Python) │                      │ (Python → Rust)  │
└────────┬─────────┘                      └────────┬─────────┘
         │                                         │
         │         ┌─────────────────────┐         │
         └────────►│  Rust Audio Thread  │◄────────┘
                   │  (PipeWire Loop)    │
                   │                     │
                   │  - Buffer capture   │
                   │  - WAV encoding     │
                   │  - Level metering   │
                   └─────────────────────┘
```

### Implementation Pattern

```rust
use std::sync::mpsc::{channel, Sender, Receiver};
use std::thread;
use pyo3::prelude::*;

// Commands from Python to Rust audio thread
enum AudioCommand {
    Pause,
    Resume,
    Stop,
    GetLevels,
}

// Events from Rust audio thread to Python
enum AudioEvent {
    Started,
    Stopped { result: RecordingResult },
    Error { message: String },
    Levels { mic: f32, system: f32 },
    DeviceLost { device_id: String },
    PipeWireDisconnected,
}

#[pyclass]
struct RecordingSession {
    command_tx: Sender<AudioCommand>,
    event_rx: Receiver<AudioEvent>,
    thread_handle: Option<thread::JoinHandle<()>>,
}

#[pymethods]
impl RecordingSession {
    fn stop(&mut self) -> PyResult<RecordingResult> {
        // Release GIL while waiting for audio thread
        Python::with_gil(|py| {
            py.allow_threads(|| {
                self.command_tx.send(AudioCommand::Stop).ok();
                // Wait for thread to finish
                if let Some(handle) = self.thread_handle.take() {
                    handle.join().ok();
                }
            })
        });
        // Return result from event channel
        // ...
    }

    fn poll_events(&self) -> PyResult<Vec<AudioEvent>> {
        // Non-blocking poll for UI updates
        let mut events = Vec::new();
        while let Ok(event) = self.event_rx.try_recv() {
            events.push(event);
        }
        Ok(events)
    }
}
```

### Key Principles

1. **Never block the main thread**: All PipeWire operations happen in the background thread
2. **Release GIL during waits**: Use `Python::allow_threads()` when waiting for audio operations
3. **Non-blocking event polling**: UI polls for events without blocking
4. **Thread-safe channels**: Use `std::sync::mpsc` or `crossbeam` for communication
5. **Graceful shutdown**: Audio thread handles cleanup before terminating

### PyQt Integration

```python
# In the Qt application
from PyQt6.QtCore import QTimer

class RecordingWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.session = None

        # Poll for audio events every 100ms
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self._poll_audio_events)
        self.poll_timer.start(100)

    def _poll_audio_events(self):
        if self.session is None:
            return

        for event in self.session.poll_events():
            match event:
                case AudioEvent.Levels(mic, system):
                    self.update_vu_meters(mic, system)
                case AudioEvent.DeviceLost(device_id):
                    self.show_device_lost_warning(device_id)
                case AudioEvent.PipeWireDisconnected():
                    self.handle_pipewire_disconnect()
```

---

## Project Structure

```
granola-linux/
│
├── Cargo.toml                    # Workspace root
├── pyproject.toml                # Python project config (maturin)
├── README.md
├── IMPLEMENTATION_GUIDE.md       # This file
│
├── granola_audio/                # Rust crate
│   ├── Cargo.toml
│   └── src/
│       ├── lib.rs                # PyO3 module definition & bindings
│       ├── pipewire/
│       │   ├── mod.rs
│       │   ├── connection.rs     # PipeWire daemon connection
│       │   ├── node.rs           # Audio node representation
│       │   └── stream.rs         # Capture stream management
│       ├── capture/
│       │   ├── mod.rs
│       │   ├── session.rs        # Recording session state
│       │   ├── encoder.rs        # WAV/FLAC encoding
│       │   └── monitor.rs        # Monitor tap implementation
│       └── device/
│           ├── mod.rs
│           ├── enumerate.rs      # Device discovery
│           └── bluetooth.rs      # Bluetooth-specific handling
│
├── granola/                      # Python package
│   ├── __init__.py
│   ├── app.py                    # Application entry point
│   ├── recording/
│   │   ├── __init__.py
│   │   ├── session.py            # Recording session management
│   │   └── manager.py            # Session lifecycle, storage
│   ├── transcription/
│   │   ├── __init__.py
│   │   ├── gemini.py             # Gemini API client
│   │   └── processor.py          # Audio preprocessing for API
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── summary.py            # Meeting summary generation
│   │   └── actions.py            # Action item extraction
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── database.py           # SQLite operations
│   │   └── files.py              # File management utilities
│   └── ui/
│       ├── __init__.py
│       ├── main_window.py        # Main application window
│       ├── recording_view.py     # Recording controls & status
│       ├── history_view.py       # Past recordings list
│       ├── transcript_view.py    # Transcript display
│       ├── settings_dialog.py    # App settings
│       └── resources/            # Icons, stylesheets
│
├── tests/
│   ├── rust/                     # Rust unit tests
│   └── python/                   # Python tests
│
└── scripts/
    ├── build.sh                  # Build script
    └── dev-setup.sh              # Development environment setup
```

---

## Component Details

### granola_audio (Rust)

#### Public API (exposed via PyO3)

```rust
// Device Management
fn list_devices() -> Vec<Device>
fn get_device(id: &str) -> Option<Device>
fn get_default_microphone() -> Option<Device>
fn get_default_speaker() -> Option<Device>

// Device Monitoring
fn subscribe_device_changes(callback: Fn(DeviceEvent)) -> Subscription

// Recording Control
fn start_recording(config: RecordingConfig) -> RecordingSession
impl RecordingSession {
    fn stop(&mut self) -> RecordingResult
    fn pause(&mut self)
    fn resume(&mut self)
    fn get_status(&self) -> SessionStatus
    fn get_levels(&self) -> AudioLevels  // For VU meters
}

// Types
struct Device {
    id: String,
    name: String,
    device_type: DeviceType,      // Microphone, Speaker, Monitor
    is_bluetooth: bool,
    bluetooth_profile: Option<BluetoothProfile>,  // A2DP, HFP, HSP
    sample_rate: u32,
    channels: u8,
    is_default: bool,
}

struct RecordingConfig {
    mic_device_id: Option<String>,      // None = default
    system_audio: bool,                  // Capture system audio?
    output_dir: PathBuf,
    format: AudioFormat,                 // WAV, FLAC
    sample_rate: u32,                    // 44100, 48000
}

enum DeviceEvent {
    Added(Device),
    Removed(String),          // device_id
    Changed(Device),          // e.g., Bluetooth profile switch
    DefaultChanged(DeviceType, String),
}

struct AudioLevels {
    mic_peak: f32,            // 0.0 - 1.0
    mic_rms: f32,
    system_peak: f32,
    system_rms: f32,
}
```

### granola (Python)

#### Recording Session Management

```python
# granola/recording/session.py

@dataclass
class RecordingSession:
    id: str
    started_at: datetime
    mic_device: str
    output_dir: Path
    status: SessionStatus

class RecordingManager:
    def start_session(self, title: Optional[str] = None) -> RecordingSession:
        """Start a new recording session."""

    def stop_session(self, session_id: str) -> CompletedRecording:
        """Stop recording and finalize files."""

    def get_active_session(self) -> Optional[RecordingSession]:
        """Get currently active recording, if any."""
```

#### Transcription Pipeline

```python
# granola/transcription/gemini.py

class GeminiTranscriber:
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)

    async def transcribe(
        self,
        audio_files: list[Path],
        prompt_context: Optional[str] = None
    ) -> Transcript:
        """
        Send audio to Gemini for transcription.

        Args:
            audio_files: Paths to audio files (mic + system audio)
            prompt_context: Optional context (e.g., "This is a standup meeting")

        Returns:
            Transcript with speaker-attributed segments
        """
```

#### GUI Components

```python
# Main window structure

┌─────────────────────────────────────────────────────────────────┐
│  Granola                                              [—][□][×] │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  ● Recording: Team Standup                    00:15:32  │   │
│  │                                                          │   │
│  │  Mic: Sony WH-1000XM4          [====|====]              │   │
│  │  System Audio: Active          [==|======]              │   │
│  │                                                          │   │
│  │              [ ⏸ Pause ]    [ ⏹ Stop ]                  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Recent Recordings                                       │   │
│  │  ─────────────────────────────────────────────────────  │   │
│  │  📝 Product Sync          Today, 2:00 PM      45:12     │   │
│  │  📝 1:1 with Manager      Today, 10:00 AM     28:45     │   │
│  │  📄 Team Standup          Yesterday           15:02     │   │
│  │  📄 Sprint Planning       Jan 13              1:02:33   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  [⚙ Settings]                              [+ New Recording]   │
└─────────────────────────────────────────────────────────────────┘

Legend: 📝 = Has transcript   📄 = Audio only (not yet transcribed)
```

---

## PipeWire Integration

### Core Concepts

**PipeWire Graph**: PipeWire models audio as a graph of nodes connected by links.

```
┌──────────────┐         ┌──────────────┐
│  Source Node │────────▶│  Sink Node   │
│ (Microphone) │         │ (Speakers)   │
└──────────────┘         └──────────────┘
       │                        │
       │                        │
       ▼                        ▼
┌──────────────┐         ┌──────────────┐
│  App (Meet)  │         │   Monitor    │
└──────────────┘         │    Port      │
       │                 └──────────────┘
       │                        │
       ▼                        ▼
┌──────────────┐         ┌──────────────┐
│   Granola    │         │   Granola    │
│  (Mic Tap)   │         │(System Tap)  │
└──────────────┘         └──────────────┘
```

**Key PipeWire concepts we use:**

1. **Sources**: Audio inputs (microphones)
2. **Sinks**: Audio outputs (speakers, headphones)
3. **Monitor Ports**: Every sink has a monitor that lets you capture its output
4. **Streams**: Our connection to the PipeWire graph

### Connection Flow

```rust
// Pseudocode for PipeWire setup

// 1. Connect to PipeWire daemon
let core = pipewire::Core::connect()?;

// 2. Get registry to enumerate devices
let registry = core.get_registry()?;

// 3. Find target nodes
let mic_node = registry.find_node(|n| n.id == selected_mic_id)?;
let sink_node = registry.find_default_sink()?;
let monitor_port = sink_node.get_monitor_port()?;

// 4. Create capture streams
let mic_stream = core.create_stream(StreamConfig {
    target: mic_node,
    direction: Direction::Input,
    ..
})?;

let system_stream = core.create_stream(StreamConfig {
    target: monitor_port,
    direction: Direction::Input,  // Monitor ports are "inputs" to us
    ..
})?;

// 5. Start capture loop
loop {
    let mic_buffer = mic_stream.dequeue_buffer()?;
    let system_buffer = system_stream.dequeue_buffer()?;

    encoder.write_mic(mic_buffer);
    encoder.write_system(system_buffer);
}
```

### Rust Dependencies

```toml
# granola_audio/Cargo.toml

[dependencies]
pipewire = "0.8"              # PipeWire Rust bindings
pyo3 = { version = "0.21", features = ["extension-module"] }
hound = "3.5"                 # WAV encoding
flac-bound = "0.3"            # FLAC encoding (optional)
thiserror = "1.0"             # Error handling
tokio = { version = "1", features = ["rt", "sync"] }  # Async runtime
```

---

## Bluetooth Audio Handling

### Profile Awareness

Bluetooth headsets operate in different profiles:

| Profile | Quality | Mic | Use Case |
|---------|---------|-----|----------|
| A2DP | High (stereo, 44.1-48kHz) | ❌ | Music playback |
| HFP | Low (mono, 8-16kHz) | ✅ | Calls |
| HSP | Low (mono, 8kHz) | ✅ | Legacy calls |

**During a meeting**: The headset will be in HFP mode (to enable the microphone), which means:
- Microphone audio: ~16kHz mono (adequate for speech/transcription)
- System audio capture: Unaffected (captured before Bluetooth encoding)

### Implementation Considerations

```rust
// Device structure includes Bluetooth info
struct Device {
    // ...
    is_bluetooth: bool,
    bluetooth_profile: Option<BluetoothProfile>,
}

enum BluetoothProfile {
    A2DP,
    HFP,
    HSP,
}

// Check if mic is available (not in A2DP mode)
fn can_record_mic(device: &Device) -> bool {
    if !device.is_bluetooth {
        return true;
    }
    matches!(
        device.bluetooth_profile,
        Some(BluetoothProfile::HFP) | Some(BluetoothProfile::HSP)
    )
}
```

### UI Handling

```python
# Pre-recording validation
def validate_device_ready(device: Device) -> list[Warning]:
    warnings = []

    if device.is_bluetooth:
        if device.bluetooth_profile == BluetoothProfile.A2DP:
            warnings.append(Warning(
                level="error",
                message="Bluetooth headset is in music mode (A2DP). "
                        "Microphone not available. Start a call or "
                        "manually switch to headset mode."
            ))
        elif device.bluetooth_profile in (BluetoothProfile.HFP, BluetoothProfile.HSP):
            warnings.append(Warning(
                level="info",
                message="Bluetooth headset in call mode. "
                        "Audio quality is reduced but mic is available."
            ))

    return warnings
```

---

## Non-Invasive Recording

### Design Principle

Granola must **never interfere** with the meeting application (Google Meet, Zoom, etc.). We achieve this through:

1. **Monitor taps, not intercepts**: We observe audio streams, not redirect them
2. **No exclusive access**: We don't claim exclusive access to devices
3. **Low priority**: Our streams are low-priority in PipeWire's graph

### How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                        Audio Flow Diagram                        │
│                                                                  │
│   ┌─────────────┐                                               │
│   │ Microphone  │                                               │
│   │  (Headset)  │                                               │
│   └──────┬──────┘                                               │
│          │                                                       │
│          ▼                                                       │
│   ┌──────────────┐     PipeWire automatically                   │
│   │   PipeWire   │     duplicates the stream                    │
│   │  Source Node │─────────────────────────┐                    │
│   └──────┬───────┘                         │                    │
│          │                                 │                    │
│          ▼                                 ▼                    │
│   ┌─────────────┐                  ┌──────────────┐            │
│   │ Google Meet │                  │   Granola    │            │
│   │  (Browser)  │                  │ (Observer)   │            │
│   └──────┬──────┘                  └──────────────┘            │
│          │                                                       │
│          ▼                                                       │
│   ┌──────────────┐                                              │
│   │   PipeWire   │                                              │
│   │  Sink Node   │──────────┐                                   │
│   └──────┬───────┘          │                                   │
│          │                  │ Monitor Port                      │
│          ▼                  ▼                                   │
│   ┌─────────────┐   ┌──────────────┐                           │
│   │  Headphones │   │   Granola    │                           │
│   │  (Playback) │   │ (Observer)   │                           │
│   └─────────────┘   └──────────────┘                           │
│                                                                  │
│   Meeting unaffected ✓        Recording captured ✓              │
└─────────────────────────────────────────────────────────────────┘
```

### Stream Configuration

```rust
// Configure our streams as passive observers
let stream_config = StreamConfig {
    // Don't set exclusive mode
    flags: StreamFlags::MAP_BUFFERS | StreamFlags::AUTOCONNECT,

    // Low latency not required (we're recording, not live-streaming)
    latency: Latency::Default,

    // We're purely a consumer
    direction: Direction::Input,
};
```

### Edge Cases

| Scenario | Behavior |
|----------|----------|
| Meeting app starts after Granola | PipeWire handles routing; no conflict |
| Bluetooth device disconnects | Emit `DeviceEvent::Removed`, notify UI |
| User switches audio device in Meet | Our streams continue on original device (by design) |
| System goes to sleep | Pause recording, resume on wake |

---

## Audio Synchronization

### The Challenge

We record two separate audio streams (microphone and system audio) to separate files. For transcription, we need to either:
1. Merge them into a single file, or
2. Provide precise timestamps so transcripts can be aligned

### Recommended Approach: Stereo Mixing for Transcription

Create a mixed stereo file specifically for sending to Gemini:
- **Left channel**: Microphone (local user)
- **Right channel**: System audio (remote participants)

This approach:
- Provides spatial separation that helps diarization models distinguish speakers
- Keeps file management simple (one file to upload)
- Preserves the original separate files for archival/flexibility

### Implementation

```
Recording Phase:                   Transcription Phase:

microphone.wav ──┐                 ┌─► mixed_stereo.wav ──► Gemini API
                 │                 │   (L=mic, R=system)
                 ├─► Keep both    ─┤
                 │   originals     │
system_audio.wav─┘                 └─► Delete after transcription
                                       (derived file)
```

### File Output (Updated)

```
~/Granola/recordings/{session_id}/
├── microphone.wav           # Original mono mic recording
├── system_audio.wav         # Original mono system recording
├── mixed_stereo.wav         # Generated for transcription (L=mic, R=sys)
├── metadata.json            # Includes precise timestamps
├── transcript.json
└── summary.md
```

### Timestamp Precision

The `metadata.json` must capture precise timing:

```json
{
  "session_id": "2024-01-15_093000_abc123",
  "started_at": "2024-01-15T09:30:00.123456Z",
  "ended_at": "2024-01-15T10:15:32.789012Z",
  "tracks": {
    "microphone": {
      "file": "microphone.wav",
      "start_offset_ms": 0,
      "sample_rate": 48000,
      "channels": 1
    },
    "system_audio": {
      "file": "system_audio.wav",
      "start_offset_ms": 12,
      "sample_rate": 48000,
      "channels": 1
    }
  }
}
```

The `start_offset_ms` captures any timing difference between when the two streams started (usually negligible, but important for precise alignment).

### Mixing Implementation

```python
# granola/transcription/processor.py

import numpy as np
from scipy.io import wavfile

def create_stereo_mix(mic_path: Path, system_path: Path, output_path: Path):
    """
    Create a stereo WAV file with mic on left, system on right.
    """
    mic_rate, mic_data = wavfile.read(mic_path)
    sys_rate, sys_data = wavfile.read(system_path)

    # Resample if needed (should match, but be safe)
    assert mic_rate == sys_rate, "Sample rates must match"

    # Normalize lengths (pad shorter with silence)
    max_len = max(len(mic_data), len(sys_data))
    mic_data = np.pad(mic_data, (0, max_len - len(mic_data)))
    sys_data = np.pad(sys_data, (0, max_len - len(sys_data)))

    # Create stereo: left=mic, right=system
    stereo = np.column_stack((mic_data, sys_data))

    wavfile.write(output_path, mic_rate, stereo)
```

### Transcription Prompt Strategy

When sending to Gemini, include context about the audio structure:

```python
TRANSCRIPTION_PROMPT = """
Transcribe this meeting audio. The audio is stereo:
- Left channel: Local participant (the person who recorded this)
- Right channel: Remote participants (everyone else in the meeting)

Please:
1. Label the local participant as "{local_user_name}" (or "Local User" if not provided)
2. Identify and label distinct remote speakers as "Speaker 1", "Speaker 2", etc.
3. Include timestamps for each speaker segment
4. Note any unclear audio with [inaudible]
"""
```

This gives Gemini "ground truth" about the local user, improving diarization accuracy for remote speakers.

---

## Data Flow

### Recording Phase

```
User clicks "Start Recording"
           │
           ▼
┌─────────────────────────────────────┐
│  Python: RecordingManager           │
│  - Generate session ID              │
│  - Create output directory          │
│  - Initialize database record       │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Rust: granola_audio.start_recording│
│  - Connect to PipeWire              │
│  - Create mic stream                │
│  - Create system audio stream       │
│  - Start encoding to files          │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Output Files:                      │
│  ~/Granola/recordings/{session_id}/ │
│  ├── microphone.wav                 │
│  ├── system_audio.wav               │
│  └── metadata.json                  │
└─────────────────────────────────────┘
```

### Processing Phase

```
User clicks "Transcribe"
           │
           ▼
┌─────────────────────────────────────┐
│  Python: TranscriptionProcessor     │
│  - Load audio files                 │
│  - Preprocess if needed             │
│  - Upload to Gemini API             │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Gemini API                         │
│  - Speech-to-text                   │
│  - Speaker diarization              │
│  - Returns transcript JSON          │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Python: AnalysisEngine             │
│  - Generate summary                 │
│  - Extract action items             │
│  - Identify key topics              │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Storage:                           │
│  ~/Granola/recordings/{session_id}/ │
│  ├── microphone.wav                 │
│  ├── system_audio.wav               │
│  ├── metadata.json                  │
│  ├── transcript.json    ← NEW       │
│  └── summary.md         ← NEW       │
└─────────────────────────────────────┘
```

---

## Error Handling & Recovery

### PipeWire Connection Watchdog

PipeWire daemons can restart unexpectedly (e.g., on Bluetooth device connect/disconnect, system sleep/wake, or user-triggered restarts). The Rust layer must detect and report these events.

### Event Types

```rust
/// Events that can occur during recording
enum PipeWireEvent {
    /// Successfully connected to PipeWire daemon
    Connected,

    /// Connection to PipeWire lost
    Disconnected {
        reason: DisconnectReason,
        recoverable: bool,
    },

    /// A specific audio device was lost
    DeviceLost {
        device_id: String,
        device_name: String,
    },

    /// Successfully reconnected after disconnect
    Reconnected,

    /// PipeWire daemon is restarting
    DaemonRestarting,
}

enum DisconnectReason {
    DaemonCrashed,
    DaemonRestarted,
    SystemSleep,
    Unknown,
}
```

### Recovery Strategy

```
┌─────────────────────────────────────────────────────────────────┐
│                    PipeWire Disconnect                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │  Pause Recording  │
                    │  (don't lose data)│
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │  Notify Python    │
                    │  via event channel│
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │  UI shows warning │
                    │  "Connection lost"│
                    └─────────┬─────────┘
                              │
                              ▼
              ┌───────────────┴───────────────┐
              │                               │
              ▼                               ▼
    ┌─────────────────┐             ┌─────────────────┐
    │  Auto-reconnect │             │  User action    │
    │  (retry loop)   │             │  (if manual)    │
    └────────┬────────┘             └────────┬────────┘
              │                               │
              └───────────────┬───────────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │  Resume Recording │
                    │  (same session)   │
                    └───────────────────┘
```

### Implementation

```rust
impl AudioThread {
    fn run_with_watchdog(&mut self) {
        loop {
            match self.connect_pipewire() {
                Ok(core) => {
                    self.event_tx.send(PipeWireEvent::Connected).ok();

                    // Run main capture loop until disconnect
                    match self.capture_loop(&core) {
                        Ok(()) => break, // Clean shutdown
                        Err(PipeWireError::Disconnected(reason)) => {
                            self.event_tx.send(PipeWireEvent::Disconnected {
                                reason,
                                recoverable: true,
                            }).ok();

                            // Attempt reconnection
                            self.attempt_reconnect();
                        }
                        Err(e) => {
                            self.event_tx.send(PipeWireEvent::Disconnected {
                                reason: DisconnectReason::Unknown,
                                recoverable: false,
                            }).ok();
                            break;
                        }
                    }
                }
                Err(e) => {
                    // Initial connection failed
                    std::thread::sleep(Duration::from_secs(1));
                    continue;
                }
            }
        }
    }

    fn attempt_reconnect(&mut self) {
        for attempt in 1..=5 {
            std::thread::sleep(Duration::from_millis(500 * attempt as u64));

            if self.connect_pipewire().is_ok() {
                self.event_tx.send(PipeWireEvent::Reconnected).ok();
                return;
            }
        }
    }
}
```

### Python/UI Handling

```python
class RecordingWidget(QWidget):
    def handle_pipewire_disconnect(self):
        """Handle PipeWire connection loss gracefully."""
        self.status_label.setText("⚠️ Audio connection lost - reconnecting...")
        self.status_label.setStyleSheet("color: orange;")

        # Disable stop button until reconnected (data is safe)
        self.stop_button.setEnabled(False)

        # Show notification
        self.show_notification(
            "Audio Connection Lost",
            "Recording is paused. Reconnecting automatically...",
            level="warning"
        )

    def handle_pipewire_reconnected(self):
        """Handle successful reconnection."""
        self.status_label.setText("● Recording")
        self.status_label.setStyleSheet("color: green;")
        self.stop_button.setEnabled(True)

        self.show_notification(
            "Connection Restored",
            "Recording has resumed.",
            level="info"
        )
```

### Device Hot-Plug Handling

```python
def handle_device_lost(self, device_id: str, device_name: str):
    """Handle a specific device being disconnected."""

    if device_id == self.current_mic_id:
        # Microphone was lost
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Microphone Disconnected")
        dialog.setText(f"'{device_name}' was disconnected.")
        dialog.setInformativeText(
            "Recording will continue with system audio only.\n"
            "Reconnect the device or select a different microphone."
        )

        # Add device selection
        devices = granola_audio.list_devices()
        mic_devices = [d for d in devices if d.type == DeviceType.Microphone]

        if mic_devices:
            dialog.addButton("Select New Mic", QMessageBox.ButtonRole.AcceptRole)
        dialog.addButton("Continue Without Mic", QMessageBox.ButtonRole.RejectRole)

        dialog.exec()
```

---

## Storage Schema

### File System Structure

```
~/Granola/
├── recordings/
│   ├── 2024-01-15_093000_abc123/
│   │   ├── microphone.wav        # Local user audio
│   │   ├── system_audio.wav      # Meeting participants
│   │   ├── metadata.json         # Recording metadata
│   │   ├── transcript.json       # Transcription result
│   │   └── summary.md            # Generated summary
│   │
│   └── 2024-01-15_140000_def456/
│       └── ...
│
├── granola.db                    # SQLite database
└── config.toml                   # User settings
```

### Database Schema

```sql
-- Core tables

CREATE TABLE recordings (
    id TEXT PRIMARY KEY,
    title TEXT,
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    duration_seconds INTEGER,
    mic_device_id TEXT,
    mic_device_name TEXT,
    directory_path TEXT NOT NULL,
    status TEXT NOT NULL,  -- 'recording', 'completed', 'failed'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE transcripts (
    id TEXT PRIMARY KEY,
    recording_id TEXT NOT NULL REFERENCES recordings(id),
    transcript_json TEXT,  -- Full Gemini response
    summary TEXT,
    status TEXT NOT NULL,  -- 'pending', 'processing', 'completed', 'failed'
    processed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE speakers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    voice_sample_path TEXT,  -- For future speaker identification
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE transcript_segments (
    id TEXT PRIMARY KEY,
    transcript_id TEXT NOT NULL REFERENCES transcripts(id),
    speaker_id TEXT REFERENCES speakers(id),
    speaker_label TEXT,      -- "Speaker 1" if not identified
    start_time_ms INTEGER,
    end_time_ms INTEGER,
    text TEXT NOT NULL,
    confidence REAL
);

CREATE TABLE action_items (
    id TEXT PRIMARY KEY,
    transcript_id TEXT NOT NULL REFERENCES transcripts(id),
    text TEXT NOT NULL,
    assignee TEXT,
    due_date TEXT,
    status TEXT DEFAULT 'open',  -- 'open', 'completed'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Configuration File

```toml
# ~/Granola/config.toml

[audio]
default_mic = "bluez_input.XX_XX_XX_XX_XX_XX"
sample_rate = 48000
format = "wav"  # or "flac"

[storage]
recordings_dir = "~/Granola/recordings"
max_storage_gb = 50  # Auto-cleanup old recordings

[transcription]
provider = "gemini"
model = "gemini-1.5-pro"
# API key stored in system keyring, not here

[ui]
theme = "system"  # "light", "dark", "system"
start_minimized = false
show_in_tray = true
```

---

## Implementation Phases

### Phase 1: Foundation (Audio Capture)

**Goal**: Record mic and system audio to files via CLI.

**Tasks**:
1. Set up Rust project with PipeWire dependencies
2. Implement device enumeration
3. Implement basic recording (mic only)
4. Add system audio capture via monitor ports
5. Implement WAV encoding for both streams
6. Create minimal PyO3 bindings
7. Test with Python script

**Deliverable**: `granola_audio` crate that can be imported in Python and record audio.

```python
# End of Phase 1, this should work:
import granola_audio

devices = granola_audio.list_devices()
print(devices)

session = granola_audio.start_recording(output_dir="./test")
input("Press Enter to stop...")
session.stop()
# Creates: ./test/microphone.wav, ./test/system_audio.wav
```

---

### Phase 2: Core Application

**Goal**: Python application with basic GUI and recording management.

**Tasks**:
1. Set up Python project with maturin
2. Implement recording session management
3. Create SQLite database layer
4. Build main window UI (PyQt6)
5. Implement recording controls (start/stop/pause)
6. Add device selection UI
7. Implement recording history view
8. Add basic settings dialog

**Deliverable**: Functional GUI app that can record meetings.

---

### Phase 3: Transcription

**Goal**: Integrate Gemini API for transcription.

**Tasks**:
1. Implement Gemini API client
2. Add audio preprocessing (format conversion if needed)
3. Create transcription queue/manager
4. Build transcript viewer UI
5. Implement speaker labeling
6. Add transcript search functionality

**Deliverable**: App can transcribe recordings and display results.

---

### Phase 4: Analysis & Polish

**Goal**: Meeting summaries, action items, and production readiness.

**Tasks**:
1. Implement summary generation
2. Add action item extraction
3. Create export functionality (markdown, PDF)
4. Add system tray integration
5. Implement auto-start with system
6. Add keyboard shortcuts
7. Handle edge cases (device disconnection, etc.)
8. Performance optimization
9. Create distribution packages

**Deliverable**: Production-ready application.

---

## Development Setup

### Prerequisites

```bash
# System dependencies (Fedora)
sudo dnf install pipewire-devel rust cargo python3.12 python3.12-devel

# Or (Ubuntu/Debian)
sudo apt install libpipewire-0.3-dev rustc cargo python3.12 python3.12-dev

# Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Python environment
python3.12 -m venv .venv
source .venv/bin/activate
pip install maturin pyqt6
```

### Building

```bash
# Development build (Rust + Python)
maturin develop

# Release build
maturin build --release

# Run tests
cargo test                    # Rust tests
pytest tests/python/          # Python tests
```

### Useful Commands

```bash
# List PipeWire nodes (for debugging)
pw-cli list-objects

# Monitor PipeWire events
pw-mon

# Check Bluetooth status
bluetoothctl info
```

---

## Known Limitations & Future Work

### Current Limitations

These are known constraints in the initial implementation:

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| Single local speaker assumption | Mic track assumed to be one person | Works for headset use case; see "Conference Mode" below |
| Post-recording transcription only | No real-time captions | Acceptable for meeting notes use case |
| Gemini API dependency | Requires internet, has cost | Could add local Whisper fallback later |
| Linux-only | No Windows/macOS support | PipeWire is Linux-specific by design |

### Future Enhancements

#### Conference Mode (Multi-Speaker Mic)

**Problem**: When using a conference speakerphone (e.g., Jabra Speak), multiple people in the room speak through the microphone track. The current assumption that "mic = single local user" breaks down.

**Future Solution**:
```python
# Settings UI
[Recording Mode]
○ Personal (headset/laptop mic - single speaker)
● Conference (speakerphone - multiple speakers in room)

# When Conference mode is enabled:
# - Don't pre-label mic track as "Local User"
# - Tell Gemini to diarize BOTH channels
# - Potentially detect automatically via voice activity patterns
```

**Implementation approach**:
1. Add `recording_mode` to config: `personal` | `conference`
2. Adjust transcription prompt based on mode
3. (Future) Auto-detect based on multiple distinct voices on mic track

#### Per-Application Audio Capture

**Current**: Capture all system audio (everything playing through speakers).

**Future**: Capture only specific applications (e.g., just the browser tab with Google Meet).

```python
# Future UI
[System Audio Source]
○ All desktop audio
● Specific application: [Google Chrome - Meet ▼]
```

**Technical approach**: PipeWire supports targeting specific nodes by application. Requires enumerating application streams and linking to specific ones.

#### Local Transcription (Whisper)

**Current**: Gemini Cloud API only.

**Future**: Local transcription using Whisper for:
- Offline use
- Cost savings
- Privacy-sensitive recordings

```python
[transcription]
provider = "local"  # or "gemini"
local_model = "whisper-large-v3"
```

#### Real-Time Transcription

**Current**: Post-recording only.

**Future**: Live transcription overlay during meetings.

**Challenges**:
- Latency requirements (need results in <1-2 seconds)
- Streaming API integration
- UI overlay that doesn't interfere with meeting app

#### Speaker Identification

**Current**: Speakers labeled as "Speaker 1", "Speaker 2", etc.

**Future**: Match voices to known contacts.

```python
# Speaker database
speakers = [
    Speaker(name="Alice", voice_sample="alice_sample.wav"),
    Speaker(name="Bob", voice_sample="bob_sample.wav"),
]

# After transcription, match detected speakers to known voices
```

#### Calendar Integration

**Future**: Auto-name recordings based on calendar events.

```python
# If recording starts during "Team Standup" calendar event:
# - Auto-set recording title to "Team Standup"
# - Add expected attendees for speaker matching
```

#### Export Formats

**Current**: Markdown summary, JSON transcript.

**Future**:
- PDF export with formatting
- Notion integration
- Google Docs export
- Slack/Teams message formatting

---

## Resources

- [PipeWire Documentation](https://docs.pipewire.org/)
- [pipewire-rs (Rust bindings)](https://github.com/pipewire/pipewire-rs)
- [PyO3 User Guide](https://pyo3.rs/)
- [maturin Documentation](https://www.maturin.rs/)
- [Gemini API Documentation](https://ai.google.dev/docs)
- [PyQt6 Documentation](https://www.riverbankcomputing.com/static/Docs/PyQt6/)
