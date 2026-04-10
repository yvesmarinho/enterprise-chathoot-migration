# Release Gate Checklist: Enterprise Chatwoot Migration

**Purpose**: Validate requirements completeness, clarity, consistency, and measurability across all domains before release — data integrity, security, idempotency, quality contracts, operational NFRs
**Created**: 2026-04-10
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md) | [data-model.md](../data-model.md) | [cli-contract.md](../contracts/cli-contract.md)
**Timing**: Release gate — last checkpoint before deployment to production
**Depth**: Thorough (all domains, all scenario classes)

---

## Requirement Completeness

- [ ] CHK001 — Are connection mode requirements (`read-only` vs `read-write`) specified for both databases, including what happens if `chatwoot_dev_db` is accidentally opened in write mode? [Completeness, Spec §FR-001]
- [ ] CHK002 — Are credential loading requirements complete: is the exact path and format of `.secrets/generate_erd.json` documented, including required fields and schema? [Completeness, Spec §FR-001]
- [ ] CHK003 — Are offset calculation requirements specified for every one of the 9 entities individually, or only generically? Does the spec cover entities without a `max(id)` in the destination (zero records)? [Completeness, Spec §FR-002]
- [ ] CHK004 — Is the FK migration order for `users` fully specified? The data model shows `users.account_id` is managed via an `account_users` join table — are requirements for this join table's migration documented? [Completeness, Spec §FR-003, Data Model §3]
- [ ] CHK005 — Are requirements defined for all FK fields in `conversations` (`account_id`, `inbox_id`, `contact_id`, `assignee_id`, `team_id`)? Are nullable FK remapping rules explicitly stated for NULLABLE FKs? [Completeness, Spec §FR-003, Data Model §7]
- [ ] CHK006 — Are requirements defined for `messages.sender_id` (FK → users.id, NULLABLE) and `messages.conversation_id` (NULLABLE) remapping? [Completeness, Data Model §8]
- [ ] CHK007 — Are JSONB field requirements defined for `contacts.additional_attributes`, `conversations.meta`, `conversations.additional_attributes`, and `messages.content_attributes`? Is masking of sensitive data nested inside JSONB explicitly required? [Completeness, Spec §FR-006, Data Model §6-8]
- [ ] CHK008 — Are requirements for the `--dry-run` flag complete: does the spec define exactly what output is produced, what is NOT written, and what the exit code should be? [Completeness, CLI Contract]
- [ ] CHK009 — Are requirements for `--only-table` flag complete: is the behavior when the specified table has unresolved FK dependencies (upstream tables not yet migrated) explicitly defined? [Completeness, CLI Contract]
- [ ] CHK010 — Are `migration_state` table creation requirements complete? Is DDL or schema of all 5 columns (`tabela`, `id_origem`, `id_destino`, `status`, `migrated_at`) formally specified, including data types and indexes? [Completeness, Spec §FR-005]

---

## Requirement Clarity

- [ ] CHK011 — Is "offset calculado uma única vez por sessão" precisely defined? Does "sessão" mean process lifetime, or script invocation? Is it clear what happens if the script is interrupted mid-run and restarted? [Clarity, Spec §FR-002]
- [ ] CHK012 — Is "falha em um batch registra os IDs afetados e continua com o próximo" sufficiently clear? Does "continua" mean the next batch of the same table, or the next table? [Clarity, Spec §FR-003]
- [ ] CHK013 — Is "migrar apenas as referências (URLs) de attachments S3" unambiguous? Are the specific column names in the `attachments` table that contain S3 URLs identified? [Clarity, Spec §FR-004, Data Model]
- [ ] CHK014 — Is the `users.email` collision strategy "sufixo `_migrated` ou prefixo de domínio" specified as a definitive choice, or is it still an option? The use of "ou" (or) in data-model.md suggests this remains undecided. [Ambiguity, Data Model §3]
- [ ] CHK015 — Is "dados sensíveis" defined with an exhaustive enumeration? Are column-level masking rules specified per entity (e.g., `contacts.identifier`, JSONB sub-fields) or only at a categorical level? [Clarity, Spec §FR-006]
- [ ] CHK016 — Is "confirmação explícita do operador" (for missing backup case) defined? Is it an interactive prompt, an env variable flag, or a CLI argument? [Ambiguity, Spec Edge Cases]
- [ ] CHK017 — Is "falha catastrófica" (exit code 3) precisely bounded? Is there a documented threshold distinguishing a catastrophic failure (FK violation in `accounts`) from a non-catastrophic one (FK violation in `messages`)? [Clarity, CLI Contract §Exit Codes]
- [ ] CHK018 — Is the output timestamp format `[TIMESTAMP]` specified with a concrete pattern (e.g., ISO 8601, `YYYY-MM-DD HH:MM:SS`)? Is timezone handling defined? [Clarity, CLI Contract §Output Schema]

---

## Requirement Consistency

- [ ] CHK019 — Are FK order requirements in `spec.md` (`accounts → inboxes → users → teams → labels → contacts → conversations → messages → attachments`) consistent with the FK graph in `data-model.md`? Is there a documented validation that this order is topologically correct given all cross-entity FK dependencies? [Consistency, Spec §FR-003, Data Model]
- [ ] CHK020 — Is the batch size of 500 records consistent across all 9 migrators? Are there any entities where a different batch size is implied (e.g., `messages` at ~338k records)? [Consistency, Spec §FR-003]
- [ ] CHK021 — Are masking requirements consistent between stdout output and the file log? The spec states "ambas as saídas passam pelo mesmo pipeline de mascaramento" — is this consistency requirement formally written as a testable requirement, not just an implementation note? [Consistency, Spec §FR-006]
- [ ] CHK022 — Are the exit codes in `cli-contract.md` consistent with the error scenarios described in `spec.md` Edge Cases? Specifically, is the "backup não existir" scenario mapped to an exit code? [Consistency, Spec Edge Cases, CLI Contract §Exit Codes]
- [ ] CHK023 — Do coverage requirements in FR-012 (`id_remapper`, `log_masker`, `fk_validator`, `connection_factory`, each `Migrator`) cover all the modules listed in the plan's `src/` structure? Is `validation_reporter.py` included in the 90% coverage gate? [Consistency, Spec §FR-012, Plan §Project Structure]

---

## Acceptance Criteria Measurability

- [ ] CHK024 — Can FR-002's offset correctness be objectively verified? Is there a defined acceptance criterion that validates `novo_id = id_origem + offset` for every record, not just a sample? [Measurability, Spec §FR-002]
- [ ] CHK025 — Is the "zero FK violations" acceptance criterion in User Story 1 measurable post-migration via a specific SQL query or validation script? Is `fk_validator.py` the defined mechanism, and is its own correctness in scope? [Measurability, Spec US-1 §SC-2,3]
- [ ] CHK026 — Is the "< 2 hours" performance goal in `plan.md` a hard acceptance criterion or an estimate? Is there a defined SLO and what happens if migration exceeds it? [Measurability, Plan §Performance Goals]
- [ ] CHK027 — Is the acceptance criterion for idempotency (US-2) measurable without manual intervention? Is there a concrete test definition (record counts before/after) formally specified? [Measurability, Spec §US-2]
- [ ] CHK028 — Is the "90% line coverage" criterion bounded to specific modules, or is it a project-wide threshold? Is `--fail-under=90` the defined command, and does the spec identify the exact pytest configuration file? [Measurability, Spec §FR-012]

---

## Scenario Coverage

- [ ] CHK029 — Are requirements defined for the concurrent execution scenario: what happens if two instances of `python src/migrar.py` are run simultaneously against the same destination? [Coverage, Gap]
- [ ] CHK030 — Are requirements defined for the partial-table scenario: `--only-table contacts` when `accounts` was never migrated? Is the expected behavior (abort, warn, proceed) specified? [Coverage, CLI Contract]
- [ ] CHK031 — Are requirements for the "source grows during migration" scenario defined? If `chatwoot_dev_db` receives new records while migration is running, are those records in scope for the current session? [Coverage, Gap]
- [ ] CHK032 — Are recovery requirements defined after exit code 3 (catastrophic failure)? Is the exact sequence of manual steps (restore backup → re-run) formally documented as part of the operational requirements, not just as a comment in edge cases? [Coverage, Exception Flow, Spec §Edge Cases]
- [ ] CHK033 — Are requirements specified for what happens when `migration_state` table exists but has corrupted or inconsistent data (e.g., `id_origem` exists but `id_destino` is NULL)? [Coverage, Edge Case, Gap]
- [ ] CHK034 — Are requirements defined for the zero-records scenario: what does the script output and what is the exit code when `chatwoot_dev_db` has 0 records in a given table? [Coverage, Edge Case]
- [ ] CHK035 — Are requirements specified for FK violations that span entity boundaries (e.g., `messages.sender_id` referencing a `user` that failed migration)? Is cascading-failure behavior defined? [Coverage, Exception Flow, Gap]

---

## Security & Privacy Requirements

- [ ] CHK036 — Is the masking scope for JSONB columns (`contacts.additional_attributes`, `conversations.meta`, `messages.content_attributes`) explicitly specified? Are masking rules defined for dynamically keyed JSON sub-fields, not just flat columns? [Completeness, Spec §FR-006]
- [ ] CHK037 — Are credentials security requirements complete: is it documented that `.secrets/generate_erd.json` must never appear in logs, stack traces, or error messages (even partially, e.g., hostname)? [Completeness, Spec §FR-001, FR-006]
- [ ] CHK038 — Is the masking strategy (redaction, hashing, tokenization) formally defined per data category? "Mascaramento" is used but the technique is unspecified — would `***` or a SHA256 hash satisfy the requirement? [Clarity, Spec §FR-006, Ambiguity]
- [ ] CHK039 — Are security requirements defined for the log file at `.tmp/migration_YYYYMMDD_HHMMSS.log`? Is file permissions mode (e.g., `600`) and retention policy specified? [Coverage, Gap]
- [ ] CHK040 — Are requirements specified for what happens if the masking pipeline itself fails (exception in `log_masker.py`)? Should the script abort, or continue with unmasked output? [Coverage, Exception Flow, Gap]

---

## Idempotency & Resilience Requirements

- [ ] CHK041 — Are idempotency requirements defined at the batch level or the record level? If a 500-record batch is partially committed (3 records inserted, then connection dies), does idempotency apply to those 3 records on re-run? [Clarity, Spec §FR-005]
- [ ] CHK042 — Are requirements specified for `migration_state.status` values? Is the set of valid statuses (e.g., `migrated`, `skipped`, `failed`) formally enumerated in the spec? [Completeness, Spec §FR-005, Gap]
- [ ] CHK043 — Is the backup-check requirement (before first write) formally part of FR requirements, or only mentioned in Edge Cases? Is this check a hard gate (abort if no backup signal) or a soft warning? [Completeness, Spec §Edge Cases, Gap]
- [ ] CHK044 — Are resilience requirements defined for transient DB errors during migration (connection timeout, lock wait timeout)? Is retry logic in scope, and if so, are retry limits and backoff strategy specified? [Coverage, Gap]

---

## Quality Contract Requirements

- [ ] CHK045 — Is the docstring requirement (FR-010) defined with a minimum completeness bar? Is "toda função pública" qualified to exclude `__init__` or private helpers? [Clarity, Spec §FR-010]
- [ ] CHK046 — Are "funções críticas DEVEM ter doctest executável" (FR-010) requirements complete: is "críticas" formally defined, or is it left to developer judgment? [Clarity, Spec §FR-010, Ambiguity]
- [ ] CHK047 — Is the linting gate (FR-011) part of CI or only a pre-commit convention? Is there a defined mechanism (Makefile target, pre-commit hook, GitHub Actions) that enforces it before merge? [Completeness, Spec §FR-011]
- [ ] CHK048 — Are test isolation requirements defined? Do unit tests require mocked DB connections, or are integration tests against live DBs acceptable? [Completeness, Spec §FR-012, Gap]

---

## Dependencies & Open Items

- [ ] CHK049 — Is open item D2 ("destino final de `chatwoot_dev_db` pós-migração") formally tracked with an owner, due date, and impact on current requirements? If unresolved at release, is there a documented risk acceptance? [Dependency, Ambiguity, Checklist §requirements.md]
- [ ] CHK050 — Are all external dependencies (`chatwoot_dev_db` schema, PostgreSQL 16.10, `.secrets/generate_erd.json` format) formally documented as assumptions with a schema version pin? Is Schema SHA1 `da6b4a36...` the release baseline? [Dependency, Data Model]
- [ ] CHK051 — Is the `account_users` join table dependency formally documented in FR-003 or data-model.md? Its existence is implied in Data Model §3 but not listed in the 9 migrated entities. [Dependency, Gap, Data Model §3]

---

## Notes

- Release gate scope: All items must be resolved (checked or explicitly accepted as known risk) before `speckit.implement` begins.
- Open item D2 (CHK049) is the only known pre-existing risk accepted by owner.
- Items marked `[Gap]` represent missing requirements that MUST be added to spec.md or plan.md before implementation.
- Items marked `[Ambiguity]` require a clarification decision to be encoded into spec.md.
