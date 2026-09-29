# -*- coding: utf-8 -*-
"""svr_run — step 2: compute every level and write the findings workbook.

    python svr_run.py <file.sav> <mapping.json> --out <Findings.xlsx> [--campaign-id I360-2026-0XX]

Workbook sheets (RTL, Shiluv navy/gold):
  README · ממצאים (one table per question; the summary variables sit at the bottom of each table) ·
  משתנים מסכמים (flat list of every dictionary slot computed) · DATA_לייבוא (5-column paste format for
  impact360-master-import) · הגדרות (mapping used) · בקרות · לא חושב
"""
import argparse
import datetime
import json
import os
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import svr_compute as C  # noqa: E402
import svr_lib as L  # noqa: E402

NAVY, GOLD, LGOLD, LGREY, WHITE = "1F3864", "BF9000", "FFF2CC", "F2F2F2", "FFFFFF"
F_HDR = Font(name="Assistant", bold=True, color=WHITE, size=11)
F_TXT = Font(name="Assistant", size=10)
F_BOLD = Font(name="Assistant", size=10, bold=True)
F_NOTE = Font(name="Assistant", size=9, italic=True, color="7F7F7F")
FILL_NAVY = PatternFill("solid", fgColor=NAVY)
FILL_GOLD = PatternFill("solid", fgColor=GOLD)
FILL_LGOLD = PatternFill("solid", fgColor=LGOLD)
FILL_GREY = PatternFill("solid", fgColor=LGREY)
FILL_RED = PatternFill("solid", fgColor="FFC7CE")
FILL_GREEN = PatternFill("solid", fgColor="C6EFCE")
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
RIGHT = Alignment(horizontal="right", vertical="center", wrap_text=True, readingOrder=2)
MIN_N = 30


DISPLAY = ["sample", "exposed", "notexposed", "customers", "noncust"]      # column order -> letters A..E
LETTER = {lv: chr(65 + i) for i, lv in enumerate(DISPLAY)}
PARTNER = {"exposed": "notexposed", "notexposed": "exposed", "customers": "noncust", "noncust": "customers"}
NCOL = 3 + 2 * len(DISPLAY)          # label, united, 5 x (value, letters), note


def sig_letters(row, lvl):
    """Letters of the column(s) this column is significantly HIGHER than: CAPITAL = 95%, small = 90%.
    Pairs: B(exposed) vs C(not exposed), D(customers) vs E(non-customers). Base >= 30 in both."""
    ref = PARTNER.get(lvl)
    if not ref:
        return ""
    a, b = row["vals"][lvl], row["vals"][ref]
    if a[0] is None or b[0] is None:
        return ""
    z = L.z_prop(a[0], a[1], b[0], b[1], MIN_N) if row["kind"] == "pct" else L.z_mean(a[0], a[2], a[1], b[0], b[2], b[1], MIN_N)
    if z > 1.96:
        return LETTER[ref]
    if z > 1.645:
        return LETTER[ref].lower()
    return ""


def fmt_for(row):
    return "0.00" if row["kind"] == "mean" else "0.0"


def style_hdr(ws, r, c1, c2, fill=FILL_NAVY):
    for c in range(c1, c2 + 1):
        cell = ws.cell(r, c)
        cell.fill, cell.font, cell.alignment, cell.border = fill, F_HDR, CENTER, BOX


# --------------------------------------------------------------------------- sheets
def sheet_findings(wb, ctx):
    ws = wb.create_sheet("ממצאים")
    ws.sheet_view.rightToLeft = True
    ws.sheet_view.showGridLines = False
    widths = [46, 30] + [9, 5] * len(DISPLAY) + [44]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "C1"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    bases = ctx.bases()
    r = 1
    ws.cell(r, 1, f"ממצאי סקר אפקטיביות — {ctx.map['project'].get('name') or ctx.map['project'].get('brand') or ''} "
                  f"| {ctx.map['project'].get('campaign_id', '')} | SAV: {ctx.map['project'].get('sav', '')}").font = Font(name="Assistant", bold=True, size=14, color=NAVY)
    r += 1
    ws.cell(r, 1, "מובהקות: אות = העמודה שמולה הערך מובהק גבוה יותר. אות גדולה = 95%, אות קטנה = 90%. השוואות: B מול C (נחשפים / לא נחשפים), "
                  "D מול E (לקוחות / לא לקוחות); בסיס ≥30. משתנים מסכמים (T2B/TOP/נטו/אינדקסים) בראש כל טבלה, על רקע זהב.").font = F_NOTE
    r += 2
    last = NCOL
    for t in ctx.tables:
        rows = t["rows"]
        if not rows:
            continue
        ws.cell(r, 1, f"{t['title']}  ·  {t['key']}" + (f"  ·  [{','.join(t['sav_vars'][:3])}{'…' if len(t.get('sav_vars', [])) > 3 else ''}]" if t.get("sav_vars") else ""))
        style_hdr(ws, r, 1, last, FILL_NAVY)
        ws.cell(r, 1).alignment = RIGHT
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=last)
        r += 1
        if t.get("question"):
            ws.cell(r, 1, t["question"][:230]).font = F_NOTE
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=last)
            ws.cell(r, 1).alignment = RIGHT
            r += 1
        # header: column letters, then level names
        ws.cell(r, 1, "עמודה")
        for k, lv in enumerate(DISPLAY):
            ws.cell(r, 3 + 2 * k, LETTER[lv])
            ws.merge_cells(start_row=r, start_column=3 + 2 * k, end_row=r, end_column=4 + 2 * k)
        style_hdr(ws, r, 1, last, FILL_NAVY)
        r += 1
        hdr = ["תשובה", "קוד (united)"]
        for lv in DISPLAY:
            hdr += [C.LEVEL_HE[lv], ""]
        hdr += ["הערה"]
        for i, h in enumerate(hdr, 1):
            ws.cell(r, i, h)
        style_hdr(ws, r, 1, last, FILL_GOLD)
        for k in range(len(DISPLAY)):
            ws.merge_cells(start_row=r, start_column=3 + 2 * k, end_row=r, end_column=4 + 2 * k)
        r += 1
        ws.cell(r, 1, "בסיס (N)").font = F_BOLD
        for k, lv in enumerate(DISPLAY):
            c = ws.cell(r, 3 + 2 * k, bases[lv])
            c.font, c.alignment = F_BOLD, CENTER
            ws.merge_cells(start_row=r, start_column=3 + 2 * k, end_row=r, end_column=4 + 2 * k)
        for i in range(1, last + 1):
            ws.cell(r, i).fill = FILL_GREY
            ws.cell(r, i).border = BOX
        r += 1
        # summary variables FIRST, then the answer breakdown
        summ = [x for x in rows if x["section"] == "summary"]
        body = [x for x in rows if x["section"] != "summary"]
        for group, is_sum, title in ((summ, True, "משתנים מסכמים"), (body, False, "פירוט תשובות")):
            if not group:
                continue
            if summ and body:
                ws.cell(r, 1, title)
                style_hdr(ws, r, 1, last, FILL_GOLD if is_sum else FILL_NAVY)
                ws.cell(r, 1).alignment = RIGHT
                ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=last)
                r += 1
            for x in group:
                ws.cell(r, 1, x["label"]).alignment = RIGHT
                ws.cell(r, 2, x["united"]).alignment = CENTER
                for k, lv in enumerate(DISPLAY):
                    v = x["vals"][lv]
                    c = ws.cell(r, 3 + 2 * k, None if v[0] is None else round(v[0], 3))
                    c.number_format = fmt_for(x)
                    c.alignment = CENTER
                    if v[0] is not None and v[1] < MIN_N:
                        c.font = Font(name="Assistant", size=10, color="C00000", italic=True)   # low base
                    ws.cell(r, 4 + 2 * k, sig_letters(x, lv)).alignment = CENTER
                note = x["note"]
                if x["status"]:
                    note = (note + " | " if note else "") + f"סטטוס מילון: {x['status']}"
                ws.cell(r, last, note).font = F_NOTE
                for i in range(1, last + 1):
                    cc = ws.cell(r, i)
                    cc.border = BOX
                    red = cc.font is not None and cc.font.color is not None and cc.font.color.rgb == "00C00000"
                    if i == last:
                        pass
                    elif red:
                        cc.font = Font(name="Assistant", size=10, italic=True, bold=is_sum, color="C00000")
                    elif i > 2 and (i - 3) % 2 == 1:
                        cc.font = Font(name="Assistant", size=10, bold=True, color=GOLD)     # significance letters
                    else:
                        cc.font = Font(name="Assistant", size=10, bold=is_sum)
                    if is_sum:
                        cc.fill = FILL_LGOLD
                r += 1
        for n in t.get("notes", []):
            ws.cell(r, 1, "⚠ " + n).font = Font(name="Assistant", size=9, color="C00000")
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=last)
            ws.cell(r, 1).alignment = RIGHT
            r += 1
        r += 2
    return ws


def sheet_summary(wb, ctx):
    ws = wb.create_sheet("משתנים מסכמים")
    ws.sheet_view.rightToLeft = True
    hdr = ["united", "VAR_NAME", "סלוט", "תווית (מילון)", "תפקיד"]
    for lv in C.LEVELS:
        hdr += [C.LEVEL_HE[lv], f"n {C.LEVEL_HE[lv]}"]
    hdr += ["בסיס ל-DATA", "סטטוס מילון", "הערה"]
    ws.append(hdr)
    style_hdr(ws, 1, 1, len(hdr))
    ws.freeze_panes = "C2"
    for t in ctx.tables:
        for x in t["rows"]:
            if not x["united"]:
                continue
            line = [x["united"], x["var"], x["slot"], x["canon"] or x["label"], x["role"]]
            for lv in C.LEVELS:
                v = x["vals"][lv]
                line += [None if v[0] is None else round(v[0], 3), v[1]]
            line += [C.LEVEL_HE.get(x["export"], x["export"]), x["status"], x["note"]]
            ws.append(line)
            rr = ws.max_row
            for k in range(4):
                ws.cell(rr, 6 + 2 * k).number_format = fmt_for(x)
            if x["status"] == "Don't import":
                for i in range(1, len(line) + 1):
                    ws.cell(rr, i).fill = FILL_GREY
    for i, w in enumerate([26, 24, 7, 44, 10] + [10, 8] * 4 + [12, 14, 60], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    return ws


def sheet_data(wb, ctx):
    """5-column paste format of impact360-master-import DATA: CAMPAIGN_ID | VAR_NAME | ANSWER_LABEL | VALUE | united
    Sample base for Sample-base variables, exposed base for the *_E twins / MAIN MESSAGE_TAKEOUT#01.
    Customer / non-customer cuts are NEVER exported (sub-segments the dictionary does not define)."""
    ws = wb.create_sheet("DATA_לייבוא")
    ws.sheet_view.rightToLeft = True
    cid = ctx.map["project"].get("campaign_id", "")
    ws.append(["CAMPAIGN_ID", "VAR_NAME", "ANSWER_LABEL", "VALUE", "united", "‖", "בסיס", "n", "הערה"])
    style_hdr(ws, 1, 1, 9)
    dropped = 0
    for t in ctx.tables:
        for x in t["rows"]:
            if not x["united"] or x["section"] == "analysis":
                continue
            if x["status"] == "Don't import":
                dropped += 1
                continue
            v = x["vals"][x["export"] if x["export"] in x["vals"] else "sample"]
            if v[0] is None:
                continue
            val = round(v[0], 2) if x["kind"] == "mean" else round(v[0], 1)
            ws.append([cid, x["var"], x["canon"] or x["label"], val, x["united"], "", C.LEVEL_HE[x["export"]], v[1], x["note"][:120]])
    ws.freeze_panes = "A2"
    for i, w in enumerate([16, 26, 44, 10, 26, 3, 10, 6, 60], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ctx.checks.append(("DATA_לייבוא: שורות 'Don't import' שהושמטו", str(dropped), "OK"))
    return ws


def sheet_mapping(wb, ctx):
    ws = wb.create_sheet("הגדרות")
    ws.sheet_view.rightToLeft = True
    M = ctx.map
    ws.append(["הגדרות הרצה"])
    ws["A1"].font = Font(name="Assistant", bold=True, size=13, color=NAVY)
    ws.append(["קובץ SAV", M["project"].get("sav")])
    ws.append(["מילון", os.path.basename(M["project"].get("dictionary", ""))])
    ws.append(["N כולל", ctx.n])
    ws.append(["משקל", M["project"].get("weight_var") or "ללא (לא משוקלל)"])
    ex = M.get("exposure") or {}
    ws.append(["הגדרת נחשפים", ex.get("label"), "איחוד: " + ", ".join(str(c['var'] if not isinstance(c['var'], list) else f"{c['var'][0]}..(x{len(c['var'])})") for c in ex.get("components", []))])
    cu = M.get("customer") or {}
    ws.append(["הגדרת לקוחות", cu.get("option_text", ""), f"{cu.get('var', '')} = {cu.get('customer_values', '')}; ריקים → {cu.get('nan_as', '')}"])
    ws.append([])
    ws.append(["בלוק SAV", "סוג", "משתנה מילון", "ביטחון מיפוי", "# משתני SAV", "לבדיקה"])
    style_hdr(ws, ws.max_row, 1, 6)
    for e in M["questions"]:
        ws.append([e["key"], e.get("type"), e.get("dict_var") or "—", e.get("confidence"), len(e["vars"]), "; ".join(e.get("review", []))])
        if not e.get("include", True):
            for i in range(1, 7):
                ws.cell(ws.max_row, i).fill = FILL_GREY
    ws.append([])
    ws.append(["בלוקים שלא נכללו", "סיבה"])
    style_hdr(ws, ws.max_row, 1, 2)
    for s in M.get("skipped", []):
        ws.append([s["block"], s["reason"]])
    for i, w in enumerate([34, 40, 34, 16, 12, 90], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    return ws


def sheet_checks(wb, ctx):
    ws = wb.create_sheet("בקרות")
    ws.sheet_view.rightToLeft = True
    ws.append(["בדיקה", "תוצאה", "סטטוס"])
    style_hdr(ws, 1, 1, 3)
    for c in ctx.checks:
        ws.append(list(c))
        ws.cell(ws.max_row, 3).fill = FILL_GREEN if c[2] == "OK" else FILL_RED
    low = 0
    for t in ctx.tables:
        for x in t["rows"]:
            if x["united"] and x["vals"]["sample"][0] is not None and x["vals"]["sample"][1] < MIN_N:
                low += 1
    ws.append(["שורות עם בסיס מדגם < 30", str(low), "OK" if low == 0 else "שים לב"])
    for m in ctx.log:
        ws.append(["הרצה", m, "שגיאה"])
        ws.cell(ws.max_row, 3).fill = FILL_RED
    for i, w in enumerate([60, 70, 12], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    return ws


def sheet_not_computed(wb, ctx):
    ws = wb.create_sheet("לא חושב")
    ws.sheet_view.rightToLeft = True
    ws.append(["VAR_NAME", "מודול", "סוג", "בסיס", "סיבה"])
    style_hdr(ws, 1, 1, 5)
    done = {x["var"] for t in ctx.tables for x in t["rows"] if x["united"]}
    for v, d in ctx.vars.items():
        if v in done:
            continue
        typ = d["type"] or ""
        if "INDEX" in typ or "Computed" in d["base"] or "RATIO" in typ:
            reason = "מדד מחושב — נגזר במנוע ה-LIVE של impact360-master-import מתוך שורות ה-DATA"
        elif v.endswith("_E"):
            reason = "תאום בסיס-נחשפים — נוצר רק אם המשתנה הבסיסי חושב"
        else:
            reason = "השאלה אינה קיימת ב-SAV / לא מופתה (אומניבוס?/לא נשאלה בסקר זה)"
        ws.append([v, d["module"], typ, d["base"], reason])
    for i, w in enumerate([34, 22, 30, 22, 80], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    return ws


def sheet_readme(wb, ctx):
    ws = wb.active
    ws.title = "README"
    ws.sheet_view.rightToLeft = True
    b = ctx.bases()
    lines = [
        ("Impact360 — הרצת ממצאים מקובץ SAV", True),
        (f"נוצר: {datetime.datetime.now():%d/%m/%Y %H:%M} | קמפיין: {ctx.map['project'].get('campaign_id') or '—'} | מותג: {ctx.map['project'].get('brand') or '—'}", False),
        ("", False),
        ("רמות הניתוח", True),
        (f"מדגם: N={b['sample']}", False),
        (f"נחשפים ל-1+ מדיה (Total Exposed = איחוד ערוצי המדיה): N={b['exposed']}", False),
        (f"לקוחות (קנו את המותג ב-3 החודשים האחרונים): N={b['customers']}", False),
        (f"לא לקוחות: N={b['noncust']}", False),
        ("", False),
        ("איך קוראים את הקובץ", True),
        ("ממצאים — טבלה לכל שאלה; עמודות = 4 הרמות; בתחתית כל טבלה 'משתנים מסכמים' (T2B, TOP, נטו, אינדקסים) על רקע זהב.", False),
        ("משתנים מסכמים — רשימה שטוחה של כל סלוט מילון שחושב (united), לכל הרמות, עם n.", False),
        ("DATA_לייבוא — פורמט 5 העמודות של impact360-master-import (רמת מדגם; תאומי _E ו-MAIN MESSAGE_TAKEOUT#01 מרמת הנחשפים). חיתוכי לקוחות/לא-לקוחות אינם מיוצאים.", False),
        ("בקרות — תוצאות בדיקות אוטומטיות (איחוד חשיפה מול משתנה ה-DP, סכומי 100, טווח ATTENTION וכו').", False),
        ("לא חושב — משתני מילון שלא חושבו וסיבה (מדדים מחושבים נגזרים במנוע LIVE).", False),
        ("", False),
        ("כללים ומגבלות", True),
        ("אחוזים 0-100. DESCRIBE#21-#27 הם ממוצעי ספירה (לא ×100); ATTENTION_100 = #27 ÷ 42 × 100 במנוע LIVE.", False),
        ("מובהקות: z-test; אות גדולה = 95%, קטנה = 90%; B מול C (נחשפים/לא נחשפים), D מול E (לקוחות/לא לקוחות); בסיס מינימלי 30.", False),
        ("בסיס הנחשפים = איחוד ערוצי המדיה (Total Exposed), ולא בהכרח עמודת 'נחשפו' בטבלת DP המבוססת על שאלה בודדת — תאומי _E ו-MAIN MESSAGE_TAKEOUT#01 מושפעים.", False),
        ("שאלות שנשאלו רק לחלק מהמדגם: האחוזים על הנשאלים (הערה בתחתית הטבלה); שאלות חשיפה-מותנית (SEMIAEX/UNEXPOSEB/SLOGAN/SPONTIMPRESSION) על כלל המדגם.", False),
        ("DESCRIBE#26 (TOTAL) מחושב כספירת כל 20 התכונות — תואם לסה\"כ בטבלת ה-DP, אך לא מוגדר בבייבל.", False),
        ("קודי הנטו של פתוחות (LIKES/DISLIKES/SLOGAN/SPONTIMPRESSION/SEMIAEX-VD) נגזרים מקודים שאושרו בהגדרות — בדוק לפני קליטה לבנצ'מארק.", False),
        ("החוקר מאמת ומעתיק ידנית לבנצ'מארק; הסקיל אינו כותב לבנצ'מארק.", False),
    ]
    for i, (txt, bold) in enumerate(lines, 1):
        c = ws.cell(i, 1, txt)
        c.font = Font(name="Assistant", size=13 if i == 1 else 11, bold=bold, color=NAVY if bold else "000000")
        c.alignment = RIGHT
    ws.column_dimensions["A"].width = 140
    return ws


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sav")
    ap.add_argument("mapping")
    ap.add_argument("--out", required=True)
    ap.add_argument("--campaign-id", default=None)
    ap.add_argument("--nets", default=None, help="nets.json exported by the Net Builder artifact (merged into the mapping)")
    a = ap.parse_args()
    with open(a.mapping, encoding="utf-8") as f:
        mapping = json.load(f)
    if a.campaign_id:
        mapping["project"]["campaign_id"] = a.campaign_id
    if a.nets:
        with open(a.nets, encoding="utf-8") as f:
            nj = json.load(f)
        byk = {e["key"]: e for e in mapping["questions"]}
        for k, b in nj.get("blocks", {}).items():
            if k in byk:
                byk[k].setdefault("nets", {}).update(b.get("nets", {}))
                if b.get("base"):
                    byk[k]["base"] = b["base"]
    vars_, codes = L.load_dictionary(mapping["project"]["dictionary"])
    df, meta = L.load_sav(a.sav)
    ctx = C.Ctx(df, meta, vars_, codes, mapping)
    C.run_all(ctx)
    wb = Workbook()
    sheet_readme(wb, ctx)
    sheet_findings(wb, ctx)
    sheet_summary(wb, ctx)
    sheet_data(wb, ctx)
    sheet_mapping(wb, ctx)
    sheet_checks(wb, ctx)
    sheet_not_computed(wb, ctx)
    # text that starts with "=" (notes such as "= #02 ...") must stay text, otherwise Excel drops it as a broken formula
    for w in wb.worksheets:
        for row in w.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("="):
                    c.data_type = "s"
    wb.save(a.out)
    n_rows = sum(1 for t in ctx.tables for x in t["rows"] if x["united"])
    bad = [c for c in ctx.checks if c[2] not in ("OK",)]
    print(f"tables={len(ctx.tables)} dictionary-slots={n_rows} checks={len(ctx.checks)} flagged={len(bad)} errors={len(ctx.log)}")
    for c in bad + [("log", m, "ERR") for m in ctx.log]:
        print("  !", c)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
