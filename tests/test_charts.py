"""Charts module: specs from findings tables + native PPTX export (synthetic data, no SAV needed)."""
import io

from pptx import Presentation
from pptx.util import Inches

from svr import charts as CH


def _row(label, v, n=500, section="item", role="", kind="pct"):
    return dict(label=label, united="X#01", section=section, role=role, kind=kind, note="", values={"sample": v, "exposed": v}, n={"sample": n}, letters={}, counts={})


RESULTS = dict(columns=[dict(key="sample", name="מדגם")], tables=[
    dict(key="CRED", title="CRED", question="עד כמה המותג אמין בעיניך?", dict_var="CRED", type="scale", rows=[
        _row("אמין מאוד", 23.4), _row("אמין", 47.6), _row("אמין במידה מסוימת", 19.0), _row("לא כל כך אמין", 8.0), _row("בכלל לא אמין", 3.0),
        _row("סה״כ אמין", 71.0, section="summary", role="T2B"), _row("רק אמין מאוד", 23.4, section="summary", role="TOP"),
        _row("ממוצע", 2.1, section="summary", role="MEAN", kind="mean")]),
    dict(key="USAGE", title="USAGE", question="איפה שמעת?", dict_var="USAGE", type="multi", rows=[
        _row(f"ערוץ {i}", float(i), n=12) for i in range(1, 26)]),
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
    assert s["categories"][0]["value"] == 25.0                    # biggest first for unordered answers
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


def _kinds(prs, i=0):
    return [sh.chart.chart_type for sh in prs.slides[i].shapes if sh.has_chart]


def test_settings_cleaning_and_per_question_overrides():
    st = CH.clean_settings(dict(defaults=dict(chart_type="nope", color="red"),
                                questions={"CRED": dict(chart_type="donut", color="#112233"), "USAGE": dict(include=False, chart_type="x"), "Z": 5}))
    assert st["defaults"] == dict(chart_type="bar_h", color=CH.DEFAULT_COLOR)
    assert st["questions"] == {"CRED": dict(chart_type="donut", color="#112233"), "USAGE": dict(include=False)}
    a, b = CH.build_specs(RESULTS, st)
    assert (a["chart_type"], a["color"], a["include"]) == ("donut", "#112233", True)
    assert (b["chart_type"], b["include"]) == ("bar_h", False)


def test_every_chart_type_renders_and_excluded_questions_are_skipped():
    from pptx.enum.chart import XL_CHART_TYPE as T
    want = {"bar_h": T.BAR_CLUSTERED, "bar_v": T.COLUMN_CLUSTERED, "stacked": T.BAR_STACKED_100, "donut": T.DOUGHNUT}
    for ct, kind in want.items():
        specs = CH.build_specs(RESULTS, dict(defaults=dict(chart_type=ct, color="#336699"), questions={"USAGE": dict(include=False)}))
        prs = Presentation(io.BytesIO(CH.render_pptx(specs)))
        assert len(prs.slides) == 1 and _kinds(prs) == [kind], ct
    # pie / stacked show the answers only (a headline net would double count them)
    prs = Presentation(io.BytesIO(CH.render_pptx(CH.build_specs(RESULTS, dict(defaults=dict(chart_type="donut"))))))
    ch = next(sh.chart for sh in prs.slides[0].shapes if sh.has_chart)
    assert "סה״כ אמין" not in list(ch.plots[0].categories) and len(list(ch.plots[0].categories)) == 5


def test_shades_darkest_first():
    s = CH.shades("#000000", 3)
    assert s[0] == "#000000" and s[0] < s[1] < s[2]


def _client_base(potx=False):
    import zipfile
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(10), Inches(5.625)
    for _ in range(2):
        prs.slides.add_slide(prs.slide_layouts[5])              # client's own sample slides must not leak into the output
    buf = io.BytesIO()
    prs.save(buf)
    data = buf.getvalue()
    if potx:
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as zi, zipfile.ZipFile(out, "w") as zo:
            for it in zi.infolist():
                b = zi.read(it.filename)
                zo.writestr(it, b.replace(b"presentationml.presentation.main+xml", b"presentationml.template.main+xml") if it.filename == "[Content_Types].xml" else b)
        data = out.getvalue()
    return data


def test_client_base_design_is_used_pptx_and_potx():
    from pptx.util import Inches
    for potx in (False, True):
        base = _client_base(potx)
        assert CH.check_base(base)[:2] == (10.0, 5.62) or CH.check_base(base)[0] == 10.0
        prs = Presentation(io.BytesIO(CH.render_pptx(CH.build_specs(RESULTS), base=base)))
        assert len(prs.slides) == 2                              # 2 questions, the 2 sample slides are gone
        assert prs.slide_width == Inches(10)                     # client's slide size kept
        sl = prs.slides[0]
        assert sl.shapes.title is not None and sl.shapes.title.text_frame.text.startswith("עד כמה")
        assert any(sh.has_chart for sh in sl.shapes)


def test_bad_base_file_is_rejected():
    import pytest
    with pytest.raises(CH.BaseError):
        CH.check_base(b"not a pptx")


def test_open_question_shows_all_answers_and_the_summaries():
    # open / multi answers are "analysis" rows (no dictionary slot) and the summary is a net with role 'item'
    res = dict(columns=[], tables=[dict(key="SLOGAN", title="SLOGAN", question="איזה סלוגן?", dict_var="SLOGAN", type="coded_open", rows=[
        _row("לא יודע", 7.9, section="analysis"), _row("סלוגן א", 24.9, section="analysis"), _row("סלוגן ב", 9.1, section="analysis"),
        _row("סה״כ זכרו נכון", 24.9, section="summary", role="item"), _row("סה״כ זכרו משהו", 60.0, section="summary", role="item")])])
    s = CH.build_specs(res)[0]
    assert [c["label"] for c in s["categories"]] == ["סה״כ זכרו נכון", "סה״כ זכרו משהו", "סלוגן א", "סלוגן ב", "לא יודע"]
    assert [c["headline"] for c in s["categories"]] == [True, True, False, False, False]      # both summaries, then the answers biggest first


def test_single_bar_is_slim_not_full_slide():
    one = dict(columns=[], tables=[dict(key="A", title="A", question="q", dict_var="A", type="single", rows=[_row("תשובה", 40.0)])])
    for ct, dim in (("bar_h", "height"), ("bar_v", "width")):
        prs = Presentation(io.BytesIO(CH.render_pptx(CH.build_specs(one, dict(defaults=dict(chart_type=ct))))))
        gf = next(sh for sh in prs.slides[0].shapes if sh.has_chart)
        assert getattr(gf, dim) < Inches(3.5), ct
        if ct == "bar_v":
            assert abs(gf.left + gf.width - Inches(12.7)) < 10          # RTL: anchored to the right
    full = dict(columns=[], tables=[dict(key="A", title="A", question="q", dict_var="A", type="multi", rows=[_row(f"x{i}", float(i)) for i in range(1, 21)])])
    prs = Presentation(io.BytesIO(CH.render_pptx(CH.build_specs(full))))
    assert next(sh for sh in prs.slides[0].shapes if sh.has_chart).height > Inches(4)       # 15 answers use the slide
