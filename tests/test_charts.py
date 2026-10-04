"""Charts module: specs from findings tables + native PPTX export (synthetic data, no SAV needed)."""
import io

from pptx import Presentation

from svr import charts as CH


def _row(label, v, n=500, section="item", role="", kind="pct"):
    return dict(label=label, united="X#01", section=section, role=role, kind=kind, note="", values={"sample": v, "exposed": v}, n={"sample": n}, letters={}, counts={})


RESULTS = dict(columns=[dict(key="sample", name="מדגם")], tables=[
    dict(key="CRED", title="CRED", question="עד כמה המותג אמין בעיניך?", dict_var="CRED", type="scale", rows=[
        _row("אמין מאוד", 23.4), _row("אמין", 47.6), _row("אמין במידה מסוימת", 19.0), _row("לא כל כך אמין", 8.0), _row("בכלל לא אמין", 3.0),
        _row("סה״כ אמין", 71.0, section="summary", role="T2B"), _row("רק אמין מאוד", 23.4, section="summary", role="TOP"),
        _row("ממוצע", 2.1, section="summary", role="MEAN", kind="mean")]),
    dict(key="USAGE", title="USAGE", question="איפה שמעת?", dict_var="USAGE", type="multi", rows=[
        _row(f"ערוץ {i}", float(i), n=12) for i in range(1, 21)]),
    dict(key="NODICT", title="NODICT", question="", dict_var=None, type="single", rows=[_row("א", 50.0)]),
    dict(key="MEANONLY", title="M", question="x", dict_var="M", type="describe", rows=[_row("ממוצע", 3.2, section="summary", role="MEAN", kind="mean")]),
])


def test_specs_headline_first_and_filters():
    specs = CH.build_specs(RESULTS)
    assert [s["key"] for s in specs] == ["CRED", "USAGE"]          # no dict_var / no pct rows -> no chart
    c = specs[0]["categories"]
    assert [x["label"] for x in c][:2] == ["סה״כ אמין", "אמין מאוד"]    # T2B headline only, then the answers in questionnaire order
    assert c[0]["headline"] and not c[1]["headline"] and len(c) == 6
    assert specs[0]["base_n"] == 500 and not specs[0]["low_base"]


def test_specs_multi_sorted_capped_low_base():
    s = CH.build_specs(RESULTS)[1]
    assert len(s["categories"]) == CH.MAX_ITEMS and s["truncated"] == 5
    assert s["categories"][0]["value"] == 20.0                    # biggest first for unordered answers
    assert s["low_base"] and s["base_n"] == 12


def test_pptx_opens_and_has_native_chart_per_question():
    data = CH.render_pptx(CH.build_specs(RESULTS))
    prs = Presentation(io.BytesIO(data))
    assert len(prs.slides) == 2
    shapes = prs.slides[0].shapes
    assert any(sh.has_chart for sh in shapes)
    chart = next(sh.chart for sh in shapes if sh.has_chart)
    assert list(chart.plots[0].categories)[0] == "סה״כ אמין"
    assert any("בסיס" in sh.text_frame.text for sh in shapes if sh.has_text_frame)
