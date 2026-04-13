# Tasks: Enterprise Chatwoot Migration

**Input**: `.specify/features/001-enterprise-chatwoot-migration/`
**Prerequisites**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/cli-contract.md ✅ | quickstart.md ✅
**Generated**: 2026-04-10
**Branch**: `001-enterprise-chatwoot-migration`
**Tests**: Required by spec.md §FR-012 (90% coverage gate on critical modules)

## Format: `- [ ] [TaskID] [P?] [Story?] Description — file path`

- **[P]**: Parallelizable — different file, no incomplete dependency in the same phase
- **[US1/US2/US3]**: Which user story this task belongs to
- Setup and Foundational phases: no story label

---

## Phase 1: Setup

**Purpose**: Source tree structure, tooling config, test scaffolding

- [X] T001 Create src/ subdirectory tree: `src/factory/`, `src/migrators/`, `src/repository/`, `src/utils/`, `src/reports/` with `__init__.py` in each package
- [X] T002 [P] Configure `pyproject.toml`: add dependencies (SQLAlchemy==2.0.49, psycopg2-binary==2.9.11, alembic==1.18.4) and dev dependencies (ruff==0.15.10, black==26.3.1, pytest==9.0.3, pytest-cov) — `pyproject.toml`
- [X] T003 [P] Configure pytest in `pyproject.toml`: `[tool.pytest.ini_options]` with `testpaths = ["test"]`, `addopts = "--cov=src --cov-report=term-missing --fail-under=90"`, `python_files = "test_*.py"` — `pyproject.toml`
- [X] T004 [P] Configure ruff and black in `pyproject.toml`: `[tool.ruff]` with `select = ["E","F","I","B","UP","D"]`, `target-version = "py312"`, `[tool.ruff.pydocstyle] convention = "restructuredtext"` (enforces FR-010 RST docstrings at lint time); `[tool.black]` with `target-version = ["py312"]` — `pyproject.toml`
- [X] T005 Create test/ subdirectory tree: `test/unit/` and `test/integration/` with `__init__.py` in each; create `test/conftest.py` with shared fixtures (mock DB sessions, test secrets loader) — `test/conftest.py`

---

## Phase 2: Foundational

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented. All migrators depend on these modules.

**Independent test criteria**: `connection_factory`, `id_remapper`, and `log_masker` can each be unit-tested in isolation with mocked DB engines and no real DB connection.

- [X] T006 [P] Implement `src/factory/connection_factory.py`: `ConnectionFactory` class with `create_source_engine()` (read-only PostgreSQL engine, `sslmode=disable`) and `create_dest_engine()` (read-write engine); loads credentials exclusively from `.secrets/generate_erd.json` (`host`, `port`, `user`, `password`, `source_db`, `dest_db` keys); raises `ConfigError` if file missing or malformed — `src/factory/connection_factory.py`
- [X] T007 [P] Implement `src/utils/log_masker.py`: `MaskingHandler(logging.Handler)` that overrides `emit()` and applies regex substitutions before writing to StreamHandler or FileHandler; `SENSITIVE_COLUMNS` dict per entity (contacts: name/email/phone_number/identifier/additional_attributes; users: name/email/phone_number; conversations: additional_attributes/meta; messages: content/content_attributes; accounts: name); regex patterns: email `[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}`, BR phone `(\+55)?\s*\(?\d{2}\)?\s*\d{4,5}[\-\s]?\d{4}`, name fields (column-targeted); JSONB field values masked recursively — `src/utils/log_masker.py`
- [X] T008 [P] Implement `src/utils/id_remapper.py`: `IDRemapper` class with `compute_offsets(dest_engine, table_names: list[str]) -> dict[str, int]` (executes `SELECT MAX(id)` on each table, returns 0 if table empty); `remap(id_origem: int, table: str) -> int` that returns `id_origem + offsets[table]`; offsets stored as instance attribute (session-scoped, computed once) — `src/utils/id_remapper.py`
- [X] T009 [P] Implement `src/repository/base_repository.py`: `BaseRepository` with `bulk_insert(conn, table: Table, records: list[dict]) -> int` using SQLAlchemy Core `insert(table)` with explicit values; wraps in transaction per call; returns count of inserted rows; re-raises on unexpected error — `src/repository/base_repository.py`
- [X] T010 Implement `src/repository/migration_state_repository.py`: `MigrationStateRepository` with `create_table_if_not_exists(engine)` (DDL: `migration_state` with columns `id BIGSERIAL PK`, `tabela VARCHAR(100) NOT NULL`, `id_origem BIGINT NOT NULL`, `id_destino BIGINT`, `status VARCHAR(20) NOT NULL DEFAULT 'ok'`, `migrated_at TIMESTAMP NOT NULL DEFAULT NOW()`, `UNIQUE(tabela, id_origem)`, index on `tabela`); `get_migrated_ids(conn, tabela: str) -> set[int]` (returns set of `id_origem` where `status='ok'`); `record_success(conn, tabela: str, id_origem: int, id_destino: int)`; `record_failure(conn, tabela: str, id_origem: int, reason: str)` — `src/repository/migration_state_repository.py`
- [X] T011 Implement `src/migrators/base_migrator.py`: abstract `BaseMigrator` with `__init__(source_engine, dest_engine, id_remapper: IDRemapper, state_repo: MigrationStateRepository, logger: logging.Logger)`; abstract method `migrate() -> MigrationResult`; shared `_run_batches(source_rows: list[dict], table_name: str, dest_table: Table, remap_fn: Callable) -> MigrationResult` that: (1) filters out already-migrated IDs via `state_repo.get_migrated_ids`, (2) splits into batches of 500, (3) remaps IDs, (4) bulk-inserts within transaction, (5) records success/failure per record, (6) continues on batch failure; `MigrationResult` dataclass: `table`, `total_source`, `migrated`, `skipped`, `failed_ids: list[int]` — `src/migrators/base_migrator.py`
- [X] T012 [P] Implement `test/unit/test_connection_factory.py`: test that `create_source_engine()` raises `ConfigError` if `.secrets/` file missing; test engine URL contains correct DB; test that `sslmode=disable` is set; mock file I/O — `test/unit/test_connection_factory.py`
- [X] T013 [P] Implement `test/unit/test_id_remapper.py`: test `compute_offsets` returns 0 for empty table; test `remap` applies `id + offset` correctly; test offsets are session-constant (calling `compute_offsets` twice returns same dict); mock dest engine — `test/unit/test_id_remapper.py`
- [X] T014 [P] Implement `test/unit/test_log_masker.py`: test email address is replaced with `***` in log output; test phone number is masked; test JSONB value containing email is masked recursively; test that record `id` (integer) is NOT masked; test that masking applies to both stdout and file handler — `test/unit/test_log_masker.py`

---

## Phase 3: User Story 1 — Executar Migração Completa de Dados (P1)

**Story goal**: `python src/migrar.py` migrates all 418.828 records from `chatwoot_dev1_db` to `chatwoot004_dev1_db` with ID remapping, FK integrity, masking, and a final validation report.

**Independent test criteria**: Run `python src/migrar.py --dry-run` against copies of both DBs; verify counts match origin totals and zero FK violations in destination. Unit tests use mocked DB sessions — no live DB required.

**Acceptance scenarios covered**: US1 §SC-1 (38.868 contacts → destination), §SC-2 (FK valid after contacts), §SC-3 (FK valid after messages), §SC-4 (report by table), §SC-5 (no PII in any output).

- [X] T015 [P] [US1] Implement `src/migrators/accounts_migrator.py`: extends `BaseMigrator`; `migrate()` reads all accounts from source (id, name, created_at, updated_at + all columns); remaps `id` to `id + offsets['accounts']`; bulk-inserts to destination; on batch failure exits with code 3 (catastrophic — accounts is root entity); records all successful IDs in `migration_state` — `src/migrators/accounts_migrator.py`
- [X] T016 [P] [US1] Implement `src/migrators/inboxes_migrator.py`: extends `BaseMigrator`; remaps `id` (offset_inboxes) and `account_id` (offset_accounts); skips+logs records with orphan `account_id` — `src/migrators/inboxes_migrator.py`
- [X] T017 [P] [US1] Implement `src/migrators/users_migrator.py`: extends `BaseMigrator`; remaps `id` (offset_users); handles `users` table and `account_users` join table migration in same transaction; detects UNIQUE email collision via pre-check and applies suffix `+migrated` to email local-part before insert (e.g., `user@x.com` → `user+migrated@x.com`) — `src/migrators/users_migrator.py`
- [X] T018 [P] [US1] Implement `src/migrators/teams_migrator.py`: extends `BaseMigrator`; remaps `id` (offset_teams) and `account_id` (offset_accounts) — `src/migrators/teams_migrator.py`
- [X] T019 [P] [US1] Implement `src/migrators/labels_migrator.py`: extends `BaseMigrator`; remaps `id` (offset_labels) and `account_id` (offset_accounts) — `src/migrators/labels_migrator.py`
- [X] T020 [US1] Implement `src/migrators/contacts_migrator.py`: extends `BaseMigrator`; remaps `id` (offset_contacts) and `account_id` (offset_accounts); applies masking to `name`, `email`, `phone_number`, `identifier`, `additional_attributes` (JSONB) in log output only — values inserted to DB are originals; batches of 500; ~79 batches for 38.868 records — `src/migrators/contacts_migrator.py`
- [X] T021 [US1] Implement `src/migrators/conversations_migrator.py`: extends `BaseMigrator`; remaps `id` (offset_conversations), `account_id`, `inbox_id`, `contact_id` (nullable: skip+log record if source `contact_id` not in migrated set), `assignee_id` (nullable: NULL-out if not migrated), `team_id` (nullable: NULL-out if not migrated); masks `meta` and `additional_attributes` in log — `src/migrators/conversations_migrator.py`
- [X] T022 [US1] Implement `src/migrators/messages_migrator.py`: extends `BaseMigrator`; remaps `id` (offset_messages), `account_id`, `conversation_id` (nullable: skip+log if not migrated), `sender_id` (nullable: NULL-out if not migrated); masks `content` and `content_attributes` in log; largest entity (~621 batches for 310.155 records) — `src/migrators/messages_migrator.py`
- [X] T023 [US1] Implement `src/migrators/attachments_migrator.py`: extends `BaseMigrator`; remaps `id` (offset_attachments), `message_id`, `account_id`; copies `external_url` as-is (S3 reference only — NO file movement); skips+logs records with orphan `message_id` — `src/migrators/attachments_migrator.py`
- [X] T024 [US1] Implement `src/migrar.py`: CLI entrypoint using `argparse`; flags: `--dry-run` (skip all writes), `--only-table <name>` (single table, respects FK order check), `--verbose` (set log level DEBUG); flow: (1) record `start_time = time.time()`; load credentials via `ConnectionFactory`, (2) create `MigrationStateRepository` and `create_table_if_not_exists`, (3) compute offsets via `IDRemapper.compute_offsets`, (4) setup `MaskingHandler` on root logger + file handler to `.tmp/migration_YYYYMMDD_HHMMSS.log`, (5) run migrators in FK order: accounts→inboxes→users→teams→labels→contacts→conversations→messages→attachments, (6) compute `elapsed = time.time() - start_time`; call `ValidationReporter.generate(results, dest_engine, elapsed)` and log report path at INFO, (7) call `FKValidator.validate(dest_engine)` and log orphan summary at INFO, (8) exit with code per result — `src/migrar.py`
- [X] T025 [P] [US1] Implement `test/unit/test_accounts_migrator.py`: test batch-of-500 splitting; test offset applied to `id`; test exit code 3 raised on catastrophic failure; mock `BaseRepository.bulk_insert` and `MigrationStateRepository` — `test/unit/test_accounts_migrator.py`
- [X] T026 [P] [US1] Implement `test/unit/test_inboxes_migrator.py`: test `account_id` remapped; test orphan `account_id` produces skip (record not inserted) and log entry — `test/unit/test_inboxes_migrator.py`
- [X] T027 [P] [US1] Implement `test/unit/test_users_migrator.py`: test email collision detection triggers `+migrated` suffix; test `account_users` join table entries are created for migrated users; test `phone_number` masked in log — `test/unit/test_users_migrator.py`
- [X] T028 [P] [US1] Implement `test/unit/test_teams_migrator.py`: test `account_id` remapped; test batch count correct for small volume (3 records = 1 batch) — `test/unit/test_teams_migrator.py`
- [X] T029 [P] [US1] Implement `test/unit/test_labels_migrator.py`: test `account_id` remapped; test all 32 source records fit in 1 batch — `test/unit/test_labels_migrator.py`
- [X] T030 [P] [US1] Implement `test/unit/test_contacts_migrator.py`: test `account_id` remapped; test `name`/`email`/`phone_number` masked in log but NOT altered in DB payload; test 38.868 records produce ceil(38868/500)=78 batches — `test/unit/test_contacts_migrator.py`
- [X] T031 [P] [US1] Implement `test/unit/test_conversations_migrator.py`: test NULL `contact_id` → record skipped with log; test `assignee_id` NULL-outed when user not migrated; test `meta` JSONB masked in log; test FK remapping for all 5 FK columns — `test/unit/test_conversations_migrator.py`
- [X] T032 [P] [US1] Implement `test/unit/test_messages_migrator.py`: test `content` masked in log; test orphan `conversation_id` → skip+log; test `sender_id` NULL-outed when not migrated; test FK remapping — `test/unit/test_messages_migrator.py`
- [X] T033 [P] [US1] Implement `test/unit/test_attachments_migrator.py`: test `external_url` copied verbatim (not modified); test orphan `message_id` → skip+log; test no S3 API calls are made — `test/unit/test_attachments_migrator.py`

---

## Phase 4: User Story 2 — Re-execução Segura / Idempotência (P2)

**Story goal**: Re-running `python src/migrar.py` after a partial failure migrates only remaining records; already-migrated records are never duplicated.

**Independent test criteria**: Populate `migration_state` with 20.000 already-migrated contact IDs; re-run contacts migration; verify destination count unchanged and no duplicate IDs in destination.

**Acceptance scenarios covered**: US2 §SC-1 (20k contacts pre-existing → 0 duplicate inserts), §SC-2 (resume from FK violation at id=99), §SC-3 (0 new records → "0 novos a migrar").

- [X] T034 [US2] Implement `test/unit/test_migration_state_repository.py`: test `create_table_if_not_exists` is idempotent (safe to call twice); test `get_migrated_ids` returns correct set; test `record_success` inserts with status='ok'; test `record_failure` inserts with status='failed'; test `UNIQUE(tabela, id_origem)` prevents duplicate inserts; test filtering: batch of [1,2,3] with {2} already migrated → [1,3] — `test/unit/test_migration_state_repository.py`
- [X] T035 [US2] Implement `test/unit/test_base_migrator.py`: test `_run_batches` skips records whose `id_origem` is in `get_migrated_ids`; test partial batch failure records `failed` status for failed IDs and continues with next batch; test `MigrationResult.migrated` + `MigrationResult.skipped` = total_source when re-running with 0 new records — `test/unit/test_base_migrator.py`
- [X] T036 [US2] Implement `test/integration/test_migration_flow.py`: using mocked SQLAlchemy connection fixtures backed by an in-process PostgreSQL-compatible engine (no SQLite — `UNIQUE(tabela, id_origem)` and `BIGSERIAL` must be PostgreSQL-compatible; use `pytest-pgsql` or `sqlalchemy_utils` + test schema, or `unittest.mock.patch` at SQLAlchemy `execute` level preserving constraint semantics); simulate: (1) run migration for 1.000 contacts stopped after 500 (interrupt via mock), (2) verify 500 records in destination and migration_state, (3) re-run full migration, (4) verify destination has exactly 1.000 contacts (no duplicates) and migration_state has 1.000 'ok' records — `test/integration/test_migration_flow.py`

---

## Phase 5: User Story 3 — Consulta ao Relatório de Validação (P3)

**Story goal**: After migration, `ValidationReporter.generate()` produces a file at `.tmp/migration_YYYYMMDD_HHMMSS_report.txt` with per-table counts and failed IDs (no content), all through the masking pipeline.

**Independent test criteria**: Call `ValidationReporter.generate()` with a mock `MigrationResult` list; verify report file contains all 9 tables with correct counts and no PII.

**Acceptance scenarios covered**: US3 §SC-1 (report with 5 columns per table), §SC-2 (FK violation IDs listed without content), §SC-3 (no PII in saved file).

- [X] T037 [US3] Implement `src/reports/validation_reporter.py`: `ValidationReporter` class with `generate(results: list[MigrationResult], dest_engine, duration_seconds: float) -> Path`; queries destination for `COUNT(id)` per table to compute `destino_total`; formats the ASCII table header (`TABELA | ORIGEM | MIGRADO | DESTINO_TOTAL | FALHAS`); includes `duration_seconds` in report header (supports SC-007 auditability); appends failed IDs list (IDs only, no content) for each table; saves to `.tmp/migration_YYYYMMDD_HHMMSS_report.txt` (creates `.tmp/` if absent); all output through `MaskingHandler` — `src/reports/validation_reporter.py`
- [X] T039 [P] [US3] Implement `test/unit/test_validation_reporter.py`: test report contains all 9 table rows; test failed IDs appear as integers (no content); test file path format matches `migration_YYYYMMDD_HHMMSS_report.txt`; test any PII-containing MigrationResult produces masked output in report file; test `reporter.generate()` with mocked inputs completes in < 5 seconds (proxy for SC-007 ≤0s runtime); mock `MigrationResult` and dest engine — `test/unit/test_validation_reporter.py`

---

## Final Phase: Polish & Cross-Cutting Concerns

**Purpose**: FK post-validation, linting gates, coverage enforcement

- [X] T040 [P] Implement `src/utils/fk_validator.py`: `FKValidator` with `validate(dest_engine) -> ValidationReport`; runs SQL `SELECT COUNT(*) FROM child_table WHERE fk_col IS NOT NULL AND fk_col NOT IN (SELECT id FROM parent_table)` for each FK relationship (9 relationships per data-model.md FK graph); returns `ValidationReport` with per-relationship orphan counts — `src/utils/fk_validator.py`
- [X] T041 [P] Implement `test/unit/test_fk_validator.py`: test FK check returns 0 orphans for clean destination; test FK check correctly detects injected orphan; mock dest engine with controlled fixture data — `test/unit/test_fk_validator.py`
- [X] T042 [P] Run `uv run ruff check src/ test/` and fix all violations across all implemented modules — all `src/*.py` and `test/**/*.py`
- [X] T043 [P] Run `uv run black --check src/ test/` and apply `uv run black src/ test/` to fix all formatting — all `src/*.py` and `test/**/*.py`
- [X] T044 Run `uv run pytest --cov=src --cov-report=term-missing --fail-under=90` and verify ≥90% line coverage on: `id_remapper`, `log_masker`, `fk_validator`, `connection_factory`, all 9 `*_migrator` modules; add missing test cases if any module is below threshold — `test/`
- [X] T045 [P] Run `uv run ruff check --select D src/` and fix all missing RST docstring violations (FR-010); verify every public function has `:param:`, `:type:`, `:returns:`, `:rtype:`, `:raises:` sections; verify functions identified as critical (`id_remapper`, `log_masker`, `fk_validator`, each `BaseMigrator._run_batches`) have executable `doctest` blocks — all `src/**/*.py`

---

## Phase POC: Dry-Run de Classificação (Pré-Migração de Produção)

**Purpose**: Executar o código de migração em modo classificatório — sem escrita — para mapear
todas as ocorrências antecipadamente antes da migração de produção.

**Independent test criteria**: Run `python src/migrar.py --dry-run --poc` with mocked engines;
verify `POCResult` classifications cover every source record and report is generated with no DB writes.

**Acceptance scenarios covered**: US4 §SC-1 (all 38.868 contacts classified without INSERT),
§SC-2 (report at `.tmp/poc_*_report.txt` with 9 tables + samples), §SC-3 (ORPHAN_FK_SKIP
sampled), §SC-4 (no PII in report).

- [x] TPOC001 Implement `src/reports/poc_reporter.py`: `Outcome` enum (`WOULD_MIGRATE`, `WOULD_MIGRATE_MODIFIED`, `ORPHAN_FK_SKIP`, `ALREADY_MIGRATED`, `COLLISION`); `RecordSample` dataclass (`id_origem`, `outcome`, `reason`, `masked_preview: dict`); `POCResult` dataclass (`table`, `total_source`, `outcome_counts: dict`, `samples: dict`; `add_record(sample)` caps at `MAX_SAMPLES=10` per outcome); `POCReporter.generate(results: list[POCResult], duration_seconds: float) -> Path` writes summary table + samples section to `.tmp/poc_YYYYMMDD_HHMMSS_report.txt` — `src/reports/poc_reporter.py`
- [x] TPOC002 Add `poc_classify(already_migrated: set[int], migrated_sets: dict[str, set[int]]) -> POCResult` to `BaseMigrator`: abstract hooks `_table_name()` + `_fetch_all_source_rows()`; concrete loop + `_classify_row_poc()` default (WOULD_MIGRATE) + `_poc_safe_preview()`; all 9 concrete migrators implement hooks + override `_classify_row_poc` with FK-specific rules; no INSERT/UPDATE/DDL — `src/migrators/base_migrator.py` + all 9 migrators
- [x] TPOC003 Add `--poc` flag to `src/migrar.py`: when `--dry-run --poc`, calls `poc_classify()` on each migrator in FK order using source read-only connections and no state table creation; collects `POCResult`s; calls `POCReporter.generate()` and logs report path at INFO; exits with code 0 on success — `src/migrar.py`
- [x] TPOC004 Execute POC against real DBs: run `python src/migrar.py --dry-run --poc`; verify `.tmp/poc_*_report.txt` generated; verify all 9 tables appear with classification counts; review and document unexpected patterns — (execution task, no source changes)
- [x] TPOC005 [P] Implement `test/unit/test_poc_reporter.py`: test all 5 `Outcome` values appear in report; test `add_record()` caps at 10 samples per outcome; test `generate()` report path matches `poc_YYYYMMDD_HHMMSS_report.txt`; test sensitive data in `masked_preview` produces masked output; test `generate()` with empty results produces valid file — `test/unit/test_poc_reporter.py`

---

## Dependency Graph

```
Phase 1 (Setup) → Phase 2 (Foundational) → Phase 3 (US1) → Phase 4 (US2) → Phase 5 (US3) → Final → Phase POC
```

**User Story completion order** (by priority and dependency):

| Order | Story | Depends On | Can Start After |
|-------|-------|------------|-----------------|
| 1 | US1 — Migração Completa | Phase 2 Foundation complete | T011 done |
| 2 | US2 — Idempotência | US1 base infrastructure exists | T011 done (T036 uses mocks — does not require T024) |
| 3 | US3 — Relatório | US1 MigrationResult produced | T024 done |

**Parallel execution per story (US1)**:

```
T011 done →
  ├─[parallel]─ T015 accounts_migrator
  ├─[parallel]─ T016 inboxes_migrator
  ├─[parallel]─ T017 users_migrator
  ├─[parallel]─ T018 teams_migrator
  └─[parallel]─ T019 labels_migrator
        ↓ all done →
  T020 contacts_migrator
        ↓
  T021 conversations_migrator
        ↓
  T022 messages_migrator
        ↓
  T023 attachments_migrator
        ↓
  T024 migrar.py (orchestrator)
```

**Parallel execution per story (tests)**:

All test files in T025–T033 are independent and can be written in full parallel once their corresponding migrator file (T015–T023) exists.

---

## Implementation Strategy

### MVP Scope: User Story 1 only (T001–T033)

Delivers the core migration. Phase 2 Foundational tasks take ~2–3 hours. US1 migrators can be parallelized in 2 batches (T015–T019 in parallel, then T020–T024 sequential). US1 tests can be written in parallel with migrators.

**MVP delivery**: `python src/migrar.py --dry-run` passes without errors; full run migrates all 418.828 records.

### Incremental delivery:

1. **Sprint 1** (MVP): T001–T033 → US1 working end-to-end
2. **Sprint 2**: T034–T036 → US2 idempotency proven by integration test
3. **Sprint 3**: T037, T039 → US3 report generation (T038 removed — integrated into T024 step 6)
4. **Sprint 4**: T040–T044 → Polish, 90% coverage gate confirmed
5. **Sprint POC** (pré-produção): TPOC001–TPOC005 → POC report validates all migration occurrences before production run

---

## Summary

| Metric | Value |
|--------|-------|
| Total tasks | 49 |
| Phase 1 — Setup | 5 tasks |
| Phase 2 — Foundational | 9 tasks |
| Phase 3 — US1 (Migração Completa) | 20 tasks |
| Phase 4 — US2 (Idempotência) | 3 tasks |
| Phase 5 — US3 (Relatório) | 2 tasks (T038 removed — duplicate of T024 step 6) |
| Final — Polish | 5 tasks (T040–T044 + T045 docstrings) |
| Phase POC — Dry-Run POC | 5 tasks (TPOC001–TPOC005) |
| Parallelizable tasks [P] | 31 tasks |
| US1 tasks | 20 tasks |
| US2 tasks | 3 tasks |
| US3 tasks | 2 tasks |
| US4 tasks | 5 tasks |
| MVP scope (US1 only) | T001–T033 (33 tasks) |
