"""Template library (spec 8): wave 2 of the same tracker needs (almost) no approvals and gives identical numbers."""
import copy

from conftest import needs_golden, SAV, DICT
from svr import pipeline as P, lib as L, templates as T


@needs_golden
def test_wave_two_roundtrip(golden, tmp_path):
    df, meta = L.load_sav(str(SAV))
    fp = T.fingerprint(df, meta)
    lib = T.Library(str(tmp_path))
    t1 = lib.save("Huggies FreeFeel", golden["mapping"], fp, user="tester", client="Kimberly", tracker="FreeFeel")
    assert t1["version"] == 1 and "respondent" not in str(t1).lower()
    # a second wave file with an identical structure is suggested (>= 0.90) and applies without new approvals
    assert lib.suggest(fp)[0]["similarity"] == 1.0
    mapping2, _ = P.run_profile(str(SAV), str(DICT), brand="האגיס", campaign_id="W2")
    diff = T.apply_template(mapping2, lib.get("Huggies_FreeFeel"))
    assert not diff["missing"] and not diff["new"] and not diff["structure_changed"]
    pending = [e["key"] for e in mapping2["questions"] if e["needs_approval"]]
    assert pending == ["seen"]                 # only the match nobody ever approved is left (spec 11.3: < 5)
    xlsx, summ, ctx2 = P.run_findings(str(SAV), mapping2, str(DICT))
    v2 = {r["united"]: r["vals"] for t in ctx2.tables for r in t["rows"] if r["united"]}
    assert v2 == golden["vals"]


@needs_golden
def test_versioning_and_alias_growth(golden, tmp_path):
    df, meta = L.load_sav(str(SAV))
    fp = T.fingerprint(df, meta)
    lib = T.Library(str(tmp_path))
    lib.save("Huggies FreeFeel", golden["mapping"], fp, user="a")
    m2 = copy.deepcopy(golden["mapping"])
    m2["questions"][0]["include"] = False
    t2 = lib.save("Huggies FreeFeel", m2, fp, user="b")
    assert t2["version"] == 2 and any("הוחרג" in c for c in t2["changes"])
    assert [h["created_by"] for h in lib.history("Huggies_FreeFeel")] == ["a", "b"]
    assert lib.aliases().get("q31") == "SEMIAEX-CAT"    # a researcher-confirmed fuzzy match becomes an alias


def test_structure_change_is_flagged(tmp_path):
    tmpl = dict(id="x", name="x", version=1, mapping=dict(project={}, questions=[dict(key="A", vars=["A1", "A2"], dict_var="ENJOY", type="scale")]))
    mapping = dict(project={}, questions=[dict(key="A", vars=["A1"], dict_var="ENJOY", confidence="exact", review=[]),
                                          dict(key="B", vars=["B1"], dict_var=None, confidence="none", review=[])])
    d = T.apply_template(mapping, tmpl)
    assert d["structure_changed"] == ["A"] and d["new"] == ["B"]
