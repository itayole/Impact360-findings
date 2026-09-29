# -*- coding: utf-8 -*-
"""svr.accuracy — identification accuracy report (spec 11.1א).  Runs the profile with NO human intervention and
compares each proposed dictionary variable with a verified ground truth.

    python -m svr.accuracy cases/*.json [--out report.json]

case.json = {"name", "sav", "dictionary", "brand", "omnibus": false,
             "truth": {"<block key>": "<dictionary VAR_NAME>" | null}}
`null` = the block must NOT map to a dictionary variable.  Blocks absent from `truth` are not scored.

Outcome per scored block:  correct | wrong | flagged (not trusted: needs approval — measured by manual-change rate
later) | missed (truth has a variable, proposal has none).  Acceptance: ZERO `wrong` among exact/tag/template/alias.
"""
import argparse
import json
import sys

from . import lib as L
from .profile import profile, TRUSTED

LAYERS = ("exact", "tag", "template", "alias", "structure", "keyword", "fuzzy-high", "fuzzy-low", "none")


def score_case(case, df=None, meta=None):
    vars_, codes = L.load_dictionary(case["dictionary"])
    if df is None:
        df, meta = L.load_sav(case["sav"])
    m, _ = profile(df, meta, vars_, codes, case["dictionary"], case.get("brand", ""), "", case.get("omnibus", False))
    rows, by_layer = [], {k: dict(correct=0, wrong=0, flagged=0, missed=0) for k in LAYERS}
    for e in m["questions"]:
        if e["key"] not in case["truth"]:
            continue
        truth, got, conf = case["truth"][e["key"]], e["dict_var"], e["confidence"]
        if got == truth:
            out = "correct" if (got is None or conf in TRUSTED) else "flagged"
            # a correct-but-untrusted proposal is still 'flagged' (a human must confirm it); count it separately
            if out == "flagged":
                by_layer[conf]["flagged"] += 1
            else:
                by_layer[conf]["correct"] += 1
        elif got is None:
            out = "missed"
            by_layer["none"]["missed"] += 1
        else:
            out = "wrong"
            by_layer[conf]["wrong"] += 1
        rows.append(dict(block=e["key"], proposed=got, truth=truth, confidence=conf, outcome=out))
    wrong_trusted = [r for r in rows if r["outcome"] == "wrong" and r["confidence"] in TRUSTED]
    return dict(name=case.get("name", case["sav"]), n_scored=len(rows), by_layer=by_layer, rows=rows,
                wrong_trusted=wrong_trusted, passed=not wrong_trusted)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cases", nargs="+")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    reports = []
    for p in a.cases:
        with open(p, encoding="utf-8") as f:
            reports.append(score_case(json.load(f)))
    for r in reports:
        print(f"{r['name']}: scored={r['n_scored']} passed={r['passed']}")
        for k, v in r["by_layer"].items():
            if any(v.values()):
                print(f"   {k:11s} {v}")
        for w in r["wrong_trusted"]:
            print("   WRONG (trusted layer):", w)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(reports, f, ensure_ascii=False, indent=1)
    return 0 if all(r["passed"] for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
