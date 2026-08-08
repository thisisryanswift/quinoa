# Quinoa

A meeting recording and transcription app for Linux. Records microphone and
system audio as separate tracks, then uses Google Gemini for transcription with
speaker diarization.

## Features

- **Dual-Channel Recording**: Captures your microphone and system audio
  (meeting participants) as separate tracks.
- **Non-Invasive**: Uses PipeWire monitor ports — works alongside Google Meet,
  Zoom, etc. without interference.
- **AI Transcription**: Google Gemini with speaker diarization, summaries, and
  action items.
- **Google Calendar Integration**: Meetings-first view with automatic
  recording-to-meeting linking.
- **Seamless Mic Switching**: Change microphones mid-recording without
  interruption.
- **Audio Compression**: Automatic WAV→FLAC conversion after transcription
  (~50% space savings).
- **Bluetooth Support**: Works with Bluetooth headsets in HFP/HSP mode.
- **Device Hot-Plug**: Automatically detects when audio devices are
  connected/disconnected.
- **Pause/Resume**: Pause recording during breaks without creating multiple
  files.
- **Trim UI**: Visually cut silence and unwanted regions from recordings.
- **AI Chat Assistant**: Ask questions across meetings using File Search
  context.

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

**Why Rust for audio?** PipeWire requires a dedicated event loop and
low-latency buffer handling. Rust provides safety and performance, exposed to
Python via PyO3.

**Why separate tracks?** Recording mic (left) and system audio (right) separately
helps Gemini distinguish between you and remote participants.

## Project Structure

```
quinoa/
├── quinoa/                    # Python application
│   ├── main.py                 # Entry point
│   ├── config.py               # Configuration (keyring for API key)
│   ├── constants.py            # Application constants
│   ├── logging.py              # Logging configuration
│   ├── audio/                  # Audio utilities (FFmpeg mixing/trimming)
│   │   ├── converter.py        # WAV→FLAC compression
│   │   ├── compression_worker.py # Background compression
│   │   ├── mixer.py            # Stereo mix for transcription
│   │   └── trimmer.py          # Silence/region trimming
│   ├── calendar/               # Google Calendar integration
│   ├── search/                 # Gemini File Search
│   ├── storage/database.py     # SQLite operations
│   ├── transcription/          # Gemini API client and manager
│   └── ui/                     # PyQt6 UI components
│
├── quinoa_audio/              # Rust audio library
│   └── src/
│       ├── lib.rs              # PyO3 bindings
│       ├── capture/            # Recording session, WAV encoding
│       └── device/             # Device discovery and hot-plug monitoring
│
├── tests/
│   ├── python/                 # Automated Python tests
│   └── manual/                 # Manual test scripts
│
├── scripts/
│   ├── check.sh                # Canonical local/CI quality gate
│   └── bundle.sh               # Local desktop bundling
│
├── quinoa.desktop              # Portable desktop entry template
├── pyproject.toml              # Python project + Maturin config
├── quinoa_audio/Cargo.toml     # Rust crate features
└── LICENSE                     # MIT License
```

## Development Setup

### Prerequisites

- Rust (latest stable)
- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- PipeWire development headers
- **FFmpeg** and **ffprobe** (runtime dependency for audio mixing and trimming)

System packages:

```bash
# Fedora
sudo dnf install pipewire-devel clang clang-devel ffmpeg

# Ubuntu/Debian
sudo apt install libpipewire-0.3-dev clang ffmpeg
```

Optional, only for `scripts/bundle.sh`:

```bash
# Fedora
sudo dnf install ImageMagick desktop-file-utils

# Ubuntu/Debian
sudo apt install imagemagick desktop-file-utils
```

### Building

```bash
# Sync Python dependencies (dev group included)
uv sync --locked --all-groups

# Build the Rust extension for mock audio (no PipeWire needed)
cd quinoa_audio
uv run maturin develop --no-default-features --features extension-module,mock
cd ..

# Or build the real PipeWire extension from the project root
uv run maturin develop
```

### Running

```bash
uv run python -m quinoa.main
```

Then open **Settings** and enter your Gemini API key. The app stores the key in
your system keyring (GNOME Keyring, KDE Wallet, etc.) and reads it from there
for transcription and chat. The UI and `TranscriptionManager` gate transcription
on the keyring value, so setting `GEMINI_API_KEY` in the environment does not
bypass the Settings/keyring flow.

## Testing

The canonical quality gate is:

```bash
./scripts/check.sh
```

It checks locked dependencies, Ruff format and lint, Mypy, Python tests, Rust
format, Rust real/mock checks and real-audio tests, shell syntax, and desktop
entry validation.

Run only the Python tests with:

```bash
uv run pytest tests/python
```

### Smoke test warning

```bash
uv run python -m quinoa.main --test
```

This starts a short recording and exits, but it writes a real recording to
`~/Music/Quinoa/` and mutates the production database. Run it only when you
intend to create recording state. It is intentionally excluded from
`./scripts/check.sh` and CI.

## Usage

1. **Select Microphone** from the dropdown (auto-detects default).
2. **Check "Record System Audio"** to capture meeting participants.
3. **Click "Start Recording"** and watch the VU meters for audio levels.
4. **Pause/Resume** as needed during breaks.
5. **Click "Stop Recording"** when done.
6. **Click "Transcribe"** to send to Gemini (or enable auto-transcribe in
   Settings).
7. **View History** for past recordings, transcripts, and the trim view.

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

Each recording session creates a directory such as
`~/Music/Quinoa/rec_20241115_143022/` containing:

```
microphone.wav      # Your voice (converted to .flac after transcription)
system.wav          # Meeting participants (converted to .flac after transcription)
mixed_stereo.wav    # Combined for transcription (converted to .flac after transcription)
```

After transcription, WAV files are automatically compressed to FLAC. Original
WAV files are kept as backup.

## Desktop Bundling

`scripts/bundle.sh` builds a local desktop release:

```bash
./scripts/bundle.sh
```

It builds the Rust extension in release mode, creates a wrapper at
`~/.local/bin/quinoa`, installs the icon, and writes
`~/.local/share/applications/quinoa.desktop` with `Exec` and `Icon` rewritten
to current-user absolute paths. The checked-in `quinoa.desktop` remains portable
and validates successfully with `desktop-file-validate`.

Requires ImageMagick (`magick`) and `desktop-file-utils` (for
`update-desktop-database` and `gtk-update-icon-cache`).

## Troubleshooting

### No audio devices found

```bash
# Check PipeWire is running
systemctl --user status pipewire

# List PipeWire nodes
pw-cli list-objects | grep -E "Audio/(Source|Sink)"
```

### Bluetooth headset shows no mic

Bluetooth headsets in A2DP (music) mode do not expose a microphone. Start a
call or manually switch to HFP/HSP mode:

```bash
# Check current profile
pactl list cards | grep -A 20 "bluez"

# Switch to headset mode (enables mic)
pactl set-card-profile bluez_card.XX_XX_XX_XX_XX_XX headset-head-unit
```

### Recording is silent

- Check VU meters during recording — they should move when you speak.
- Verify the correct microphone is selected.
- Check system audio is playing through the expected output device.

### Transcription fails

- Verify the API key is saved in **Settings** (stored in the system keyring).
- Check network connectivity.
- Ensure audio files exist in the recording directory.

## License

MIT. See [LICENSE](LICENSE).
