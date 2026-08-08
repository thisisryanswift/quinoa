# Agent Guidelines for Quinoa

This document is the source of truth for AI agents working on Quinoa. It is
client-neutral; optional adapter files for OpenCode or Devin may exist, but they
are not required to understand or verify the repository.

## Project Overview

Quinoa is a meeting recording and transcription application for Linux.

- **Python (PyQt6)** drives the GUI and application logic.
- **Rust (PyO3)** handles audio capture and device management in `quinoa_audio/`.
- **FFmpeg** mixes, trims, and converts audio at runtime.
- **Google Gemini** provides transcription and chat (live API; not used in
  automated tests).
- **SQLite** stores meetings, transcripts, and notes locally.
- **Keyring** stores the Gemini API key and File Search store name securely.

## Project Management (Ticket)

Use the Ticket CLI (`tk`) for task tracking.

### Core workflow

1. Start of session: `tk ready` (unblocked work) or `tk ls --status=open` (all
   open tickets).
2. Start work: `tk start <ticket-id>`.
3. Create follow-ups: `tk create "Title"`.
4. Close when done: `tk close <ticket-id>`.

### Useful commands

- `tk ls --status=open` — list open tickets
- `tk ready` — list unblocked tickets ready for work
- `tk blocked` — list blocked tickets
- `tk show <id>` — view ticket details
- `tk query` — export tickets as JSON
- `tk help` — see all commands

Preserve closed ticket history: never rewrite, delete, or alter a closed
ticket's record. If a closed ticket reveals genuinely new work, prefer a
follow-up ticket. Reopen a closed ticket only when the original ticket is
demonstrably incomplete and the product intent is confirmed.

## Code Quality Standards

Run the canonical verifier before finishing:

```bash
./scripts/check.sh
```

The script checks, in order: locked UV dependencies, Ruff format and lint,
Mypy, Python tests against a mock audio build, Rust format, Rust mock/real
checks and real-audio tests, and then restores the real PipeWire extension.
It also checks shell syntax and desktop-file validation.

### Python

- Target Python 3.12+ syntax (`str | None`, not `Optional[str]`).
- Follow Ruff's configured rules; use `uv run ruff check --fix quinoa tests` for
  safe fixes.
- Run `uv run mypy quinoa tests` after changes.
- Use the `quinoa` logger; do not use `print()` in application code (tests may
  print).

### Rust

- `quinoa_audio` builds as a `cdylib` via PyO3.
- `cargo check --locked --no-default-features --features real-audio` (PipeWire)
  and `--features mock` must pass.
- `cargo test --locked --no-default-features --features real-audio` must link
  and pass.
- Maturin extension builds enable `extension-module` through `pyproject.toml`;
  normal Cargo checks/tests do not.

## File Ownership

| Concern | Location |
|---|---|
| Constants | `quinoa/constants.py` |
| Logging | `quinoa/logging.py` |
| UI styles | `quinoa/ui/styles.py` |
| Database | `quinoa/storage/database.py` |
| Audio utilities (FFmpeg) | `quinoa/audio/` |
| Transcription | `quinoa/transcription/` |
| Calendar integration | `quinoa/calendar/` |
| File Search | `quinoa/search/` |
| UI components | `quinoa/ui/` |
| Rust audio library | `quinoa_audio/` |
| Automated Python tests | `tests/python/` |

See `README.md` for the current source tree and `ROADMAP.md` for milestones.

## Key Files

1. `quinoa/ui/main_window.py` — main window, worker orchestration, pending-worker
   cleanup.
2. `quinoa/ui/middle_panel.py` — recording controls, notes/transcript viewer.
3. `quinoa/ui/calendar_panel.py` — left panel meeting list.
4. `quinoa/storage/database.py` — SQLite operations and migrations.
5. `quinoa/config.py` — configuration; keyring-backed secrets.
6. `quinoa/transcription/manager.py` — transcription job queue and cooperative
   cancellation.
7. `quinoa_audio/src/capture/session.rs` — Rust recording session, device
   switching.

## Common Tasks

### Add a constant

1. Add to `quinoa/constants.py`.
2. Import and use where needed.
3. Run `uv run ruff check quinoa tests` and `uv run mypy quinoa tests`.

### Modify the database schema

1. Update `_init_db()` in `quinoa/storage/database.py`.
2. Add defensive migration logic for existing databases (check column/table
   before adding).
3. Add type hints and update relevant queries.
4. Run `tests/python/test_database.py`.

### Work with audio

- Mock build (no PipeWire):
  `cd quinoa_audio && uv run maturin develop --no-default-features --features extension-module,mock`
- Real build: `uv run maturin develop` from the project root.
- `quinoa/audio/mixer.py` and `quinoa/audio/trimmer.py` use FFmpeg at runtime;
  `ffmpeg` and `ffprobe` must be in `PATH`.

## Testing

### Automated suite

```bash
uv run pytest tests/python
```

The canonical `./scripts/check.sh` runs this plus Rust and format gates.

### Smoke test warning

```bash
uv run python -m quinoa.main --test
```

This starts a short recording, writes to the normal output directory
(`~/Music/Quinoa/`), and mutates the production database. Run it only when you
intend to create recording state. It is excluded from CI and
`./scripts/check.sh`.

### Manual checks (run only with permission)

- Recording start/stop, pause/resume.
- Microphone switching during recording.
- Device hot-plug detection.
- Transcription and history display.
- Live calendar sync and notifications.

## Architecture Decisions

### Why Rust for audio?

PipeWire needs a dedicated event loop and low-latency buffer handling. Rust
provides safety and performance, exposed to Python via PyO3.

### Why separate tracks?

Microphone and system audio are recorded as separate WAV tracks and mixed to
stereo for transcription. The channel separation helps Gemini distinguish the
local speaker from remote participants.

### Why keyring for API keys?

API keys and File Search store names are stored in the system keyring (GNOME
Keyring, KDE Wallet, etc.) instead of plain-text config files.

## Safety Constraints

- Do not commit secrets, MCP credentials, OAuth tokens, API keys, or personal
  server definitions.
- Do not run live Gemini or Calendar calls unless explicitly requested.
- Do not run `python -m quinoa.main --test` in an automated check.
- Do not delete tracked files, run destructive Git or filesystem operations, or
  modify security controls without explicit authorization.
- Preserve closed tickets and repository history; create new tickets for new
  work rather than rewriting history.
- Client-specific adapter files are optional; authoritative workflow lives here
  and in `README.md`.

## Troubleshooting

### "No module named quinoa_audio"

- Mock build:
  `cd quinoa_audio && uv run maturin develop --no-default-features --features extension-module,mock`
- Real build: `uv run maturin develop` from the project root

### Missing Python dependencies

```bash
uv sync --locked --all-groups
```

### Type errors after changes

```bash
uv run mypy quinoa tests
```

### Import sorting or lint issues

```bash
uv run ruff check --fix quinoa tests
```
