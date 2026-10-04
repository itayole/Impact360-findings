"""Charts from findings tables (pure functions; aggregates only, never respondent data).

build_specs(results)  -> one chart spec per question, from the `preview.results_tables` payload
render_pptx(specs)    -> native (editable) PowerPoint charts, one slide per question, Hebrew / RTL

The module never recomputes methodology: every value comes from the findings tables as they are.
"""
import io
import math

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt
from lxml import etree

FONT = "Assistant"
MIN_N = 30                  # same threshold as the workbook (svr/report.py)
MAX_ITEMS = 15              # answer bars per chart (summaries are always shown)
DEFAULT_COLOR = "#775F76"
SORTED_TYPES = ("multi", "coded_open")      # unordered answers: biggest first; scales keep the questionnaire order
LEVEL_FALLBACK = "מדגם"


def build_specs(results, level="sample", color=DEFAULT_COLOR):
    """Chart spec per question that has at least one percentage row with a value at `level`."""
    names = {c["key"]: c["name"] for c in results.get("columns", [])}
    out = []
    for t in results["tables"]:
        if not t.get("dict_var"):
            continue
        pct = [r for r in t["rows"] if r["kind"] == "pct" and r["values"].get(level) is not None]
        summ = [r for r in pct if r["section"] == "summary"]
        items = [r for r in pct if r["section"] in ("item", "scale")]
        head = [r for r in summ if r.get("role") == "T2B"] or summ     # the headline net, as "Total Credible" in the brief
        if not head and not items:
            continue
        if t.get("type") in SORTED_TYPES:
            items = sorted(items, key=lambda r: -r["values"][level])
        cut = max(0, len(items) - MAX_ITEMS)
        items = items[:MAX_ITEMS]
        cats = [dict(label=r["label"], value=r["values"][level], headline=True) for r in head]
        cats += [dict(label=r["label"], value=r["values"][level], headline=False) for r in items]
        base = next((r["n"].get(level) for r in head + items if r["n"].get(level)), None)
        out.append(dict(key=t["key"], title=t.get("question") or t["title"], dict_var=t["dict_var"], type=t.get("type"),
                        chart_type="bar_h", color=color, level=level, level_name=names.get(level, LEVEL_FALLBACK),
                        base_n=base, low_base=bool(base is not None and base < MIN_N), truncated=cut, categories=cats))
    return out


# ------------------------------------------------------------------------------------------ pptx
def _rgb(hex_):
    h = hex_.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _font(font, size, bold=False, color="404040"):
    font.name = FONT
    font.size = Pt(size)
    font.bold = bold
    font.color.rgb = _rgb(color)
    rpr = font._rPr                                        # Hebrew is rendered with the complex-script font
    for old in rpr.findall(qn("a:cs")):
        rpr.remove(old)
    etree.SubElement(rpr, qn("a:cs")).set("typeface", FONT)


def _textbox(slide, x, y, w, h, text, size, bold=False, color="404040"):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.RIGHT
    p._p.get_or_add_pPr().set("rtl", "1")
    r = p.add_run()
    r.text = text
    _font(r.font, size, bold, color)
    r.font._rPr.set("lang", "he-IL")
    return tb


def _point_label_bold(point):
    """Bold, linked '0"%"' label for one point (python-pptx has no per-point number format)."""
    dl = point.data_label
    _font(dl.font, 16, True, "404040")
    dl.position = XL_LABEL_POSITION.OUTSIDE_END
    d = dl._dLbl
    if d.find(qn("c:numFmt")) is None:
        nf = etree.Element(qn("c:numFmt"))
        nf.set("formatCode", '0"%"')
        nf.set("sourceLinked", "0")
        d.find(qn("c:spPr") if d.find(qn("c:spPr")) is not None else qn("c:txPr")).addprevious(nf)   # schema order: numFmt, spPr, txPr


def _add_slide(prs, spec):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _textbox(slide, 0.6, 0.35, 12.1, 1.2, spec["title"], 24, True, "333333")
    cd = CategoryChartData()
    cd.categories = [c["label"] for c in spec["categories"]]
    cd.add_series(spec["level_name"], [c["value"] for c in spec["categories"]])
    gf = slide.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(0.6), Inches(1.65), Inches(12.1), Inches(5.0), cd)
    ch = gf.chart
    ch.has_legend = False
    ch.has_title = False
    ch.font.name = FONT
    plot = ch.plots[0]
    plot.gap_width = 70
    plot.vary_by_categories = False
    ser = plot.series[0]
    ser.format.fill.solid()
    ser.format.fill.fore_color.rgb = _rgb(spec["color"])
    dls = ser.data_labels            # series level: per-point labels below create it anyway and would hide the rest
    dls.show_value = True
    dls.number_format = '0"%"'
    dls.number_format_is_linked = False
    dls.position = XL_LABEL_POSITION.OUTSIDE_END
    _font(dls.font, 16, False, "595959")
    for i, c in enumerate(spec["categories"]):
        if c["headline"]:
            _point_label_bold(ser.points[i])
    top = max(c["value"] for c in spec["categories"])
    va, ca = ch.value_axis, ch.category_axis
    va.minimum_scale = 0
    va.maximum_scale = min(100, math.ceil(top * 1.2 / 10.0) * 10)
    va.has_major_gridlines = False
    va.reverse_order = True            # RTL: bars grow from the right, the answer labels sit on the right
    va.visible = False
    ca.reverse_order = True            # first answer on top
    ca.format.line.fill.background()
    ca.has_major_gridlines = False
    _font(ca.tick_labels.font, 16, False, "404040")
    note = f"בסיס: {spec['level_name']}"
    if spec["base_n"] is not None:
        note += f", N={spec['base_n']}"
    if spec["truncated"]:
        note += f" · מוצגות {MAX_ITEMS} תשובות מתוך {MAX_ITEMS + spec['truncated']}"
    _textbox(slide, 0.6, 6.8, 9.0, 0.45, note, 12, False, "7F7F7F")
    if spec["low_base"]:
        _textbox(slide, 9.6, 6.8, 3.1, 0.45, f"⚠ בסיס נמוך מ-{MIN_N}", 12, True, "C00000")


def render_pptx(specs):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    for s in specs:
        _add_slide(prs, s)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
