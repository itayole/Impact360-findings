#!/usr/bin/env python3
"""Step 1b - export ANONYMOUS respondent-level code flags + level masks for the Net Builder artifact.

python svr_export_results.py study.sav mapping.json --out results_data.json

No respondent id, no verbatim text: only 0/1 bit-strings (one char per respondent) per code, the 5 level masks and
the 'asked' base per block. Load the file LOCALLY in the Net Builder (FileReader, nothing is uploaded).
"""
import argparse, json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import svr_lib as L
import svr_compute as C


def bits(a):
    return "".join("1" if x else "0" for x in a)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sav"); ap.add_argument("mapping"); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    mapping = json.load(open(a.mapping, encoding="utf-8"))
    vars_, codes = L.load_dictionary(mapping["project"]["dictionary"])
    df, meta = L.load_sav(a.sav)
    ctx = C.Ctx(df, meta, vars_, codes, mapping)
    m = ctx.masks
    out = {"n": int(ctx.n), "levels": {k: bits(m[k]) for k in ("sample", "exposed", "notexposed", "customers", "noncust") if k in m},
           "blocks": {}}
    for e in mapping["questions"]:
        if e.get("type") != "coded_open" or not e.get("include", True):
            continue
        blk = df[e["vars"]]
        asked = blk.notna().any(axis=1).values
        if asked.mean() >= 0.98 or e.get("base") == "all":
            asked = np.ones(ctx.n, bool)
        out["blocks"][e["key"]] = {"asked": bits(asked), "asked_all": bits(np.ones(ctx.n, bool)),
                                   "flags": {v: bits((df[v] == 1).values) for v in e["vars"]}}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("wrote", a.out, os.path.getsize(a.out) // 1024, "KB; blocks:", len(out["blocks"]), "N =", ctx.n)


if __name__ == "__main__":
    main()
