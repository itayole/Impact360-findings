"""Identification layers + questionnaire (spec 5א, 11.1א)."""
import pytest

from conftest import needs_golden, SAV, DICT, ROOT
from svr import questionnaire as Q, lib as L
from svr.profile import profile, needs_approval

DOCX = ROOT / "Example" / "שאלון אפקטיביות קמפיין השקת האגיס  FREE FEEL final (ID 146445).docx"


def test_parse_paragraphs_tags_answers_and_messages():
    paras = ["ENJOY", "עד כמה נהנית לצפות בפרסומת?", "הצג", "תשובה אחת", "מאוד נהניתי", "כלל לא נהניתי", "",
             "MAIN_MESSAGE_TAKEOUT", "איזה מסר הודגש?", "מסר א", "- מסר עיקרי", "מסר ב מסר משני", "לא יודעת"]
    q = Q.parse_paragraphs(paras)
    tags = q.by_tag()
    assert tags["ENJOY"].answers == ["מאוד נהניתי", "כלל לא נהניתי"]
    assert [m.role for m in q.messages] == ["main", "secondary", "none"]


def test_parse_failure_is_soft(tmp_path):
    bad = tmp_path / "x.docx"
    bad.write_bytes(b"not a docx")
    q = Q.parse_docx(str(bad))
    assert q.items == [] and q.warnings


@needs_golden
def test_haggies_layers_and_gating():
    vars_, codes = L.load_dictionary(str(DICT))
    df, meta = L.load_sav(str(SAV))
    q = Q.parse_docx(str(DOCX)) if DOCX.exists() else None
    m, _ = profile(df, meta, vars_, codes, str(DICT), "האגיס", "T", False, "x.sav", qnr=q)
    by = {e["key"]: e for e in m["questions"]}
    assert by["ENJOY"]["confidence"] == "exact" and by["ENJOY"]["layer"] == 1 and not by["ENJOY"]["needs_approval"]
    assert by["q31"]["needs_approval"] and by["seen"]["needs_approval"]
    # one dictionary variable = one block (structure layer must not duplicate ENJOY)
    carried = [e["dict_var"] for e in m["questions"] if e["dict_var"]]
    assert len(carried) == len(set(carried))
    assert all(e["needs_approval"] == needs_approval(e) for e in m["questions"])
    if q:
        assert [x["role"] for x in m["questionnaire"]["message_suggestion"]["order"]] == ["main", "secondary", "secondary", "generic"]


@needs_golden
def test_tag_layer_is_switch_controlled():
    vars_, codes = L.load_dictionary(str(DICT))
    df, meta = L.load_sav(str(SAV))
    meta.column_labels[meta.column_names.index("q54")] = "[ENJOY] q54: x"
    off, _ = profile(df, meta, vars_, codes, str(DICT), "האגיס", "T", False, "x.sav")
    assert not any(e["confidence"] == "tag" for e in off["questions"])
