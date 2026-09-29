---
name: impact360-sav-runner
description: >-
  Runs the FINDINGS of an advertising-effectiveness (Impact360) survey straight from the raw SPSS .sav file:
  finds the relevant effectiveness questions (also inside an omnibus with other clients' questions), tabulates
  them at three levels — total sample, exposed to at least one medium (Total Exposed), customers / non-customers
  (brand bought in the last 3 months) — computes DESCRIBE + ATTENTION (DESCRIBE#27) and every summary variable
  of the bench dictionary (T2B/TOP/B3B, nets, indices, _E twins) and writes ONE tidy Hebrew-RTL Excel with the
  summary variables at the bottom of each table plus a 5-column DATA sheet ready for impact360-master-import.
  Use whenever someone hands over a .sav (SPSS / Decipher export) of an ad-effectiveness / Impact360 / campaign
  study and asks for the findings, "הרצה", "הרצת ממצאים", "ריצת דאטה", "טבלאות מה-SAV", "תריץ את הקובץ",
  "ממצאים מ-SAV", "חשב את משתני הבנצ'מארק", or wants the bench numbers without a DP crosstab. Not for
  questionnaires-vs-script QA (decipher-questionnaire-checker) or respondent-level deep dives (deep-analyzer).
---

# Impact360 SAV Runner — raw .sav → findings workbook (3 levels) → bench-ready DATA

## What it does (and does not)

Turns `study.sav` into `<Study>_FINDINGS_SAV.xlsx`. It replaces the DP crosstab step for effectiveness
studies and produces exactly what `impact360-master-import` needs (`DATA_לייבוא`). It is **respondent-level**:
nets that cannot be recovered from marginals (NEXT_ACTION max-method, coded-open nets, DESCRIBE worlds,
ATTENTION, Total Exposed union) are computed from the raw rows.

It does **not** compute the KPI indices (APS/BLS/MEI/ARS, I360 …) — those are formulas in the LIVE workbook of
`impact360-master-import` fed by the DATA rows. It never writes to the bench; the researcher verifies and pastes.

## Locked rules (do not relitigate — see `references/rules.md` for the why)

1. **Levels** — `מדגם` (all) · `נחשפים` (Total Exposed = union of the media-exposure questions, validated against the
   DP variable `vctq1c1` when present) · `לקוחות` / `לא לקוחות` (USAGE 3 months, tested-brand row; empty = non-customer).
2. **Only sample-level values and `_E` twins are exported to `DATA_לייבוא`.** Customer / non-customer cuts are analysis
   only (sub-segments the dictionary does not define are never imported).
3. **Bench dictionary is the authority** for VAR_NAME, slots, labels, roles and `Status`. Rows with
   `Status = "Don't import"` (all `#95` means) are shown in the tables but dropped from `DATA_לייבוא`.
4. **Percent scale 0-100; DESCRIBE#21-#27 are mean counts** (not ×100). ATTENTION_100 = #27 ÷ 42 × 100 lives in LIVE.
5. **Base**: question asked of a subset → % of those asked (flagged in the table). Skip-logic *exposure* follow-ups
   (SEMIAEX-VD, SEMIAEX-CAT, UNEXPOSEB, SLOGAN, SPONTIMPRESSION) → `base:"all"` = total sample.
6. **A fuzzy dictionary match is never trusted silently.** `confidence: fuzzy-*` blocks are tabulated as analysis-only
   (no `united` code) until the mapping says `"confirmed": true`.
7. **Never guess** which option is the tested brand, which code is the correct slogan / main message / proof of
   exposure, or which question is the "main media" — ask the researcher.

## Workflow

### 0. Confirm inputs (ask, do not guess)
`.sav` path · tested brand (Hebrew name as it appears in the answer lists) · CAMPAIGN_ID (if known) · omnibus? ·
questionnaire `.docx` (needed for message order & slogan/message code roles) · optional DP crosstab to reconcile.
Locate the newest `Impact360 import dictionary*.xlsx` (Benchmark folder, ignore `OLD`/`Copy of`); the profile step
falls back to the bundled copy in `assets/`.

### 1. Profile — find the relevant questions
```
python scripts/svr_profile.py "<file.sav>" --out mapping.json --brand "<brand>" --campaign-id <ID> [--omnibus] \
       [--search-root "<Benchmark dir>"]
```
Writes `mapping.json` (machine) and `mapping_review.xlsx` (human). It groups the SAV columns into question blocks,
skips paradata / demographics / raw verbatims, and proposes for each block: type (`scale · single · multi ·
coded_open · describe · message_takeout`), dictionary variable + confidence (`exact · alias · keyword · fuzzy-*`),
value→slot map, exposure components, customer variable, and a `review` list of what must be confirmed.
`--omnibus` sets `include:false` on every block without a dictionary variable (other clients' questions).

### 2. Review the mapping WITH the researcher (mandatory gate)
Show: relevant blocks and their dictionary variable; the `NEEDS confirmed` list; skipped blocks that look relevant;
exposure components + the union check; customer variable + option text. Then resolve, editing `mapping.json`:

| Item | What to decide / edit |
|---|---|
| fuzzy matches | verify against the questionnaire; set `"confirmed": true` or change/null `dict_var` |
| exposure | `exposure.components` — one entry per media question (`kind: single` or `any_of`); the `dict_var` REC* of each question is set on the question block |
| customer | `customer.var` = the USAGE (3 months) row of the **tested brand**; unticked/empty → non-customer |
| scales | `value_slots` (SAV code → slot; DK → 88). 4-point wording → the `-KC version` variant (auto) |
| message takeout | `MAIN_MESSAGE_TAKEOUT` value_slots and `TOTAL_MESSAGE_TAKEOUT` `option_slots`: 1=main, 2=sec-1, 3=sec-2, 4=buy/try — **from the questionnaire answer list, never by size** |
| coded open-ends | `nets`: `{"SLOGAN#01":{"include":[codeVar]}}`; `SPONTIMP_CORRECT/MAIN/SEC/_BRD`, `SEMIAEX-VD_gross/NET/PRS/LNG/MSG/BRD` need code roles; `UNEXPOSEB#01`/`SEMIAEX-CAT#01` = tested-brand code/row |
| duplicates | one dictionary variable per block (the profile demotes duplicates to analysis-only) |

**Custom summaries (Net Builder artifact).** Step 1 also writes `<mapping>_codes_catalog.json` (every code of every coded
open-end / multi block + the nets the dictionary expects, e.g. SPONTIMP_CORRECT, SEMIAEX-VD_PRS). Load it in the
"Net Builder" artifact (claude.ai artifact published by Itay), tick which codes belong to each net, add free-named
summaries ("מסרים נכונים"), copy the resulting `nets.json` and run with `--nets nets.json`. Dictionary-named nets go to
`DATA_לייבוא`; `CUSTOM:` nets appear in the findings table only (no bench slot).

**Live view in the Net Builder.** `python scripts/svr_export_results.py study.sav mapping.json --out results_data.json` writes
anonymous 0/1 code flags + the 5 level masks (no ids, no text). In the artifact press "טען נתוני משיבים": % per level with
significance letters update live as codes are ticked; the file is read locally in the browser and never uploaded. Never
embed it in the published page.

### 3. Run
```
python scripts/svr_run.py "<file.sav>" mapping.json --out "<Study>_FINDINGS_SAV.xlsx" [--campaign-id <ID>] [--nets nets.json]
```
Needs `pyreadstat openpyxl pandas numpy rapidfuzz` (`pip install ... --break-system-packages`).

### 4. Verify, then hand over
Open sheet **בקרות**: exposure union = DP variable; every single-choice table sums to 100; ATTENTION within 0-42;
duplicate `united`; low bases. Reconcile a few tables against the DP crosstab if one exists (they must match on the
same base). Report to the researcher: N per level, the exposure definition used, every assumption still open, and the
dictionary variables that were **not** computed (sheet **לא חושב**) with the reason.
Then: `DATA_לייבוא` → paste into the LIVE workbook of `impact360-master-import` (or hand the workbook to that skill).

## Output workbook

| Sheet | Content |
|---|---|
| README | levels + N, how to read, limits |
| ממצאים | one table per question · columns A Sample · B Exposed · C Not exposed · D Customers · E Non-customers, with significance LETTERS (capital = 95%, small = 90%; B vs C, D vs E) · **summary variables (T2B, TOP, B3B, mean, nets, indices) in a gold block at the TOP of each table**, answer breakdown below |
| משתנים מסכמים | flat list of every dictionary slot computed (united, label, role, 4 levels + n) |
| DATA_לייבוא | `CAMPAIGN_ID · VAR_NAME · ANSWER_LABEL · VALUE · united` (+ base, n) — sample level; `_E` twins from the exposed level |
| הגדרות | mapping used, exposure / customer definition, skipped blocks |
| בקרות | automatic checks |
| לא חושב | dictionary variables not computed + reason (indices are computed by the LIVE engine) |

## What is computed automatically (from raw rows)

- every answer slot of a mapped question (`#01…#0N`, `#88` DK), `#90 TOP`, `#91 T2B`, `#92 B3B`, `#93 Low3`, `#95 MEAN`
- **Total Exposed#01** (union) and **Total Exposed Digital#01**, `REC*#01` per channel (single yes/no or any-of grid)
- **DESCRIBE#01-#20**, worlds `#21-#25` (Bible v5.2 W-map, by attribute name), `#26` TOTAL, **`#27` ATTENTION =
  (0.4·fn1 + 0.2·(fn2+fn3+fn4))·10** on respondent level
- `MAIN MESSAGE_TAKEOUT#01-#06`, `Total MESSAGE_TAKEOUT#01-#05` (main-pick OR additional-mention), `MEI_DEPTH` (analysis row)
- `NEXT_ACTION#96` (max method 100/70/40/0/0), coded-open nets (`LIKES#01`, `DISLIKES#01`, `SPONTIMPRESSION#01`, …)
- `_E` twins for every computed slot that has one (exposed base)
- significance: two-proportion z (pooled, 95%, n≥30); means via z on SD

Details, formulas and the open items: `references/rules.md`. Dictionary coverage: `references/coverage.md`.

## Known limits (v1)
Demographic profile tables and brand-image grids (brand × statement) are not tabulated. Weighting is supported via
`project.weight_var` (weighted %, unweighted n). Dictionary indices (APS/BLS/MEI/ARS/GAPI/…) are left to the LIVE
engine. The SAV must carry the Decipher naming convention (`name`, `nameN`, `nameNrM`, `vqX_coded`) — other layouts need
the block map edited by hand.
