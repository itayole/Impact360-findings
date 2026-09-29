import json
import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAV = pathlib.Path(os.environ.get("GOLDEN_SAV", ROOT / "Example" / "15422 (ID 147851).sav"))
DICT = pathlib.Path(os.environ.get("GOLDEN_DICT", ROOT / "Impact360 import dictionary (ID 145212).xlsx"))

needs_golden = pytest.mark.skipif(not (SAV.exists() and DICT.exists()), reason="golden SAV / dictionary not mounted")


@pytest.fixture(scope="session")
def golden():
    from svr import pipeline as P
    conf = json.loads((ROOT / "tests" / "golden" / "haggies_confirmations.json").read_text(encoding="utf-8"))
    mapping, catalog = P.run_profile(str(SAV), str(DICT), brand=conf["brand"], campaign_id="TEST-1")
    byk = {e["key"]: e for e in mapping["questions"]}
    for k in conf["confirmed"]:
        byk[k]["confirmed"] = True
    for k, nets in conf["nets"].items():
        byk[k].setdefault("nets", {}).update(nets)
    byk["q31"].setdefault("nets", {}).update(conf["q31_nets"])
    xlsx, summ, ctx = P.run_findings(str(SAV), mapping, str(DICT))
    vals = {r["united"]: r["vals"] for t in ctx.tables for r in t["rows"] if r["united"]}
    return dict(mapping=mapping, xlsx=xlsx, summary=summ, ctx=ctx, vals=vals)
