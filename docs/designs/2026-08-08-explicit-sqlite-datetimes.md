---
status: approved
approved_at: 2026-08-08T15:56:55-04:00
approved_body_sha256: 767811d03a62adb84684d1364804d360f50aa69ff4dc519d6ac8af041ca3e236
execution_authorized: true
---

# Canonical UTC SQLite Timestamps Design

## Goal

Replace Quinoa's mixed, implicit SQLite timestamp representation with one forward-compatible canonical format and migrate all existing timestamp rows.

Every persisted timestamp will represent an unambiguous instant as fixed-width UTC ISO 8601 text:

```text
2026-08-08T22:07:12.123456+00:00
```

All legacy naive timestamps are interpreted as `America/New_York`; legacy aware values preserve their instant. Python 3.12 and 3.13 must run without deprecated SQLite datetime-adapter warnings.

Backward compatibility with older Quinoa binaries that write the legacy format is not required after migration.

## Context

SQLite has no native datetime storage class. Quinoa declares `TIMESTAMP` columns but reads raw strings because connections do not enable `detect_types`.

Current data is mixed:

- Python's deprecated adapter writes naive application datetimes as space-separated local wall time, such as `2026-08-08 18:07:12.123456`.
- Google Calendar values may include offsets.
- `chat_history.timestamp DEFAULT CURRENT_TIMESTAMP` creates naive UTC strings.
- One range-query path already uses `T`-separated bounds while rows use spaces.
- Several UI paths parse timestamps correctly, while others slice raw date strings or format aware UTC values without converting to local display time.

Direct datetime binding triggers 27 warnings in the normal suite. With `DeprecationWarning` promoted to error, 13 focused tests fail at the deprecated adapter boundary.

The user has explicitly chosen a forward migration rather than preserving the legacy representation and has specified `America/New_York` as the interpretation for legacy naive application timestamps.

The repository is clean on `main` at `f369bbe2146ef66822774b4741e6541a2dacab15`. Ticket `qui-2mrl` is open and no Ticket is in progress.

## Decisions

1. **Canonical storage is UTC ISO text.** Use `datetime.astimezone(timezone.utc).isoformat(timespec="microseconds")`, producing a `T` separator, six fractional digits, and `+00:00`.
2. **Legacy naive application values mean New York wall time.** Attach `ZoneInfo("America/New_York")`, allowing historical DST rules to choose the UTC offset for each date, then normalize to UTC.
3. **Legacy chat defaults mean UTC.** Naive `chat_history.timestamp` values created by SQLite `CURRENT_TIMESTAMP` are interpreted as UTC, not New York.
4. **Legacy aware values preserve their instant.** Parse their offset and normalize directly to UTC.
5. **Migrate existing rows once.** Use `PRAGMA user_version = 1` as the durable migration marker. Migration is strict, transactional, and idempotent by version.
6. **Back up before rewriting populated databases.** Before the first timestamp migration of a file-backed database containing timestamp values, create a non-overwriting sibling backup named `<database>.pre-utc-v1.bak` through SQLite's backup API.
7. **Fail rather than guess malformed or DST-indeterminate values.** A nonempty timestamp that cannot be parsed, a nonexistent New York spring-forward wall time, or a fall-back wall time whose fold cannot be inferred aborts and rolls back migration with the table/column/key identified. The row can then be corrected to an explicit offset before retrying.
8. **All future database writes normalize.** One private serializer accepts datetime or ISO string input, interprets naive values as New York unless a column-specific UTC policy is requested, validates New York wall times by UTC round-trip/fold comparison, and always returns canonical UTC text.
9. **Application-generated timestamps become aware at origin where practical.** New recording start/end and database-generated created/synced times use `datetime.now(timezone.utc)` rather than naive `datetime.now()`.
10. **Query bounds normalize to UTC.** Naive UI/date-range bounds are interpreted as New York and serialized canonically before SQLite comparison.
11. **Display remains local.** Stored UTC values are parsed and converted to the machine's local timezone before user-visible formatting, grouping, and date-key generation.
12. **No global sqlite adapters/converters.** Do not call `sqlite3.register_adapter`, enable `detect_types`, or change database return types.
13. **Old binaries are unsupported after migration.** Rollback requires restoring the automatic backup or staying on the new code; running an old build against the migrated database may reintroduce mixed formats.

Alternatives rejected:

- Preserving the deprecated adapter's space-separated representation retains ambiguous naive timestamps and the existing query-format inconsistency.
- Storing Unix microseconds is compact and sortable but would require broader caller/type changes and makes manual database inspection harder without improving precision over fixed-microsecond UTC text.
- Storing New York offset text preserves wall dates but makes absolute lexical ordering unreliable across offsets and DST boundaries.
- Global adapters hide unreviewed direct binds and affect the whole process.

## Canonical Timestamp Contract

### Serialization

A shared storage helper accepts `datetime | str` and a policy for naive values:

1. Parse strings with `datetime.fromisoformat()`; support existing space or `T` separators and offsets.
2. If naive under New York policy, validate candidates exactly:
   - after parsing, call the naive datetime `local_value` and build `candidate = local_value.replace(tzinfo=NYC, fold=fold)` for each fold in `(0, 1)`;
   - compute `roundtrip = candidate.astimezone(UTC).astimezone(NYC)`;
   - a candidate is valid only when `roundtrip.replace(tzinfo=None) == local_value` and `roundtrip.fold == fold`;
   - zero valid candidates means nonexistent spring-forward time;
   - two valid candidates with different UTC offsets means ambiguous fall-back time;
   - one valid candidate (or two with the same offset) is unambiguous.
3. Legacy naive strings have no fold provenance and therefore reject ambiguity. A runtime naive `datetime` may use its explicit `fold` value when that exact candidate validates; future application-generated writes are aware UTC and avoid this path.
4. Under the legacy-chat UTC policy, attach UTC directly to naive SQLite `CURRENT_TIMESTAMP` values.
5. Convert to `timezone.utc` and emit `isoformat(timespec="microseconds")`.

Examples:

- Legacy New York summer wall time `2026-08-08 18:07:12.123456` → `2026-08-08T22:07:12.123456+00:00`
- Legacy New York winter wall time `2026-01-08 18:07:12` → `2026-01-08T23:07:12.000000+00:00`
- Aware `2026-08-08T18:07:12-04:00` → `2026-08-08T22:07:12.000000+00:00`
- Chat `2026-08-08 22:07:12` → `2026-08-08T22:07:12.000000+00:00`

### Reads

Database methods continue returning strings. Canonical strings are always aware UTC. Callers parse and convert to local display time where presentation or local-date grouping is required.

### Comparisons

Fixed-width UTC strings sort chronologically with ordinary SQLite text comparison. All write values and query bounds use the same canonical contract.

## Migration

### Versioning and transaction

After schema initialization, run a focused `_migrate_timestamps()` step on the same dedicated initialization connection. A process-level migration lock serializes `Database` construction; `BEGIN IMMEDIATE` plus an in-transaction version recheck protects against another process:

1. Read `PRAGMA user_version`; if version is at least 1, do nothing.
2. Start `BEGIN IMMEDIATE` and re-read `user_version`; if another initializer completed migration, roll back the empty transaction and stop.
3. Inventory non-null timestamp values across all affected columns.
4. Resolve the main database filename through `PRAGMA database_list`; an empty filename means in-memory and skips backup.
5. If timestamp values exist in a file-backed database, create the non-overwriting backup before timestamp updates. While the migration connection holds the reserved write lock, open a separate read source plus destination connection and call `source.backup(destination)`; close both backup connections before updates.
6. Parse and canonicalize every non-null timestamp according to its column policy.
7. Set `PRAGMA user_version = 1` only after all updates succeed.
8. Commit; on any error, roll back and leave version 0.

### Migrated columns

New York-naive policy:

- `recordings.started_at`, `recordings.ended_at`
- `meeting_folders.created_at`
- `speaker_profiles.last_used_at`
- `transcripts.created_at`
- `file_search_sync.last_synced_at`
- `calendar_events.start_time`, `calendar_events.end_time`, `calendar_events.synced_at`

UTC-naive policy:

- `chat_history.timestamp`

Null values remain null. Canonical aware UTC rows encountered during an interrupted/retried test normalize to themselves.

### Backup behavior

- Use separate source/destination `sqlite3.Connection` objects and `source.backup(destination)`, not a raw file copy.
- If `.pre-utc-v1.bak` already exists while `user_version` is still 0, abort before updates rather than overwrite or assume the backup is valid.
- New/empty or in-memory databases set version 1 without creating a backup.
- Tests use temporary database paths and remove their backup artifacts.

## Architecture

### `quinoa/storage/database.py`

Add private timezone/serialization helpers using `datetime`, `timezone`, and `zoneinfo.ZoneInfo`:

- parse datetime or string;
- attach the required naive timezone policy;
- normalize to fixed-microsecond UTC text;
- convert canonical stored values to local aware/naive values only through caller-facing utility code, not SQLite converters.

Refactor schema/migration initialization to use one short-lived dedicated connection under a class-level process lock, then close it before normal lazy thread-local connections are used. Add the versioned migration and backup orchestration after schema creation on that connection; `PRAGMA user_version` is database-global, not thread-local.

Use canonical serialization in:

- `get_all_past_calendar_events`
- `add_recording`
- `update_recording_status`
- `save_transcript`
- `get_recordings_in_range`
- `upsert_speaker_profile`
- `set_sync_status`
- `save_chat_message` (bind an explicit aware UTC timestamp instead of relying on `CURRENT_TIMESTAMP`)
- `upsert_calendar_events`
- `get_calendar_events`
- `get_current_meeting`
- `create_folder`

Database-generated timestamps use aware UTC now-values. Inputs that remain naive are interpreted as New York by contract.

### Shared display utility

Add `quinoa/datetime_utils.py` with typed helpers:

- `parse_timestamp(value: str | datetime) -> datetime` parses ISO text and treats unexpected naive runtime values as New York using the same strict DST validation;
- `to_local_datetime(value: str | datetime) -> datetime` returns an aware datetime in the machine's local timezone;
- `to_local_naive(value: str | datetime) -> datetime` supports existing comparisons against naive `get_now()`;
- `to_local_date_key(value: str | datetime) -> str` returns the local `YYYY-MM-DD` grouping key.

Use these helpers wherever stored timestamps are displayed, grouped, or turned into local date keys, including:

- meeting picker and meeting header in `middle_panel.py`;
- calendar event/recording items, Today/history grouping, and both raw `[:10]` date-key paths in `calendar_panel.py`;
- recent-series display dates in `main_window.py`;
- chat-context date formatting in `search/file_search.py`;
- File Search meeting-document dates in `search/content_formatter.py`;
- notification parsing in `calendar/notification_worker.py`.

Callers that merely transport the canonical string without displaying/grouping it may remain unchanged.

### Timestamp origins

Change recording database timestamps in `middle_panel.py` to aware UTC now-values. The local timestamp used only to form a human-readable recording ID/directory name remains local and unchanged.

Calendar API timestamps are already aware and normalize directly to UTC.

## Failure And Recovery

- Any malformed non-null legacy timestamp aborts the migration and application initialization with the offending table/column/key identified in the error; no partial timestamp rewrite or version bump is committed.
- The pre-migration backup remains untouched and can be restored manually if semantic review finds a problem after commit.
- Existing backup files are never overwritten.
- If backup creation fails, migration does not begin.
- An unsupported bind value remains a type error rather than being stringified.
- UTC conversion preserves instants and microseconds. Legacy naive accuracy is bounded by the explicitly approved New York assumption.
- An old Quinoa binary writing legacy timestamps after migration is unsupported and may create mixed data; this is an explicit compatibility break, not silently handled debt.

## Safety

- This is a user-data migration. Implementation and tests operate only on temporary databases until separately approved application rollout.
- The migration uses a transaction, a durable version marker, and a pre-write SQLite backup for populated file databases.
- No cloud, credential, MCP, API, or dependency behavior changes.
- Migration never deletes timestamp rows or silently skips malformed values.
- The discovered production source is `/home/rswift/.local/share/quinoa/quinoa.db`; the planned non-overwriting backup is `/home/rswift/.local/share/quinoa/quinoa.db.pre-utc-v1.bak`, which does not currently exist. Before any migration-enabled command opens that source, obtain explicit approval naming both paths and verify no Quinoa process is using the database. If either path changes, stop for renewed confirmation. Automated unit/CI tests do not touch user data.

## Testing

Add focused tests for:

1. Canonical fixed-width UTC serialization of naive New York summer/winter values, aware values, offsets, and microseconds.
2. Recording writes and query bounds using canonical UTC strings.
3. Calendar aware values and naive New York query bounds finding expected rows across local-day and DST boundaries.
4. Chat legacy naive UTC migration and explicit future chat timestamps.
5. Migration of every listed table/column from representative legacy space/T/aware values.
6. `PRAGMA user_version` idempotency: migration runs once and a second initialization makes no changes.
7. Populated file database backup creation and non-overwrite behavior.
8. New/empty database behavior without unnecessary backup.
9. Malformed, nonexistent spring-forward, and ambiguous fall-back timestamps aborting with table/column/key context, unchanged version, and unchanged source rows.
10. Process-concurrent initialization serialization plus `BEGIN IMMEDIATE`/version-recheck idempotency.
11. In-memory database setting version 1 without backup creation.
12. Pre-existing backup refusal without overwrite or source updates.
13. Display/local-date helpers preventing UTC date-boundary grouping regressions.
14. Warning-as-error coverage proving no deprecated datetime binding remains.

Tests use temporary SQLite files and controlled timezone-aware datetimes. They do not open the user's database.

## Testing And Verification

Fresh completion evidence must include:

1. Existing warning-as-error red evidence at the deprecated adapter boundary.
2. Migration/UTC/display regression tests failing for intended pre-implementation reasons, then passing.
3. `uv run pytest tests/python/test_database.py tests/python/test_transcription_manager.py -W error::DeprecationWarning` exiting zero.
4. Full Python suite with no SQLite datetime-adapter warnings.
5. `./scripts/check.sh` exiting zero, including mock/real Rust gates and real extension restoration.
6. Independent integrated review of migration safety, timestamp semantics, and all display/query consumers.
7. Hosted CI success on Python 3.12; local Python 3.13 success.
8. Production migration remains unexecuted unless separately confirmed with exact source and backup paths.

## Rollout And Rollback

Code and migration tests can be committed and shipped without manually launching Quinoa. The migration executes automatically only when the new application opens a version-0 database.

For the user's current database, first identify the exact database and planned backup paths, then obtain explicit confirmation before any manual application launch or migration command.

Rollback after migration means stopping Quinoa, replacing the migrated database with its `.pre-utc-v1.bak`, and running a compatible pre-migration build. Source rollback alone is not sufficient because old binaries are intentionally unsupported against version-1 timestamp data.

## Non-Goals

- Compatibility with old Quinoa binaries after migration.
- Preserving the legacy space-separated or naive timestamp representation.
- Recovering an unknown original timezone other than the approved New York assumption.
- Changing meeting ID/directory naming timestamps.
- Storing original calendar timezone identifiers in addition to UTC instants.
- Repairing malformed legacy timestamp values automatically.
- Redesigning unrelated database schema, pooling, or calendar behavior.
- Migrating the production database without separate explicit confirmation.

## Acceptance Criteria

- Every timestamp row is migrated once to fixed-width aware UTC ISO text and `PRAGMA user_version` records completion.
- Legacy naive application timestamps are interpreted with historical `America/New_York` rules; legacy chat defaults are interpreted as UTC; aware values preserve their instant.
- New writes and all query bounds use the canonical UTC contract without deprecated adapters.
- SQLite ordering and range/current/past queries operate over one lexically chronological representation.
- User-visible dates/times and local-day grouping remain correct after UTC storage.
- Populated file databases receive a non-overwritten pre-migration SQLite backup; failures roll back without a version bump.
- Reads remain strings, no global adapter/converter state is introduced, and old binaries are explicitly unsupported after migration.
- Warning-as-error tests, migration/display regressions, the canonical gate, independent review, and hosted CI pass on supported Python versions.
- No production database migration is run without exact-path confirmation.
