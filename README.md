# Granola Linux

A meeting recording and transcription app for Linux, built with Rust (audio capture) and Python (GUI/Transcription).

## Features

- **Dual-Channel Recording**: Captures microphone and system audio (meeting participants) separately.
- **Transcription**: Uses Google Gemini 2.0 Flash for fast, accurate transcription with speaker diarization.
- **History**: Local database of past recordings and transcripts.
- **Non-Invasive**: Works alongside Google Meet, Zoom, etc. without interfering.

## Development Setup

### Prerequisites

- Rust (latest stable)
- Python 3.12+
- PipeWire development headers (`libpipewire-0.3-dev` on Debian/Ubuntu, `pipewire-devel` on Fedora)

### Building

1. Create a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install maturin PyQt6 google-genai
   ```

3. Build the Rust extension:
   ```bash
   cd granola_audio
   maturin develop --features real-audio
   cd ..
   ```

### Running

1. Set your Gemini API key:
   ```bash
   export GEMINI_API_KEY="your_api_key_here"
   ```

2. Run the application:
   ```bash
   python -m granola.main
   ```

## Usage

1. **Select Microphone**: Choose your input device from the dropdown.
2. **Record System Audio**: Keep checked to capture remote participants.
3. **Start Recording**: Click the button.
4. **Stop Recording**: Click again when done.
5. **Transcribe**: Click "Transcribe Last Recording" to generate a transcript.
6. **History**: Switch to the "History" tab to view past recordings and transcripts.

## Data Location

- **Recordings**: `~/Music/Granola/`
- **Database**: `~/.local/share/granola/granola.db`
