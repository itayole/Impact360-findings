# impact360-sav-runner — rules, definitions and open items

Validation on Huggies (N=406): **252/260** comparable table cells equal the DP crosstab (the 8 others = `q9` asked of a subset — DP divides by 406, the runner by those asked — and DESCRIBE TOTAL shown ×100 in the DP tab); **91/96** `united` values equal the verified LIVE workbook.

Everything here was fixed while running the Huggies FreeFeel study (SAV 15422, N=406) and reconciling it with the
previously verified LIVE workbook (`Huggies_FreeFeel_LIVE_v2.xlsx`, 86 of 90 comparable values identical; the 4
differences are the two documented deviations below).

## 1. Levels

| Level | Definition | Huggies check |
|---|---|---|
| מדגם | every respondent | N=406 |
| נחשפים (Total Exposed) | **union** of all media-exposure questions: TV/video (`q33`→RECVD), digital/banners (`q49`), social (`q50`), influencer grid (`q52`, any option except "none"), activity questions (`q53/q56/q57`) | union = 217 = DP variable `vctq1c1` for 406/406 respondents |
| לקוחות | tested-brand row of the USAGE (3 months) multi-select = 1 | 246 |
| לא לקוחות | everyone else (0 **or empty** — Decipher leaves un-ticked rows empty) | 160 |
| (לא נחשפים) | complement of the exposed union — used only as the reference for the ▲▼ test | 189 |

Do not confuse with the DP crosstab "נחשפו" column, which in the Huggies tab was `q33` only (n=116, "חשיפה למדיה
עיקרית"). The dictionary flags the definition of "נחשפים" for the `_E` twins as an open high-severity item
(`Impact360_Summation_Vars_Map.xlsx`, sheet פגמים במילון). The runner uses the owner's choice (TOTAL_EXPOSURE union)
and says so in the README of every workbook. **Deviation 1:** `ENJOY_E#91`, `MAIN MESSAGE_TAKEOUT#01` (and any `_E`)
differ from a run that used the q33 base — expected.

## 2. Bases

* Scale / single / multi: % of respondents **who answered** the question (n shown per row in `משתנים מסכמים`;
  table note when n < N).
* `base:"all"` (skip-logic follow-ups, measured on the total sample; non-asked = did not mention):
  `SEMIAEX-VD` (asked only of those who claimed category-ad exposure — 152 of 406), `SEMIAEX-CAT`, `UNEXPOSEB`,
  `SLOGAN`, `SPONTIMPRESSION`. Verified: `SEMIAEX-VD#01`=29.6, `SEMIAEX-CAT#01`=37.4, `UNEXPOSEB#01`=36.0,
  `SLOGAN#01`=24.9 match the bench run.
* `LIKES` / `DISLIKES` are asked of a subset (239 / 167) → base = asked (matches the DP tab).

## 3. Formulas

* **T2B (#91)** = slots 01+02; **TOP (#90)** = 01; **B3B (#92)** = 03+04+05; **Low3 (#93)** = 01+02+03;
  **MEAN (#95)** = mean of the slot number 1..5 excluding DK (1 = most positive). `#95` is `Don't import`.
* **DESCRIBE** worlds from the Bible v5.2 sheet `DESCRIBE_Worlds_Pentagon`, matched **by attribute name**
  (SAV item order ≠ W-code order): Magnetism 7 · Emotional 2 · Dynamic 3 · Negative 2 · Rational 4 (+ 2 unassigned:
  משעממת, נעימה). `#21-#25` = mean count per respondent, `#26 TOTAL` = mean count of all 20 (Huggies DP total
  335.5% = 3.355 ✓ matches), **`#27 ATTENTION` = mean of (0.4·fn1 + 0.2·(fn2+fn3+fn4))·10**, range 0-42.
* **Total MESSAGE_TAKEOUT #k** = picked option k in `MAIN_MESSAGE_TAKEOUT` **or** ticked in the additional-mentions
  multi (Decipher leaves the already-picked option empty there, so the OR is required). `#05` = max(#01..#03).
  **MAIN MESSAGE_TAKEOUT** `#02..#05` = first-mention shares of options 1..4, `#01` = `#02` among the exposed,
  `#06` = max(#02..#04).
* **NEXT_ACTION#96** = mean over respondents of the highest tier ticked (100/70/40/0/0) — max method, from raw rows.
* **Coded open-ends**: `X#01` = respondent has ≥ 1 substantive code (`exclude` list = DK / nothing / "liked all" for
  DISLIKES). Role-specific nets need `include` lists.
* **`_E` twin** = the same slot, exposed level, exported from the exposed column.
* Significance: pooled two-proportion z, |z| > 1.96, both n ≥ 30; means: Welch z. ▲/▼ vs the reference group
  (exposed vs not-exposed, customers vs non-customers and vice-versa).

## 4. Open items (raise with the researcher every time)

1. `DESCRIBE#26` — definition confirmed by the Huggies DP total but not by the Bible; keep "assumption" note.
2. Which REC* dictionary variable each media question is (`q49`→RECIMB vs RECVDG, `q50`→RECINF vs RECVSO …): the
   keyword proposal follows the previous verified run; the questionnaire stimulus decides. **Deviation 2:** the
   previous run built `RECINF_BR` and `Total Exposed Digital` from a different set of activity questions
   (36.9 / 42.6 vs 35.7 / 40.4 here).
3. Code roles for `SPONTIMP_CORRECT/MAIN/SEC(+_E)`, `SEMIAEX-VD_gross/NET/PRS/LNG/MSG/BRD`, correct slogan — brief +
   codebook; the runner does not invent them.
4. `MEI_DEPTH` has no dictionary slot (emitted as an analysis row).
5. Scale points ≠ dictionary points (e.g. 4-point CLEAR_MESSAGE) → blank slot, flagged.
6. SAV value labels: Hebrew Decipher exports decode scrambled with the default cp1255; the loader re-reads value
   labels as iso-8859-8 (clean). If a new export still looks garbled, check `svr_lib.load_sav`.
