# BonusReport — Next Session Brief

**Last session:** 2026-05-05 (Phase 7 foundation)
**Next session opens with:** Engine wiring (test fixtures + adapter + runner)

---

## Where we are right now

### Schema state (deployed, verified)

All migrations through `Phase7prep_v2_extension_patch2.sql` are deployed on Railway Postgres. The data model is now agreement-based with priority Group → List → Institution structure:

```
ref_institution_agreement  (124 rows: 28 VIA_PARTNER + 96 DIRECT, all dated 2023-01-01 to 2026-12-31)
    ↓
ref_partner_classification (27 rows: 18 GROUP + 7 MA-OOS + 2 MA-GENUINE; kpi_weight, bonus_model)
ref_partner_flat_rate      (12 rows: ApplyBoard + Can-Achieve × 3 offices × 2 roles)

ref_priority_group         (32 rows: Navitas + ENZ + 30 standalone Groups)
    ↓
ref_priority_list          (38 rows; renamed from ref_priority_partner)
    ↓
ref_priority_list_institution (45 rows; junction with bonus_pct_override + weight_override + institution_target_*)
    ↓
ref_priority_target        (76 rows: 38 for 2024 with real bonus_pct, 38 for 2025 at 0%)
```

Key schema facts:

- `ref_institution.classification` was DROPPED. In-system / out-of-system status is derived from active agreements at the case date.
- `ref_partner` has effective_from/effective_to (StudyLink ↔ partner relationship dates).
- `ref_institution_agreement` has agreement_type ('DIRECT' or 'VIA_PARTNER'), nullable partner_id, kpi_weight, effective dates.
- `ref_priority_list_institution` has the override columns for promotional and carve-out treatment.
- Griffith College is one institution (id=130). Brisbane (id=310) was merged in via patch2; it's in the aggregate's no-longer state.

### Code state

**Importer (production-ready):**
- `backend/importer/transformer.py` — pure alias-lookup, no asterisk parsing, agreement-aware System Type cross-check
- `backend/importer/resolvers.py` — alias resolvers; `lookup_partner_institution_links` removed
- Smoke-tested on Lợi April 2025: 7 rows imported, 0 errors, 0 warnings (after backdating agreement effective_from to 2023-01-01)

**Data layer (production-ready):**
- `backend/data/ref_loaders.py` — 22 loaders, 6 new ones for the Phase 7 tables
- `backend/data/reference_data.py` — assembles ReferenceData with all 22 fields
- Smoke-tested: clean assembly, all counts correct

**Engine (code complete, NOT YET EXECUTED):**
- `backend/engine/models.py` — ReferenceData/RunContext renamed and extended
- `backend/engine/calc_priority.py` — full rewrite: junction-walk, carve-out, override-aware
- `backend/engine/calc_tier.py` — agreement-aware fees_paid_non_enrolled check
- All four files compile (syntax checked). The engine has NOT been run against a real case yet — that's task 1 next session.

### Test state

**Tests will fail.** Fixtures use old field names (`priority_partners`, `priority_partner_id`, `enrolments_by_priority_partner_ytd`, `aggregate_priority_partner_id`). Affected files:

- `backend/tests/test_addon.py`
- `backend/tests/test_co_sub_subscheme.py`
- `backend/tests/test_package.py`
- `backend/tests/test_payment_timing.py`
- `backend/tests/test_presales.py`
- `backend/tests/test_priority.py` (most invasive — exercises priority logic specifically)
- `backend/tests/test_e2e_real_data.py`

This is expected and not blocking — fixtures need to catch up to the new model.

---

## Locked decisions (do NOT re-derive)

These were settled in the last session. Don't re-open:

1. **Asterisks in CRM data are aliases, not syntax.** The importer never parses them; it looks up the raw string in `ref_institution_alias`. Currently 32 of 32 asterisk-bearing rows in Lợi's data resolve cleanly via existing aliases.

2. **In-system / out-of-system is derived from agreements**, not stored on the institution. An institution is "in-system" if it has an active agreement at the case date.

3. **Routing partner is NOT recorded on tx_case from institution-name parsing.** The importer reads `Refer Source Agent` column for sub-agent routing. Partner-routing for engine logic is derived from `ref_institution_agreement` at runtime.

4. **Effective dates for backfilled data: 2023-01-01 to 2026-12-31** (institutions, agreements, partner relationships). Priority targets retain their 2024-12-31 expiry per management.

5. **Griffith College is one institution.** Lives at id=130 with canonical name "Griffith College". Single List "Griffith College (Navitas)" has target=2. Aggregate "Other Navitas AU" has 7 members (no GC).

6. **Carve-out semantics:** when a junction row has `institution_target_*` set, that institution's enrolments count toward the per-institution target, not the List-level target. When NULL, enrolments aggregate to the List total.

7. **fees_paid_non_enrolled override fires** when status flag is set AND institution has any active VIA_PARTNER agreement at case date. No distinction between MA and Group routings for this rule.

8. **Override columns on the junction (bonus_pct_override, weight_override)** are first-class machinery. Engine reads them with the override-or-fallback pattern. Used today for static cases (e.g. GC's individual target) and future for promotional periods.

9. **Junction multi-membership rule:** prefer non-aggregate List over aggregate when an institution belongs to multiple Lists at the same case date. Within ties, take deterministic-first.

10. **Country flat rates for "no-agreement" institutions** are NOT a current policy concept. Don't build infrastructure speculatively. When SL formalizes per-country differentiation (Germany / Sweden / Poland / Switzerland), the schema can extend cleanly via either a `country_id` column on `ref_rate` or sub-bucket values.

---

## Backlog — explicit items NOT lost

### Engine wiring (next session, top of list)

1. **Update test fixtures** to new model — 7 files, mostly mechanical renames
2. **Write `backend/engine_runner/adapter.py`** — converts a `tx_case` row from DB into a `CaseInput` dataclass
3. **Write `backend/engine_runner/cli.py`** — orchestrates a month's run: read tx_case rows, run engine, persist tx_bonus_payment + tx_clawback_balance
4. **Run engine end-to-end on Lợi April 2025** — first real test of the new code path; expect to find and fix ≥ 1 bug
5. **Build YTD aggregator** — populates `ctx.enrolments_by_priority_list_ytd` and `ctx.enrolments_by_priority_list_institution_ytd` from prior runs in the year

### Asterisk alias seeder (mechanical, can do anytime)

`/mnt/user-data/outputs/phase7prep_extension/code/seed_asterisk_aliases.py` is written and ready. It mechanically maps the 94 asterisk-decorated CRM strings to canonical institutions. Run with `--dry-run` first, then commit. Not blocking the engine.

### Open policy items (mostly answered, just need engine wiring)

These have answers from management (in `policy_lockbook_DRAFT.md`) but engine logic isn't wired yet:

- **2-for-1 KPI weighting** for Malaysia / Korea / Thailand (Q1.4) — affects KPI counter, not bonus rate
- **Philippines 20+ wk English = 0.5 weight** (Q1.5) — affects KPI counter; sub-20-week English = zero
- **US 2-for-1.4 rule** (Q8.3) — only applies to US out-system master-agent-routed cases
- **US out-system fee < 28M = zero KPI weight** (Q8.7)
- **Doc 2's 1.0 weight scope for Canadian packages** (Q8.4)

None of these block the basic engine wiring. They're enhancements once the engine runs cleanly end-to-end.

### Watch-this-space (forward-looking, no work yet)

- **Per-country granularity** for European countries (Germany, Sweden, Poland, Switzerland) and possibly China. Currently treated as standard target-country tier rates. Management has discussed but not finalized differentiation. When policy lands, the schema extends non-breakingly.
- **Independent out-of-system country flat bonus** — earlier conversation surfaced this as a possible future need, but the policy doesn't define it as a distinct category. If management formalizes it, we need a country × role rate matrix and a new table.

### Known issues / hygiene

- `backend/output/` not in `.gitignore`
- `backend/tools/python commands...` (committed file) should move to `docs/scratch/`
- Legacy test files in `backend/tests/` aren't pytest-runnable
- Railway BonusReport service shows "Build failed" — cosmetic
- 12 unanswered management items in policy_lockbook Appendix C (re-ask)
- Q11.12 vs Q11.14 contradiction on path-change clawback (TENTATIVE)
- VP role description in dim_role says "Vice President" but actually means "Office" (Vietnamese shorthand) — documentation issue, not blocking
- The `staff_id != home_office_id` cases (staff working across offices) aren't fully tested

---

## Outstanding management questions

(Anthropology questions only — not blocking engine work.)

12 items in Appendix C of `policy_lockbook_DRAFT.md` (`/mnt/user-data/outputs/policy_lockbook/`).

If a re-ask happens, useful additions:
- Confirm Q1.6 ruling on sub-20-week English from Thai/Korea/Malay (lockbook: presumed but not explicit)
- Sub-20-week English from China/Japan/Taiwan/HK — same rule? (no current explicit answer)

---

## File locations reference

```
/mnt/user-data/outputs/phase7/
    code/
        data/reference_data.py
        engine/models.py
        engine/calc_priority.py
        engine/calc_tier.py
    sql/
        Phase7prep_v2_extension_patch2.sql

/mnt/user-data/outputs/phase7prep_extension/
    DESIGN.md                          (superseded by deployed migrations)
    Phase7prep_v2_extension.sql        (deployed)
    Phase7prep_v2_extension_patch1.sql (deployed; backdated dates to 2023-01-01)
    code/
        transformer.py                 (in repo)
        resolvers.py                   (in repo)
        seed_asterisk_aliases.py       (ready, not yet run)
        asterisk_institution_strings.txt
        check_alias_coverage.sql

/mnt/user-data/outputs/phase7prep_v2/
    Phase7prep_v2.sql                  (deployed)
    Phase7prep_v2_TX1_rollback.sql     (deployed)
    Phase7prep_v2_TX2_rebuild_schema.sql (deployed)
    Phase7prep_v2_TX3_seed_data.sql    (deployed)
    Phase7prep_v2_patch1.sql           (deployed)

/mnt/user-data/outputs/policy_lockbook/
    policy_lockbook_DRAFT.md
```

Repo state: all production code (transformer, resolvers, ref_loaders, reference_data, models, calc_priority, calc_tier) is in place at:
```
C:\Users\rhod_\Documents\BonusReport\Application\backend\
```

---

## Database connection (carries forward)

```
postgresql://postgres:dGWeGkmkeymwVxPvecZvvrqsywOwoxtq@switchyard.proxy.rlwy.net:16003/railway
```

(Server alias: StudyLinkBonusReport on Railway.)

---

## Conventions to preserve

- Frozen dataclasses, money as int (đồng), percentages as Decimal
- Effective-dating with effective_from/effective_to on all relationship tables
- Loud failures (raise specific exceptions, never silent defaults)
- Audit-friendly (return full row dicts, record in audit_json)
- `dim_*` for dimensions, `ref_*` for reference, `tx_*` for transactional
- Each migration: BEGIN/COMMIT, idempotent, self-verification at end
- One file per replacement (not patch instructions) when delivering code
- pgAdmin for migration runs; verify via verification queries

---

## Suggested first action next session

1. Open this brief, skim it, confirm context
2. Run `pytest backend/tests/ -v` — see how many tests fail. The number tells us scope.
3. Update fixtures starting with `test_priority.py` (most invasive) and working outward.
4. Once tests pass, write the adapter and runner.
5. Run the engine on Lợi April 2025 cases. First-pass output goes to `tx_bonus_payment`. Compare against Lợi's actual báo cáo file to spot regressions.
