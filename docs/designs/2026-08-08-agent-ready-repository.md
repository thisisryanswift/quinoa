---
status: approved
approved_at: 2026-08-08T13:51:42-04:00
approved_body_sha256: ea642f781b54709058a292865f72f06b4118b6d46ddbcd9c98f7f6081013f017
execution_authorized: true
---

# Agent-Ready Repository Baseline Design

## Goal

Make Quinoa a truthful, deterministic, agent-neutral development repository. A new human or coding agent should be able to discover the architecture, choose work, install dependencies, run one canonical verification suite, and receive the same quality gates in GitHub Actions.

This pass establishes that baseline without expanding product scope. Broader warning, dependency, coverage, and release-process improvements will be captured as follow-up Tickets for the next hygiene pass.

## Context

The repository is clean on `main` at `392d6192b5adef5f9fdec201ea528d8bbde699a9`, synchronized with `origin/main`. Ticket currently has no ready work and one backlog ticket.

Fresh audit evidence:

- `uv lock --check`, Ruff lint, Mypy over `quinoa` and `tests`, all 118 Python tests, Rust formatting, and real/mock `cargo check` pass.
- Ruff formatting reports 19 existing files that require formatting.
- `cargo test --locked --features real-audio` fails to link because `quinoa_audio/Cargo.toml` enables PyO3's `extension-module` feature for every Cargo target. Extension builds need that feature, but Rust test executables need normal Python linkage. `pyproject.toml` already enables `pyo3/extension-module` specifically for Maturin builds.
- Python tests emit 27 SQLite datetime-adapter deprecation warnings on Python 3.13.
- Real-audio Clippy with warnings denied reports nine findings; Clippy is not currently a declared gate.
- No CI workflow exists.
- README, AGENTS, ROADMAP, project skills, `.gitattributes`, and the recently added Devin worker configuration contain confirmed drift or duplication.
- `quinoa.desktop` hard-codes one developer's home path; `scripts/bundle.sh` rewrites only the icon, so local bundling is not portable to another user.
- README claims MIT licensing, but the repository has no license file.

The authoritative cross-agent contract will be ordinary repository artifacts: `AGENTS.md`, checked-in docs, Ticket commands, and canonical shell scripts. `.agents/skills` remains the shared skill location where a skill adds durable project value. Client-specific files remain optional thin adapters and cannot be required to understand or verify the repository.

## Decisions

1. **Balanced scope now.** Correct documentation and agent configuration, establish deterministic local/CI checks, repair the Rust test configuration, format the existing Python baseline, make desktop bundling portable, and add the MIT license.
2. **Agent-neutral core with thin adapters.** `AGENTS.md` and scripts are complete on their own. Keep `opencode.json` as a small OpenCode permissions adapter and `.devin/agents/swe-worker.md` as a low-cost Devin worker profile.
3. **Remove stale or unsafe duplication.** Remove the project-local dynamic Gemini model skill, because it is stale, collides with user/global skills, and embeds fast-changing model claims. Remove the duplicate Devin subagent skill and shared tracked assignment file; direct custom-subagent prompts already provide a safer interface.
4. **Retain useful shared skills.** Keep the PyQt6 and UX skills. Make PyQt6 guidance client-neutral and align its worker lifecycle guidance with Quinoa's cooperative cancellation pattern.
5. **One canonical verifier.** Add `scripts/check.sh`; local instructions and CI call the same script rather than maintaining parallel command lists.
6. **Core CI now.** Add a GitHub Actions workflow on Linux using locked dependencies and system packages required by PipeWire, FFmpeg, Maturin/PyO3, and desktop-file validation.
7. **Format now.** Apply Ruff formatting to `quinoa/` and `tests/`, then enforce `ruff format --check` in the canonical verifier.
8. **MIT attribution.** Add the standard MIT text with `Copyright (c) 2025 Ryan Swift`.
9. **No project MCP dependency.** Do not commit personal/global MCP servers or credentials. Ignore Devin local MCP/config files in the repository and document that MCP is optional client augmentation, not a build prerequisite.
10. **Defer broader hygiene durably.** Create a flat set of focused follow-up Tickets rather than expanding this pass into unrelated refactors. The Ticket workflow intentionally avoids parent epics and dependency edges when each outcome can proceed independently.

Alternatives rejected:

- Keeping all current adapters unchanged preserves an unsafe shared assignment file and stale skill collision.
- Removing every client adapter gives up useful, low-cost behavior without improving portability; optional adapters do not prevent other agents from working.
- Adding Clippy, warning-free tests, coverage thresholds, release automation, and dependency pruning to this pass would mix baseline repair with policy decisions and unrelated source refactors.

## Behavior

After this pass:

- `AGENTS.md` gives any agent the complete project workflow without assuming Devin, OpenCode, Claude, or another client.
- `./scripts/check.sh` is the documented local quality gate and exits nonzero on lock drift, Python format/lint/type/test failures, Rust format/check/test failures, shell syntax errors, or invalid desktop metadata.
- GitHub Actions executes the same gate in a clean Linux environment.
- Python formatting has a clean baseline; agents do not inherit 19 existing formatter failures.
- Rust unit tests build as normal test executables while Maturin extension builds continue enabling `pyo3/extension-module` through `pyproject.toml`.
- `scripts/bundle.sh` installs a desktop entry whose `Exec` and `Icon` values resolve for the current user, while the checked-in `quinoa.desktop` remains portable and validates successfully.
- README setup, runtime dependencies, architecture, feature summary, storage, desktop installation, testing, and licensing match the repository.
- ROADMAP no longer claims the trim feature has zero tests and records the August 2026 hardening work without inventing completion for unresolved product ideas.
- `tk ls --status=open`, `tk ready`, and other documented Ticket commands match actual CLI behavior.
- OpenCode and Devin can use their optional adapters; other agents can ignore them and still follow the full workflow.
- No repository MCP configuration, OAuth token, API key, or user-specific server is required or committed.

## Architecture

### Documentation and neutral workflow

- **`README.md`**: simplify the source tree to durable components; add FFmpeg and local-bundle prerequisites; use `uv`/Maturin commands consistently; document `scripts/check.sh`; clarify automatic versus manual transcription and the mutating recording smoke test; document current features and desktop bundling; retain accurate storage/keyring guidance.
- **`AGENTS.md`**: become the concise source of truth for agent workflow, architecture boundaries, Ticket lifecycle, file ownership, canonical checks, test tiers, and client-neutral safety constraints. Correct Python and Ticket command inaccuracies. Point to source/docs instead of copying a brittle exhaustive tree.
- **`ROADMAP.md`**: correct test status and add the completed hardening session. Preserve unresolved product plans as plans; do not infer implementation merely from closed Ticket status.

### Shared skills and client adapters

- **`.agents/skills/pyqt6-dev/**`**: remove Gemini-CLI wording. Its existing cooperative-cancellation preference is directionally correct; remove the `terminate()` example so the skill cannot suggest a lifecycle mechanism Quinoa explicitly avoids.
- **`.agents/skills/ux-design/**`**: retain unchanged unless review finds a direct factual conflict.
- **`.agents/skills/gemini-api-dev/`**: remove after a separate, explicit deletion confirmation. Current model catalogs belong in maintained global/vendor documentation, not a project snapshot.
- **`opencode.json`**: retain only useful OpenCode permissions; remove permission entries for deleted skills.
- **`.devin/agents/swe-worker.md`**: retain as the thin Devin adapter for bounded low-cost implementation work.
- **`.devin/skills/swe-worker/` and `.devin/swe-worker-task.md`**: remove after separate, explicit deletion confirmation. The custom profile already accepts a direct task, while the shared assignment file creates tracked-file churn and parallel-worker races.
- **`.gitignore`**: ignore `.devin/config.local.json` and `.devin/mcp_config.local.json`; keep personal secrets untracked.
- **`.gitattributes`**: remove its obsolete Beads-only merge rule after separate, explicit deletion confirmation.

### Deterministic verification

Add executable **`scripts/check.sh`** with fail-fast commands for:

1. `uv lock --check`
2. `uv run ruff format --check quinoa tests`
3. `uv run ruff check quinoa tests`
4. `uv run mypy quinoa tests`
5. `uv run pytest tests/python`
6. `cargo fmt --all -- --check`
7. `cargo check --locked --no-default-features --features real-audio`
8. `cargo check --locked --no-default-features --features mock`
9. `cargo test --locked --no-default-features --features real-audio`
10. `bash -n scripts/bundle.sh`
11. `desktop-file-validate quinoa.desktop` when the validator is available locally; CI installs it and therefore always runs it

The script must not launch the GUI, access Gemini/Calendar APIs, read personal secrets, or create recordings.

Add **`.github/workflows/ci.yml`** on `ubuntu-latest` using `actions/checkout@v4` and `astral-sh/setup-uv@v6`. It installs the UV tool, installs `libpipewire-0.3-dev`, `pkg-config`, `clang`, `libclang-dev`, `ffmpeg`, `desktop-file-utils`, and `python3-dev`, then runs `uv sync --locked --all-groups --python 3.12` to provision Python 3.12 and project dependencies before invoking `scripts/check.sh`. The runner-provided stable Rust toolchain is sufficient unless implementation evidence proves otherwise. The workflow will not deploy, publish, upload user data, or require repository secrets.

### Build and desktop integration

- **`quinoa_audio/Cargo.toml`**: remove the unconditional `extension-module` feature from the PyO3 dependency and add an `extension-module = ["pyo3/extension-module"]` crate feature. Change **`pyproject.toml`** Maturin features to `extension-module` plus `real-audio`. Normal Cargo checks/tests then link Python, while Maturin builds still opt into extension-module behavior. The README's explicit mock extension command uses `--no-default-features --features extension-module,mock` from `quinoa_audio/`.
- **Python sources and tests**: apply Ruff formatting only; do not mix behavioral refactors into formatting changes.
- **`quinoa.desktop` and `scripts/bundle.sh`**: change the checked-in entry to `Exec=quinoa`. During bundling, rewrite `Exec` to the absolute `$HOME/.local/bin/quinoa` wrapper and `Icon` to the installed current-user icon path. Preserve the existing local-release behavior.
- **`LICENSE`**: add standard MIT license text with the approved attribution.

### Deferred hygiene Tickets

Create independent, unstarted hygiene Tickets with no parent or dependency edges, covering:

1. remove SQLite datetime-adapter deprecation warnings and verify Python 3.12/3.13 behavior;
2. remediate and adopt a real/mock Clippy policy;
3. audit unused/stale Python and Rust dependencies plus the obsolete Gemini SDK upload workaround;
4. define coverage reporting and a non-arbitrary threshold;
5. resolve graceful SIGINT shutdown/data-loss risk before release;
6. define release/version/changelog/security/contributor policy;
7. reconcile closed product epics and ROADMAP checklists where ticket status and remaining scope disagree.

## Failure And Recovery

- The canonical verifier fails immediately and leaves the worktree unchanged except for normal ignored build/cache artifacts.
- Local desktop validation is skipped with a clear message only when `desktop-file-validate` is unavailable; CI makes the check mandatory.
- CI dependency installation or platform incompatibility is treated as an infrastructure failure, not hidden with permissive `|| true` behavior.
- If removing PyO3's crate-level extension feature breaks Maturin development builds, revert that focused change and revise the design; do not disable Rust tests.
- If bulk formatting changes behavior or exposes a mixed-ownership file, stop and review that file before continuing. The current baseline is clean, so no mixed ownership is expected.
- Documentation changes must not claim that live Gemini, Calendar OAuth, PipeWire hardware, Bluetooth, or notification flows were exercised unless a corresponding manual check was actually run.
- Follow-up Ticket creation is idempotent by title inspection; do not create duplicates if equivalent open Tickets appear before execution.

## Safety

- No secrets, MCP credentials, OAuth tokens, API keys, personal server definitions, or local absolute paths will be committed.
- CI uses no application secrets and does not call external Gemini or Calendar APIs.
- The application smoke mode is excluded from automated verification because it can create a recording and mutate the user's normal database/output directory.
- No push, pull request, branch protection change, release, deployment, or commit is included.
- Removing tracked skill/config files is irreversible at the filesystem level. Immediately before deletion, request explicit confirmation for exactly: `.agents/skills/gemini-api-dev/`, `.devin/skills/swe-worker/`, `.devin/swe-worker-task.md`, and `.gitattributes`. No other path may be included under that confirmation. Git history remains a recovery path but does not replace confirmation.
- New GitHub workflow actions will use stable, established action releases; no floating `latest` references.
- The license addition records the user's explicit MIT choice and approved attribution.

## Testing And Verification

Fresh completion evidence must include:

1. clean `git diff --check`;
2. `./scripts/check.sh` exiting zero from the project root;
3. `uv run maturin develop` from the project root followed by `uv run python -c 'import quinoa_audio; print(quinoa_audio.__file__)'`, proving that `[tool.maturin]` enables the real extension features after the PyO3 change;
4. `(cd quinoa_audio && uv run maturin develop --no-default-features --features extension-module,mock)` followed by the same import check, proving the README's mock extension command;
5. `cargo check --locked --no-default-features --features mock`, proving explicit mock Cargo compatibility;
6. review of the GitHub workflow structure and commands, with a clear statement that hosted CI execution remains unproven because push/PR actions are outside this pass;
7. `desktop-file-validate quinoa.desktop` with no errors;
8. targeted inspection that README/AGENTS/ROADMAP commands and paths exist;
9. `tk ready`, `tk ls --status=open`, and inspection of newly created deferred Tickets;
10. final `git status --short --branch` proving no unrelated files changed.

After implementation converges, a fresh read-only integrated review will compare the full diff to this approved design. Material findings will be fixed and re-reviewed before final verification.

## Rollout And Rollback

No data migration or application rollout is required. Changes affect repository metadata, development tooling, CI, formatting, one build-feature boundary, and local desktop bundling.

Rollback is file-scoped: revert the workflow/script/docs/adapter changes independently. The PyO3 feature change can be reverted independently if Maturin compatibility cannot be proven. No user database, recording, keyring, or cloud state is modified.

## Non-Goals

- Product features or UI redesigns.
- Fixing Python deprecation warnings in this pass.
- Enforcing or repairing all Clippy findings in this pass.
- Choosing a coverage threshold or adding coverage dependencies now.
- Dependency upgrades or broad dependency pruning.
- Release automation, packaging formats such as Flatpak/AppImage, branch protection, or publishing.
- Committing personal/global MCP server configuration.
- Rewriting closed product Tickets or deciding whether partially completed product epics should be reopened; that reconciliation is deferred to a focused hygiene Ticket.
- Running live Gemini, Calendar, notification, Bluetooth, or real recording manual tests without a separate explicit request.
- Creating a commit, pushing, or opening a pull request.

## Acceptance Criteria

- A client without OpenCode or Devin-specific support can derive the full workflow from `AGENTS.md` and execute the same canonical check suite used by CI.
- README, AGENTS, and ROADMAP contain no confirmed stale paths, false test-gap statements, incorrect Ticket commands, or user-specific installation instructions.
- OpenCode and Devin adapters are thin, optional, and contain no duplicated authoritative workflow or shared mutable task state.
- Stale Gemini model guidance and Beads residue are absent after explicitly confirmed removals.
- All Python files under `quinoa/` and `tests/` pass Ruff format and lint checks; Mypy passes over both trees; all collected Python tests pass.
- Real and mock Rust checks pass, and real-audio Rust unit tests link and pass without weakening the Maturin extension build.
- `scripts/check.sh` completes locally with locked dependencies, and GitHub Actions invokes that same script from a clean locked setup. Hosted execution is explicitly reported as unverified until a later authorized push runs the workflow.
- The desktop entry validates and the bundle script generates current-user `Exec` and `Icon` paths rather than a hard-coded developer path.
- The repository includes the standard MIT license with `Copyright (c) 2025 Ryan Swift`.
- Personal secrets and local MCP/config files remain ignored; no project MCP server is required.
- Deferred comprehensive-hygiene work is represented by non-duplicate, unstarted Tickets with concrete outcomes.
- No unrelated product behavior, personal data, remote state, or Git history is changed.
