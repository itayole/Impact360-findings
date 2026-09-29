# -*- coding: utf-8 -*-
"""Thin CLI wrapper for manual runs and tests:

    python -m svr.cli profile study.sav --dictionary dict.xlsx --brand "האגיס" --out mapping.json
    python -m svr.cli run study.sav mapping.json --out Findings.xlsx [--nets nets.json]
"""
import argparse
import json

from . import pipeline as P


def main(argv=None):
    ap = argparse.ArgumentParser(prog="svr")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("profile")
    p.add_argument("sav"); p.add_argument("--dictionary", required=True)
    p.add_argument("--out", default="mapping.json")
    p.add_argument("--brand", default=""); p.add_argument("--campaign-id", default="")
    p.add_argument("--omnibus", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("sav"); r.add_argument("mapping"); r.add_argument("--out", required=True)
    r.add_argument("--campaign-id", default=None); r.add_argument("--nets", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "profile":
        mapping, catalog = P.run_profile(a.sav, a.dictionary, a.brand, a.campaign_id, a.omnibus)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=1)
        with open(a.out.rsplit(".", 1)[0] + "_codes_catalog.json", "w", encoding="utf-8") as f:
            json.dump(catalog, f, ensure_ascii=False, indent=1)
        print(f"questions={len(mapping['questions'])} skipped={len(mapping['skipped'])} -> {a.out}")
    else:
        with open(a.mapping, encoding="utf-8") as f:
            mapping = json.load(f)
        if a.campaign_id:
            mapping["project"]["campaign_id"] = a.campaign_id
        if a.nets:
            with open(a.nets, encoding="utf-8") as f:
                P.apply_nets(mapping, json.load(f))
        xlsx, summ, _ = P.run_findings(a.sav, mapping)
        with open(a.out, "wb") as f:
            f.write(xlsx)
        print(f"tables={summ['tables']} dictionary-slots={summ['slots']} checks={summ['checks']} "
              f"flagged={len(summ['flagged'])} errors={len(summ['errors'])}")
        for c in summ["flagged"] + summ["errors"]:
            print("  !", c)


if __name__ == "__main__":
    main()
