# Quinoa

A meeting recording and transcription app for Linux. Records microphone and system audio separately, then uses Google Gemini for transcription with speaker diarization.

## Features

- **Dual-Channel Recording**: Captures your microphone and system audio (meeting participants) as separate tracks
- **Non-Invasive**: Uses PipeWire monitor ports - works alongside Google Meet, Zoom, etc. without interference
- **AI Transcription**: Google Gemini 2.5 Flash with speaker diarization, summaries, and action items
- **Bluetooth Support**: Works with Bluetooth headsets in HFP/HSP mode
- **Device Hot-Plug**: Automatically detects when audio devices are connected/disconnected
- **Pause/Resume**: Pause recording during breaks without creating multiple files

## System Requirements

Quinoa works on modern Linux distributions. It explicitly requires **PipeWire** for audio capture.

### Ubuntu Compatibility

- **Ubuntu 22.10 and newer**: PipeWire is the default. Works out of the box.
- **Ubuntu 22.04 LTS**: Uses PulseAudio by default. You must enable PipeWire:
  ```bash
  # Install PipeWire and compatibility layer
  sudo apt install pipewire pipewire-pulse

  # Enable and start the service
  systemctl --user --now enable pipewire pipewire-pulse
  ```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Python Application                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  PyQt6 GUI   │  │   Gemini     │  │  SQLite Storage  │   │
│  └──────┬───────┘  │ Transcription│  └──────────────────┘   │
│         │          └──────────────┘                          │
│         ▼                                                    │
│  ┌───────────────────────────────────────────────────────┐  │
│  │            quinoa_audio (Rust + PyO3)                │  │
│  │         PipeWire capture, device management           │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                ┌───────────────────────┐
                │       PipeWire        │
                └───────────────────────┘
```

**Why Rust for audio?** PipeWire requires a dedicated event loop and low-latency buffer handling. Rust provides safety and performance, exposed to Python via PyO3.

**Why separate tracks?** Recording mic (left) and system audio (right) separately helps Gemini distinguish between you and remote participants.

## Project Structure

```
quinoa/
├── quinoa/                    # Python application
│   ├── main.py                 # Entry point
│   ├── config.py               # Configuration (keyring for API key)
│   ├── constants.py            # Application constants
│   ├── logging.py              # Logging configuration
│   ├── storage/database.py     # SQLite operations
│   ├── transcription/
│   │   ├── gemini.py           # Gemini API client
│   │   └── processor.py        # Audio mixing for transcription
│   └── ui/
│       ├── main_window.py      # Main GUI
│       ├── settings_dialog.py  # Settings
│       ├── styles.py           # UI stylesheets
│       ├── transcribe_worker.py # Background transcription
│       └── transcript_handler.py # Transcript parsing utilities
│
├── quinoa_audio/              # Rust audio library
│   └── src/
│       ├── lib.rs              # PyO3 bindings
│       ├── capture/
│       │   ├── session.rs      # Recording session management
│       │   └── encoder.rs      # WAV encoding
│       └── device/
│           ├── enumerate.rs    # Device discovery
│           └── monitor.rs      # Hot-plug monitoring
│
└── tests/
    ├── python/                 # Integration tests
    └── manual/                 # Manual test scripts
```

## Development Setup

### Prerequisites

- Rust (latest stable)
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- PipeWire development headers

```bash
# Fedora
sudo dnf install pipewire-devel

# Ubuntu/Debian
sudo apt install libpipewire-0.3-dev
```

> **Note**: If you are on Ubuntu 22.04, ensure you have enabled PipeWire as described in [System Requirements](#system-requirements).

### Building

```bash
# Create virtual environment and install dependencies
uv venv
source .venv/bin/activate
uv pip install maturin PyQt6 google-genai keyring pydantic

# Install dev dependencies (optional)
uv pip install -e ".[dev]"  # Includes ruff, mypy, pytest

# Build Rust extension with PipeWire support
cd quinoa_audio
maturin develop --features real-audio
cd ..
```

### Running

```bash
# Option 1: Set API key via environment (temporary)
export GEMINI_API_KEY="your_key"
python -m quinoa.main

# Option 2: Set via Settings dialog (stored in system keyring)
python -m quinoa.main
# Then go to Settings and enter your API key
```

### Testing

```bash
# Run with mock audio backend (no PipeWire needed)
cd quinoa_audio
maturin develop  # Without --features real-audio
cd ..
python -m quinoa.main --test

# Run integration tests
pytest tests/python/

# Lint and type check
ruff check quinoa/ tests/
mypy quinoa/
```

## Usage

1. **Select Microphone** from the dropdown (auto-detects default)
2. **Check "Record System Audio"** to capture meeting participants
3. **Click "Start Recording"** - watch the VU meters for audio levels
4. **Pause/Resume** as needed during breaks
5. **Click "Stop Recording"** when done
6. **Click "Transcribe"** to send to Gemini
7. **View History** tab for past recordings and transcripts

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+R` | Start/Stop Recording |
| `Space`  | Pause/Resume |
| `Ctrl+Q` | Quit |

## Data Storage

| Data | Location |
|------|----------|
| Recordings | `~/Music/Quinoa/{session_id}/` |
| Database | `~/.local/share/quinoa/quinoa.db` |
| Config | `~/.config/quinoa/config.json` |
| API Key | System keyring (secure) |

Each recording session creates:
```
~/Music/Quinoa/rec_20241115_143022/
├── microphone.wav      # Your voice
├── system.wav          # Meeting participants
└── mixed_stereo.wav    # Combined (for transcription)
```

## Troubleshooting

### No audio devices found
```bash
# Check PipeWire is running
systemctl --user status pipewire

# List PipeWire nodes
pw-cli list-objects | grep -E "Audio/(Source|Sink)"
```

### Bluetooth headset shows no mic
Bluetooth headsets in A2DP (music) mode don't expose a microphone. Start a call or manually switch to HFP/HSP mode:
```bash
# Check current profile
pactl list cards | grep -A 20 "bluez"

# Switch to headset mode (enables mic)
pactl set-card-profile bluez_card.XX_XX_XX_XX_XX_XX headset-head-unit
```

### Recording is silent
- Check VU meters during recording - they should move when you speak
- Verify correct microphone is selected
- Check system audio is playing through expected output device

### Transcription fails
- Verify API key is set (Settings dialog or `GEMINI_API_KEY` env var)
- Check network connectivity
- Ensure audio files exist in the recording directory

## License

MIT
