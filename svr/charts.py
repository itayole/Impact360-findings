"""Charts from findings tables (pure functions; aggregates only, never respondent data).

build_specs(results, settings)  -> one chart spec per question, from the `preview.results_tables` payload
render_pptx(specs, base=None)   -> native (editable) PowerPoint charts, one slide per question, Hebrew / RTL;
                                   `base` = bytes of the client's .pptx/.potx whose master/layouts/theme are reused

The module never recomputes methodology: every value comes from the findings tables as they are.
`settings` = {"defaults": {"chart_type", "color"}, "questions": {table_key: {"chart_type", "color", "include"}}}
(stored in mapping["charts"], so it travels with the client template).
"""
import io
import math
import re
import zipfile

from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

FONT = "Assistant"
MIN_N = 30                  # same threshold as the workbook (svr/report.py)
MAX_ITEMS = 20              # answer bars per chart (summaries are always shown)
DEFAULT_COLOR = "#1F3864"          # dark blue = the workbook navy (svr/report.py)
SORTED_TYPES = ("multi", "coded_open")      # unordered answers: biggest first; scales keep the questionnaire order
LEVEL_FALLBACK = "מדגם"
MAQAF = "־"            # Hebrew hyphen: unlike "-" it is not absorbed into the following number
THRESHOLD_MIN_ANSWERS = 6   # the display threshold applies to open questions and to any other (non-scale) question with more answers than this
CHART_TYPES = {"bar_h": "עמודות אופקיות", "bar_v": "עמודות אנכיות", "stacked": "עמודה מוערמת 100%", "donut": "דונאט"}
DEFAULT_TYPE = "bar_h"
_HEX = re.compile(r"#[0-9a-fA-F]{6}\Z")
_W, _H = 13.333, 7.5        # layout coordinates below are for a 16:9 slide, scaled to the actual slide size


_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")           # control characters are illegal in XML: one stray byte would fail the whole export
_PIPE = re.compile(r"\s*\[pipe:[^\]]*\]")                           # questionnaire piping tokens that leak into question texts
NON_ADDITIVE = SORTED_TYPES + ("derived", "twin", "describe", "message_takeout")     # answers that do not sum to 100%: no pie / 100% stack


def clean_text(v):
    return _CTRL.sub("", str(v if v is not None else "")).strip()


def allowed_types(qtype):
    """Pie and 100%-stacked charts only make sense for answers that add up to 100%."""
    return [k for k in CHART_TYPES if qtype not in NON_ADDITIVE or k not in ("stacked", "donut")]


def _pct(v):
    """Lower threshold for open-question answers, % (0 = show everything)."""
    if isinstance(v, bool):
        return 0
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0
    return round(min(max(v, 0.0), 100.0), 1) if v == v else 0


def clean_settings(raw):
    """Validated copy of user settings (unknown keys / bad values / wrong types dropped)."""
    raw = raw if isinstance(raw, dict) else {}
    d = raw.get("defaults") if isinstance(raw.get("defaults"), dict) else {}
    ct, col = d.get("chart_type"), d.get("color")
    out = dict(defaults=dict(chart_type=ct if isinstance(ct, str) and ct in CHART_TYPES else DEFAULT_TYPE,
                             color=col if isinstance(col, str) and _HEX.match(col) else DEFAULT_COLOR,
                             min_pct=_pct(d.get("min_pct"))),
               questions={})
    qs = raw.get("questions") if isinstance(raw.get("questions"), dict) else {}
    for k, q in list(qs.items())[:500]:
        if not isinstance(q, dict):
            continue
        o = {}
        if isinstance(q.get("chart_type"), str) and q["chart_type"] in CHART_TYPES:
            o["chart_type"] = q["chart_type"]
        if isinstance(q.get("color"), str) and _HEX.match(q["color"]):
            o["color"] = q["color"]
        if q.get("include") is False:
            o["include"] = False
        if o:
            out["questions"][str(k)[:120]] = o
    if isinstance(raw.get("base_name"), str) and raw["base_name"]:
        out["base_name"] = raw["base_name"][:200]
    if isinstance(raw.get("base_sha"), str) and re.fullmatch(r"[0-9a-f]{6,16}", raw["base_sha"]):
        out["base_sha"] = raw["base_sha"]
    return out


def shades(color, n):
    """n tints of `color` (darkest first) for pies / stacked bars. Same formula as the browser preview (static/app.js)."""
    h = color.lstrip("#")
    rgb = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    out = []
    for i in range(n):
        t = 0.65 * i / max(n - 1, 1)
        out.append("#" + "".join(f"{round(c + (255 - c) * t):02X}" for c in rgb))
    return out


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def build_specs(results, settings=None, level="sample"):
    """Chart spec per question that has at least one percentage row with a value at `level`."""
    st = clean_settings(settings)
    names = {c["key"]: c["name"] for c in results.get("columns", [])}
    out = []
    for t in results["tables"]:
        if not t.get("dict_var"):
            continue
        pct = [r for r in t["rows"] if r["kind"] == "pct" and _finite(r["values"].get(level))]
        summ = [r for r in pct if r["section"] == "summary"]
        items = [r for r in pct if r["section"] != "summary"]       # open / multi answers are "analysis" rows (no dictionary slot): still answers
        head = [r for r in summ if r.get("role") == "T2B"] or summ     # the headline net, as "Total Credible" in the brief
        if not head and not items:
            continue
        if t.get("type") in SORTED_TYPES:
            items = sorted(items, key=lambda r: -r["values"][level])
        hidden = 0
        long_list = t.get("type") == "coded_open" or (t.get("type") != "scale" and len(items) > THRESHOLD_MIN_ANSWERS)
        if long_list and st["defaults"]["min_pct"] > 0:        # drop the long tail of rare answers (rating scales are never thinned)
            keep = [r for r in items if r["values"][level] >= st["defaults"]["min_pct"]]
            hidden, items = len(items) - len(keep), keep
        cut = max(0, len(items) - MAX_ITEMS)
        items = items[:MAX_ITEMS]
        # One base per chart: the answers' (most common n). A summary computed on another base (e.g. exposed only) would sit next
        # to answers of the whole sample and mislead, so it is left out and the slide says so.
        ns = [r["n"].get(level) for r in (items or head) if r["n"].get(level)]
        base = max(set(ns), key=ns.count) if ns else None
        dropped = [r for r in head if base is not None and r["n"].get(level) and r["n"].get(level) != base] if items else []
        head = [r for r in head if r not in dropped]
        if not head and not items:
            continue
        cats = [dict(label=clean_text(r["label"]), value=r["values"][level], headline=True) for r in head]
        cats += [dict(label=clean_text(r["label"]), value=r["values"][level], headline=False) for r in items]
        q = st["questions"].get(t["key"], {})
        allowed = allowed_types(t.get("type"))
        ctype = q.get("chart_type", st["defaults"]["chart_type"])
        out.append(dict(key=t["key"], title=clean_text(t.get("question") or t["title"]), dict_var=t["dict_var"], type=t.get("type"),
                        short_title=clean_text(t.get("short_title")) or t["dict_var"],       # the dictionary's short Hebrew title
                        chart_type=ctype if ctype in allowed else DEFAULT_TYPE, allowed_types=allowed, color=q.get("color", st["defaults"]["color"]),
                        include=q.get("include", True), level=level, level_name=names.get(level, LEVEL_FALLBACK),
                        base_n=base, low_base=bool(base is not None and base < MIN_N), truncated=cut, hidden_low=hidden, dropped_head=len(dropped),
                        min_pct=st["defaults"]["min_pct"], categories=cats))
    return out


def _parts(spec):
    """Categories drawn by pie / stacked charts: the answers only (a headline net would double count them)."""
    items = [c for c in spec["categories"] if not c["headline"]]
    return items or spec["categories"]


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


def _rtl_paragraph(p):
    p.alignment = PP_ALIGN.RIGHT
    p._p.get_or_add_pPr().set("rtl", "1")


def _textbox(slide, x, y, w, h, text, size, bold=False, color="404040", k=1.0):
    tb = slide.shapes.add_textbox(Inches(x * k), Inches(y * k), Inches(w * k), Inches(h * k))
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    _rtl_paragraph(p)
    r = p.add_run()
    r.text = text
    _font(r.font, size, bold, color)
    r.font._rPr.set("lang", "he-IL")
    return tb


def _point_label_bold(point, size):
    """Bold, linked '0"%"' label for one point (python-pptx has no per-point number format)."""
    dl = point.data_label
    _font(dl.font, size, True, "404040")
    dl.position = XL_LABEL_POSITION.OUTSIDE_END
    d = dl._dLbl
    if d.find(qn("c:numFmt")) is None:
        nf = etree.Element(qn("c:numFmt"))
        nf.set("formatCode", '0"%"')
        nf.set("sourceLinked", "0")
        d.find(qn("c:spPr") if d.find(qn("c:spPr")) is not None else qn("c:txPr")).addprevious(nf)   # schema order: numFmt, spPr, txPr


def _bars(ch, spec, vertical, size):
    cats = spec["categories"]
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
    _font(dls.font, size, False, "595959")
    for i, c in enumerate(cats):
        if c["headline"]:
            _point_label_bold(ser.points[i], size)
    va, ca = ch.value_axis, ch.category_axis
    va.minimum_scale = 0
    va.maximum_scale = max(10, math.ceil(max(c["value"] for c in cats) * 1.2 / 10.0) * 10)
    va.has_major_gridlines = False
    va.visible = False
    ca.reverse_order = True            # horizontal: first answer on top; vertical (RTL): first answer on the right
    if not vertical:
        va.reverse_order = True        # RTL: bars grow from the right, the answer labels sit on the right
    ca.format.line.fill.background()
    ca.has_major_gridlines = False
    _font(ca.tick_labels.font, size, False, "404040")


def _stacked(ch, spec):
    plot = ch.plots[0]
    plot.gap_width = 40
    plot.overlap = 100
    plot.has_data_labels = True
    dls = plot.data_labels
    dls.show_value = True
    dls.number_format = '0"%"'
    dls.number_format_is_linked = False
    dls.position = XL_LABEL_POSITION.CENTER
    _font(dls.font, 16, True, "FFFFFF")
    parts = _parts(spec)
    for s, col in zip(plot.series, shades(spec["color"], len(parts))):
        s.format.fill.solid()
        s.format.fill.fore_color.rgb = _rgb(col)
    va, ca = ch.value_axis, ch.category_axis
    va.visible = False
    va.has_major_gridlines = False
    va.reverse_order = True            # RTL
    ca.visible = False
    ch.has_legend = True
    ch.legend.position = XL_LEGEND_POSITION.BOTTOM
    ch.legend.include_in_layout = False
    _font(ch.legend.font, 16, False, "404040")


def _donut(ch, spec):
    plot = ch.plots[0]
    plot.vary_by_categories = True
    ser = plot.series[0]
    parts = _parts(spec)
    for i, col in enumerate(shades(spec["color"], len(parts))):
        pt = ser.points[i]
        pt.format.fill.solid()
        pt.format.fill.fore_color.rgb = _rgb(col)
    plot.has_data_labels = True
    dls = plot.data_labels
    dls.show_value = True
    dls.number_format = '0"%"'
    dls.number_format_is_linked = False
    _font(dls.font, 16, True, "FFFFFF")
    ch.has_legend = True
    ch.legend.position = XL_LEGEND_POSITION.RIGHT
    ch.legend.include_in_layout = False
    _font(ch.legend.font, 16, False, "404040")


def question_footer(spec):
    """Grey 8pt line at the bottom of the slide: the question as asked, and its number / variable."""
    ident = spec["dict_var"] if spec["key"] == spec["dict_var"] else f"{spec['key']} / {spec['dict_var']}"
    q = re.sub(r"\s+", " ", _PIPE.sub("", spec["title"])).strip()
    if len(q) > 260:
        q = q[:259].rstrip() + "…"                                  # two 8pt lines at most: a long text must not run off the slide
    return f"{q}  |  {ident}"


def _add_slide(prs, layout, spec, k):
    slide = prs.slides.add_slide(layout)
    title_ph = next((ph for ph in slide.placeholders if "TITLE" in str(ph.placeholder_format.type) and "SUB" not in str(ph.placeholder_format.type)), None)
    for ph in list(slide.placeholders):                    # client layouts: keep the title, drop empty body/date/footer boxes
        if title_ph is None or ph._element is not title_ph._element:
            ph._element.getparent().remove(ph._element)
    if title_ph is not None:                               # inherits the client's title formatting
        tf = title_ph.text_frame
        tf.text = spec["short_title"]
        _rtl_paragraph(tf.paragraphs[0])
        for r in tf.paragraphs[0].runs:
            r.font._rPr.set("lang", "he-IL")
        try:
            top_chart = max(1.2 * k, (title_ph.top + title_ph.height) / 914400 + 0.1)
        except TypeError:                                  # a client layout without explicit geometry
            top_chart = 1.2 * k
    else:
        _textbox(slide, 0.6, 0.35, 12.1, 0.8, spec["short_title"], 28, True, "333333", k)
        top_chart = 1.2 * k
    bottom = 6.7 * k
    cd = CategoryChartData()
    ctype = spec["chart_type"]
    if ctype == "stacked":
        parts = _parts(spec)
        cd.categories = [spec["level_name"]]
        for c in parts:
            cd.add_series(c["label"], [c["value"]])
        kind = XL_CHART_TYPE.BAR_STACKED_100
    else:
        cats = _parts(spec) if ctype == "donut" else spec["categories"]
        cd.categories = [c["label"] for c in cats]
        cd.add_series(spec["level_name"], [c["value"] for c in cats])
        kind = {"bar_h": XL_CHART_TYPE.BAR_CLUSTERED, "bar_v": XL_CHART_TYPE.COLUMN_CLUSTERED, "donut": XL_CHART_TYPE.DOUGHNUT}[ctype]
    # A bar keeps the same thickness whatever the number of answers: the chart box is sized to the data (one answer = a slim chart,
    # not a full-slide bar). Horizontal: top aligned; vertical: right aligned (RTL).
    avail, n = bottom - top_chart, len(cd.categories) if ctype != "stacked" else 1
    x, y, w, h = 0.6 * k, top_chart, 12.1 * k, avail
    size = 16
    if ctype == "bar_h":
        h = min(avail, max(1.0 * k, n * 0.62 * k + 0.3 * k))
        size = 16 if h / n >= 0.42 * k else 12
    elif ctype == "bar_v":
        w = min(12.1 * k, max(3.0 * k, n * 1.6 * k))
        x = 0.6 * k + 12.1 * k - w
        size = 14 if n <= 8 else 11
    elif ctype == "stacked":
        h = min(avail, (2.6 + 0.3 * math.ceil(len(_parts(spec)) / 3)) * k)
    gf = slide.shapes.add_chart(kind, Inches(x), Inches(y), Inches(w), Inches(h), cd)
    ch = gf.chart
    ch.has_legend = False
    ch.has_title = False
    ch.font.name = FONT
    if ctype in ("bar_h", "bar_v"):
        _bars(ch, spec, ctype == "bar_v", size)
    elif ctype == "stacked":
        _stacked(ch, spec)
    else:
        _donut(ch, spec)
    for tx in ch._chartSpace.iter(qn("c:txPr")):                 # Hebrew labels: paragraph direction RTL so punctuation / Latin stay on the right side
        for ppr in tx.iter(qn("a:pPr")):
            ppr.set("rtl", "1")
    # Bottom notes: ONE number per text box and no hyphen touching a digit (the BIDI algorithm would swap two numbers in a Hebrew
    # line, and "ל-5%" renders as a minus). Boxes fill the row from the right.
    notes = [(f"בסיס: {spec['level_name']}" + (f", N={spec['base_n']}" if spec["base_n"] is not None else ""), False, "7F7F7F")]
    if spec.get("hidden_low"):
        notes += [(f"סף תצוגה: {spec['min_pct']:g}%", False, "7F7F7F"), (f"הוסתרו {spec['hidden_low']} תשובות קטנות", False, "7F7F7F")]
    if spec["truncated"]:
        notes.append((f"לא מוצגות {spec['truncated']} תשובות קטנות", False, "7F7F7F"))
    if spec.get("dropped_head"):
        notes.append(("סיכום על בסיס אחר לא מוצג", False, "7F7F7F"))
    if spec["low_base"]:
        notes.append((f"⚠ בסיס נמוך מ{MAQAF}{MIN_N}", True, "C00000"))
    w = min(3.0, 12.1 / len(notes))
    for i, (txt, bold, col) in enumerate(notes):
        _textbox(slide, 0.6 + 12.1 - w * (i + 1), 6.75, w, 0.35, txt, 12, bold, col, k)
    _textbox(slide, 0.6, 7.1, 12.1, 0.3, question_footer(spec), 8, False, "808080", k)      # question wording + number / variable


# ------------------------------------------------------------------------------------------ client base file
class BaseError(ValueError):
    pass


def _open_base(data):
    """Presentation from a client's .pptx or .potx (a template's content type is rewritten so python-pptx accepts it)."""
    try:
        zin = zipfile.ZipFile(io.BytesIO(data))
        ct = zin.read("[Content_Types].xml")
        if b"presentationml.template.main+xml" in ct:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    blob = zin.read(item.filename)
                    if item.filename == "[Content_Types].xml":
                        blob = blob.replace(b"presentationml.template.main+xml", b"presentationml.presentation.main+xml")
                    zout.writestr(item, blob)
            data = buf.getvalue()
        return Presentation(io.BytesIO(data))
    except Exception as e:
        raise BaseError("הקובץ אינו מצגת PowerPoint תקינה (.pptx / .potx)") from e


def check_base(data):
    """Validate an uploaded design file; returns (slide width, height in inches, layout names)."""
    prs = _open_base(data)
    return round(prs.slide_width / 914400, 2), round(prs.slide_height / 914400, 2), [l.name for l in prs.slide_layouts]


_SECTIONS_EXT = "{521415D9-36F7-43E2-AB2F-B90AF26B5E84}"       # p14:sectionLst


def _clear_slides(prs):
    lst = prs.slides._sldIdLst
    for sid in list(lst):
        prs.part.drop_rel(sid.rId)
        lst.remove(sid)
    root = prs._element                                    # sections and custom shows list slide ids: stale ids make PowerPoint ask to repair the file
    for el in root.findall(qn("p:custShowLst")):
        root.remove(el)
    ext_lst = root.find(qn("p:extLst"))
    if ext_lst is not None:
        for ext in list(ext_lst):
            if ext.get("uri") == _SECTIONS_EXT:
                ext_lst.remove(ext)


def _pick_layout(prs):
    """Title Only if the client's master has one; else the layout with a title and the fewest other placeholders; else the last (blank)."""
    best, score = None, None
    for lay in prs.slide_layouts:
        types = [str(ph.placeholder_format.type) for ph in lay.placeholders]
        if not any("TITLE" in t and "SUB" not in t for t in types):
            continue
        nm = (lay.name or "").lower()
        s = len(types) - (10 if ("title only" in nm or "כותרת בלבד" in nm) else 0)
        if score is None or s < score:
            best, score = lay, s
    return best or prs.slide_layouts[len(prs.slide_layouts) - 1]


def render_pptx(specs, base=None):
    """One slide per included spec. `base` (bytes) = the client's design file; without it a plain 16:9 deck."""
    if base:
        prs = _open_base(base)
        _clear_slides(prs)
        layout = _pick_layout(prs)
    else:
        prs = Presentation()
        prs.slide_width, prs.slide_height = Inches(_W), Inches(_H)
        layout = prs.slide_layouts[6]
    k = min(prs.slide_width / 914400 / _W, prs.slide_height / 914400 / _H)
    for s in specs:
        if s.get("include", True):
            _add_slide(prs, layout, s, k)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
