# Agent Guidelines for Granola Linux

This document provides guidance for AI agents working on the Granola Linux codebase.

## Project Overview

Granola Linux is a meeting recording and transcription application. It uses:
- **Python (PyQt6)** for the GUI and application logic
- **Rust (PyO3)** for audio capture via PipeWire
- **Google Gemini** for AI transcription
- **SQLite** for local storage

## Code Quality Standards

### Linting and Type Checking

All Python code must pass:
```bash
ruff check granola/ tests/
mypy granola/
```

Rust code should compile without warnings:
```bash
cargo check --features real-audio
```

### Style Guidelines

- **Python**: Follow ruff's default rules (pycodestyle, pyflakes, isort, flake8-bugbear)
- **Type Hints**: Use modern Python 3.10+ syntax (`str | None` not `Optional[str]`)
- **Logging**: Use the `granola` logger, never `print()` statements
- **Constants**: Hard-coded values go in `granola/constants.py`
- **Stylesheets**: UI styles go in `granola/ui/styles.py`

### File Organization

| Type | Location |
|------|----------|
| Constants | `granola/constants.py` |
| Logging config | `granola/logging.py` |
| UI styles | `granola/ui/styles.py` |
| Database ops | `granola/storage/database.py` |
| Transcription | `granola/transcription/` |
| UI components | `granola/ui/` |

## Key Files to Understand

1. **`granola/ui/main_window.py`** (~805 lines) - Main application window, recording controls, history tab
2. **`granola/storage/database.py`** - SQLite operations for recordings, transcripts, action items
3. **`granola/config.py`** - Configuration with keyring integration for API key storage
4. **`granola_audio/src/capture/session.rs`** - Rust recording session with PipeWire integration

## Common Tasks

### Adding a New Constant

1. Add to `granola/constants.py`
2. Import and use in relevant files
3. Run `ruff check` and `mypy`

### Adding UI Styles

1. Add to `granola/ui/styles.py`
2. Import and apply in `main_window.py` or relevant component
3. Keep styles DRY - use functions for parameterized styles

### Modifying Database Schema

1. Update `_init_db()` in `database.py`
2. Add migration logic for existing databases (check column exists before adding)
3. Update relevant methods with new fields
4. Add type hints to all method signatures

### Working with Audio (Rust)

1. Changes require rebuilding: `maturin develop --features real-audio`
2. Test with mock backend first: `maturin develop` (no features)
3. PipeWire must be running for real audio tests

## Testing

### Quick Smoke Test
```bash
python -m granola.main --test
```
This starts a 3-second recording and exits.

### Full Test Suite
```bash
pytest tests/python/
```

### Manual Testing Checklist
- [ ] Recording starts/stops correctly
- [ ] Pause/resume works
- [ ] Device hot-plug detected
- [ ] Transcription completes
- [ ] History tab shows recordings

## Architecture Decisions

### Why Rust for Audio?
PipeWire requires a dedicated event loop and real-time buffer handling. Python's GIL would cause audio glitches. Rust provides the necessary performance while PyO3 makes integration seamless.

### Why Separate Audio Tracks?
Recording microphone and system audio to separate channels allows Gemini to distinguish between the user and remote participants for better speaker diarization.

### Why Keyring for API Keys?
Security best practice - API keys are stored in the system keyring (GNOME Keyring, KDE Wallet) rather than plain text config files.

## Remaining Work

See `ACTION_PLAN.md` for detailed refactoring status. Current remaining items:
- Database helper methods (optional cleanup)
- Gemini model configurability
- Further UI component extraction (if main_window.py grows)

## Troubleshooting

### "No module named granola_audio"
Rebuild the Rust extension:
```bash
cd granola_audio && maturin develop --features real-audio && cd ..
```

### Missing Python dependencies
Install with uv:
```bash
uv pip install -e ".[dev]"
```

### Type errors after changes
Run mypy to catch issues:
```bash
mypy granola/
```

### Import sorting issues
Auto-fix with ruff:
```bash
ruff check --fix granola/
```
