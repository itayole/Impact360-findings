# -*- coding: utf-8 -*-
"""svr_compute — turns (SAV + confirmed mapping.json + bench dictionary) into result tables.

A *row* is one dictionary answer slot (united = VAR#SLOT) or an analysis-only line; it carries a value+base for
each analysis level.  Levels:  sample | exposed | customers | noncust  (+ notexposed, used only for significance).
"""
import re
from collections import OrderedDict

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

from . import lib as L

LEVELS = ["sample", "exposed", "customers", "noncust"]
ALL_LEVELS = LEVELS + ["notexposed"]
LEVEL_HE = {"sample": "מדגם", "exposed": "נחשפים", "customers": "לקוחות", "noncust": "לא לקוחות",
            "notexposed": "לא נחשפים"}
DIGITAL_RECS = {"RECVDG", "RECVSO", "RECIMB", "RECIMF", "RECINF"}
NEXT_ACTION_TIERS = {1: 100, 2: 70, 3: 40, 4: 0, 5: 0}
TRUSTED = ("manual", "exact", "tag", "template", "alias")   # matches allowed into `united` without a human decision
SUMMARY_ROLES = {"T2B", "TOP", "B3B", "Low3", "MEAN", "INDEX"}


def uid(var, slot):
    return f"{var}#{int(slot):02d}"


class Ctx:
    def __init__(self, df, meta, vars_, codes, mapping):
        self.df, self.meta, self.vars, self.codes, self.map = df, meta, vars_, codes, mapping
        self.vl = meta.variable_value_labels or {}
        self.labels = dict(zip(meta.column_names, meta.column_labels))
        wv = (mapping.get("project") or {}).get("weight_var")
        self.w = df[wv].fillna(0).astype(float).values if wv else None
        self.n = len(df)
        self.tables, self.checks, self.log = [], [], []
        self.masks = {}
        self.exposure_note = ""
        self._build_masks()

    # ---------------------------------------------------------------- levels
    def _build_masks(self):
        df, M = self.df, self.map
        self.masks["sample"] = np.ones(self.n, bool)
        ex = M.get("exposure") or {}
        expo = np.zeros(self.n, bool)
        used = []
        for c in ex.get("components", []):
            if c.get("enabled", True) is False:
                continue
            vals = c.get("values", [1])
            if c.get("kind") == "any_of" or isinstance(c["var"], list):
                cols = c["var"] if isinstance(c["var"], list) else [c["var"]]
                m = np.zeros(self.n, bool)
                for v in cols:
                    m |= df[v].isin(vals).values
            else:
                m = df[c["var"]].isin(vals).values
            expo |= m
            used.append(c)
        self.masks["exposed"] = expo
        self.masks["notexposed"] = ~expo
        self.expo_components = used
        vv = ex.get("verify_var")
        if vv and vv in df:
            agree = int((expo == (df[vv] == 1).values).sum())
            self.checks.append(("חשיפה: איחוד הערוצים מול משתנה ה-DP " + vv, f"{agree}/{self.n} משיבים תואמים",
                                "OK" if agree == self.n else "בדוק"))
        cu = M.get("customer")
        if cu and cu.get("var") in df:
            ser = df[cu["var"]]
            cm = ser.isin(cu.get("customer_values", [1])).values
            if cu.get("nan_as", "noncustomer") == "noncustomer":
                nm = ~cm
            else:
                nm = ser.isin(cu.get("noncustomer_values", [0])).values
            self.masks["customers"], self.masks["noncust"] = cm, nm
            self.checks.append(("לקוחות (שימוש 3 חודשים): " + cu["var"],
                                f"לקוחות={int(cm.sum())} | לא לקוחות={int(nm.sum())} | ריקים שטופלו כלא-לקוחות={int(ser.isna().sum())}", "OK"))
        else:
            self.masks["customers"] = np.zeros(self.n, bool)
            self.masks["noncust"] = np.zeros(self.n, bool)
            self.checks.append(("לקוחות/לא לקוחות", "לא הוגדר משתנה שימוש — העמודות ריקות", "שים לב"))

    def bases(self):
        out = {}
        for k in ALL_LEVELS:
            out[k] = int(self.masks[k].sum())
        return out

    # ---------------------------------------------------------------- helpers
    def per_level(self, fn):
        """fn(mask) -> (value, n[, sd])"""
        out = {}
        for k in ALL_LEVELS:
            r = fn(self.masks[k])
            out[k] = r if len(r) == 3 else (r[0], r[1], None)
        return out

    def pct(self, cond, valid=None):
        valid = np.ones(self.n, bool) if valid is None else valid
        return self.per_level(lambda m: L.wpct(cond, valid & m, self.w))

    def mean(self, values, valid=None):
        valid = np.ones(self.n, bool) if valid is None else valid

        def f(m):
            v, n = L.wmean(values, valid & m, self.w)
            sd = float(np.std(values[valid & m], ddof=1)) if n > 1 else None
            return v, n, sd
        return self.per_level(f)

    def item_codes(self, dv):
        return {c["slot"]: c for c in self.codes.get(dv or "", []) if isinstance(c["slot"], int)}

    def row(self, var, slot, label, vals, section="item", role="", note="", export="sample", united=None, kind="pct"):
        c = self.item_codes(var).get(slot) if var else None
        if united is None:
            united = uid(var, slot) if (var and c) else ""
        status = c["status"] if c else ""
        return dict(united=united, var=var if c else "", slot=slot, label=label,
                    canon=(c["label"] if c else ""), vals=vals, section=section, role=role or (c["role"] if c else ""),
                    note=note, status=status, export=export, kind=kind)


# =============================================================================
# per-type handlers
# =============================================================================

_IMG = re.compile(r"\[[^\]]*\.(?:jpg|jpeg|png|gif)\]", re.I)


def clean_label(s):
    return _IMG.sub("", str(s)).strip()


def sav_label(ctx, var, val):
    return clean_label((ctx.vl.get(var) or {}).get(val, (ctx.vl.get(var) or {}).get(float(val), val)))


def do_categorical(ctx, e):
    var = e["vars"][0]
    ser = ctx.df[var]
    valid = ser.notna().values
    dv = e.get("dict_var")
    vs = {float(k): v for k, v in (e.get("value_slots") or {}).items()}
    slots = ctx.item_codes(dv)
    slot_arr = ser.map(lambda x: vs.get(float(x)) if pd.notna(x) else None)
    slot_num = pd.to_numeric(slot_arr, errors="coerce").values
    rows, seen = [], set()
    for val in sorted((ctx.vl.get(var) or {}).keys()):
        s = vs.get(float(val))
        cond = ser.values == val
        cond = np.where(pd.isna(ser.values), False, cond)
        lab = sav_label(ctx, var, val)
        if s is not None and s in slots and slots[s]["role"] in ("scale", "item", "DK"):
            rows.append(ctx.row(dv, s, lab, ctx.pct(cond, valid)))
            seen.add(s)
        else:
            rows.append(ctx.row(None, 0, lab, ctx.pct(cond, valid), section="analysis", united=""))
    for s, c in slots.items():   # dictionary answer slots with no SAV option
        if c["role"] in ("scale", "item") and s not in seen and dv and not (dv == "MAIN MESSAGE_TAKEOUT" and s in (1, 6)):
            rows.append(ctx.row(dv, s, c["label"], {k: (None, 0, None) for k in ALL_LEVELS}, note="לא נשאל בשאלון (אין אפשרות תשובה תואמת ב-SAV)"))
    # summary slots
    if dv:
        summ = [
            ("TOP", lambda: np.isin(slot_num, [1])), ("T2B", lambda: np.isin(slot_num, [1, 2])),
            ("B3B", lambda: np.isin(slot_num, [3, 4, 5])), ("Low3", lambda: np.isin(slot_num, [1, 2, 3])),
        ]
        for role, cf in summ:
            for s, c in slots.items():
                if c["role"] == role:
                    cond = cf() & valid
                    rows.append(ctx.row(dv, s, c["label"], ctx.pct(cond, valid), section="summary"))
        for s, c in slots.items():
            if c["role"] == "MEAN":
                ok = valid & np.isin(slot_num, [1, 2, 3, 4, 5])
                rows.append(ctx.row(dv, s, c["label"], ctx.mean(np.nan_to_num(slot_num), ok), section="summary", kind="mean",
                                    note="ממוצע 1-5 (1=הכי חיובי). " + ("Don't import" if c["status"] == "Don't import" else "")))
    # scale polarity / point-count sanity
    if dv and e.get("type") == "scale":
        vlab = ctx.vl.get(var) or {}
        if vlab and 1 in slots and 5 in slots:
            first, last = sorted(vlab)[0], sorted(vlab)[-1]
            s_first = fuzz.token_set_ratio(str(vlab[first]), slots[1]["label"])
            s_last = fuzz.token_set_ratio(str(vlab[first]), slots[5]["label"])
            if s_last > s_first + 25:
                ctx.checks.append((f"{var}: כיווניות סקאלה", "קוד 1 ב-SAV דומה יותר לקצה השלילי במילון — ייתכן היפוך", "בדוק"))
    # MAIN MESSAGE_TAKEOUT specials
    if dv == "MAIN MESSAGE_TAKEOUT":
        by = {r["slot"]: r for r in rows if r["united"]}
        if 2 in by:
            rows.append(ctx.row(dv, 1, "מסר עיקרי מנחשפים",
                                {k: (by[2]["vals"]["exposed"] if k == "sample" else by[2]["vals"][k]) for k in ALL_LEVELS},
                                section="summary", export="exposed", note="= #02 בקרב הנחשפים; ל-DATA נלקח מעמודת הנחשפים"))
        firsts = [by[s] for s in (2, 3, 4) if s in by]
        if firsts:
            mx = {k: (max((r["vals"][k][0] or 0) for r in firsts), firsts[0]["vals"][k][1], None) for k in ALL_LEVELS}
            rows.append(ctx.row(dv, 6, "שיעור המסר הגבוה ביותר בציון ראשון", mx, section="summary", note="MAX על #02-#04"))
    return rows


def do_multi(ctx, e, coded=False):
    vars_ = e["vars"]
    names = {k: clean_label(v) for k, v in (e.get("option_names") or e.get("code_names") or {}).items()}
    osl = {k: int(v) for k, v in (e.get("option_slots") or {}).items()}
    dv = e.get("dict_var")
    slots = ctx.item_codes(dv)
    blk = ctx.df[vars_]
    asked = blk.notna().any(axis=1).values
    if asked.mean() >= 0.98:            # a handful of all-empty rows = "ticked nothing", not "not asked"
        asked = np.ones(ctx.n, bool)
    if e.get("base") == "all":          # skip-logic follow-ups measured on the TOTAL sample (not-asked = did not mention)
        asked = np.ones(ctx.n, bool)
    flags = {v: (ctx.df[v] == 1).values for v in vars_}
    rows = []
    for v in vars_:
        s = osl.get(v)
        lab = names.get(v) or v
        if s and s in slots:
            rows.append(ctx.row(dv, s, lab, ctx.pct(flags[v], asked)))
        else:
            rows.append(ctx.row(None, 0, lab, ctx.pct(flags[v], asked), section="analysis", united=""))
    # ---- nets
    nets = e.get("nets") or {}
    for u, spec in nets.items():
        var, _, slot = u.partition("#")
        inc = spec.get("include") or [v for v in vars_ if v not in set(spec.get("exclude", []))]
        cond = np.zeros(ctx.n, bool)
        for v in inc:
            cond |= flags[v]
        if not slot.isdigit() or int(slot) not in ctx.item_codes(var):      # user-defined net without a dictionary slot
            rows.append(ctx.row(None, 0, spec.get("label", u), ctx.pct(cond, asked), section="summary", united="",
                                note=spec.get("note", "סיכום מוגדר-משתמש — ללא סלוט במילון (לא ייצא ל-DATA)")))
            continue
        rows.append(ctx.row(var, int(slot), (ctx.item_codes(var).get(int(slot)) or {}).get("label", u), ctx.pct(cond, asked),
                            section="summary", note=spec.get("note", "נטו: לפחות קוד מהותי אחד" if not spec.get("include") else "נטו לפי קודים שהוגדרו")))
    # ---- default any-of net for single-slot exposure style variables
    if not nets and dv and list(slots) == [1] and not osl and not coded:
        exc = set(e.get("net_exclude", [])) | {v for v, n in names.items() if any(w in n for w in ("לא ראיתי", "אף אחד", "לא עוקב", "אין לי"))}
        cond = np.zeros(ctx.n, bool)
        for v in vars_:
            if v not in exc:
                cond |= flags[v]
        rows.append(ctx.row(dv, 1, slots[1]["label"], ctx.pct(cond, asked), section="summary", note="נטו: ראה לפחות אחד (למעט 'אף אחד')"))
    # ---- NEXT_ACTION#96 (max method)
    if dv == "NEXT_ACTION" and osl:
        sc = np.zeros(ctx.n)
        for v, s in osl.items():
            sc = np.maximum(sc, np.where(flags[v], NEXT_ACTION_TIERS.get(s, 0), 0))
        rows.append(ctx.row(dv, 96, "NEXT_ACTION (max method)", ctx.mean(sc, asked), section="summary", kind="mean",
                            note="ממוצע ברמת משיב של הדרגה הגבוהה שסומנה (100/70/40/0/0)"))
    return rows


def do_message_takeout(ctx, e):
    """Total MESSAGE_TAKEOUT#01-#04 = picked in MAIN_MESSAGE_TAKEOUT OR ticked in the 'additional' multi; #05 = max."""
    dv = e.get("dict_var") or "Total MESSAGE_TAKEOUT"
    mainv = e.get("main_var", "MAIN_MESSAGE_TAKEOUT")
    osl = {k: int(v) for k, v in (e.get("option_slots") or {}).items()}
    pos = {int(k): int(v) for k, v in (e.get("main_positions") or {}).items()}
    names = e.get("option_names") or {}
    main = ctx.df[mainv]
    asked = main.notna().values
    slots = ctx.item_codes(dv)
    rows, per_slot = [], {}
    for s in (1, 2, 3, 4):
        cond = np.zeros(ctx.n, bool)
        for val, sl in pos.items():
            if sl == s:
                cond |= (main == val).values
        for v, sl in osl.items():
            if sl == s:
                cond |= (ctx.df[v] == 1).values
        per_slot[s] = cond
        rows.append(ctx.row(dv, s, (slots.get(s) or {}).get("label", f"מסר {s}"), ctx.pct(cond, asked)))
    if 5 in slots:
        vals = {}
        for k in ALL_LEVELS:
            best = 0.0; n0 = 0
            for s in (1, 2, 3):
                v, n = L.wpct(per_slot[s], asked & ctx.masks[k], ctx.w)
                best = max(best, v or 0.0); n0 = n
            vals[k] = (best, n0, None)
        rows.append(ctx.row(dv, 5, slots[5]["label"], vals, section="summary", note="MAX על #01-#03"))
    # MEI depth (no dictionary slot)
    depth = sum(per_slot[s].astype(float) for s in (1, 2, 3)) / 3.0 * 100.0
    rows.append(ctx.row(None, 0, "MEI_DEPTH — ממוצע (מס' מסרי בריף שצוינו ÷ 3 × 100)", ctx.mean(depth, asked), section="analysis",
                        united="", kind="mean", note="אין סלוט במילון — לשימוש חישוב MEI בלבד"))
    return rows


def do_describe(ctx, e):
    vars_ = e["vars"]
    names = e.get("attr_names") or {}
    slots = ctx.item_codes("DESCRIBE")
    canon = {c["label"].strip(): s for s, c in slots.items() if s <= 20}
    flags, world_of, rows = {}, {}, []
    unmatched = []
    for v in vars_:
        attr = names.get(v, "").strip()
        flags[v] = (ctx.df[v] == 1).values
        s = canon.get(attr)
        if s is None:
            unmatched.append(attr or v)
            rows.append(ctx.row(None, 0, attr or v, ctx.pct(flags[v]), section="analysis", united=""))
            continue
        world_of[v] = L.DESCRIBE_WORLDS.get(attr, "-")
        rows.append(ctx.row("DESCRIBE", s, attr, ctx.pct(flags[v])))
    if unmatched:
        ctx.checks.append(("DESCRIBE: תכונות שלא זוהו מול המילון", "; ".join(unmatched), "בדוק"))
    fn = {}
    for w in L.WORLD_SLOT:
        cols = [v for v in vars_ if world_of.get(v) == w]
        fn[w] = sum(flags[v].astype(float) for v in cols) if cols else np.zeros(ctx.n)
        rows.append(ctx.row("DESCRIBE", L.WORLD_SLOT[w], w, ctx.mean(fn[w]), section="summary", kind="mean",
                            note=f"ממוצע מס' תכונות שנבחרו (0..{len(cols)}) — לא ×100"))
    total = sum(flags[v].astype(float) for v in vars_)
    rows.append(ctx.row("DESCRIBE", 26, "TOTAL", ctx.mean(total), section="summary", kind="mean",
                        note="הנחה: ספירת כל 20 התכונות — הגדרת #26 טרם אומתה בבייבל; לאמת"))
    att = (0.4 * fn["Magnetism"] + 0.2 * (fn["Emotional"] + fn["Dynamic"] + fn["Negative"])) * 10
    rows.append(ctx.row("DESCRIBE", 27, "ATTENTION (totalnewatt3)", ctx.mean(att), section="summary", kind="mean",
                        note="(0.4*fn1 + 0.2*(fn2+fn3+fn4))*10, טווח 0-42. ATTENTION_100 = ÷42×100 במנוע LIVE"))
    a = float(np.mean(att))
    ctx.checks.append(("DESCRIBE#27 בטווח 0-42", f"{a:.2f}", "OK" if 0 <= a <= 42 else "חריג"))
    return rows


HANDLERS = {"scale": do_categorical, "single": do_categorical, "multi": do_multi,
            "coded_open": lambda c, e: do_multi(c, e, coded=True), "describe": do_describe,
            "message_takeout": do_message_takeout}


# =============================================================================
def total_exposed_table(ctx):
    rows = []
    valid = np.ones(ctx.n, bool)
    rows.append(ctx.row("Total Exposed", 1, "סה\"כ חשיפה לקמפיין (איחוד ערוצי המדיה)", ctx.pct(ctx.masks["exposed"], valid), section="summary",
                        note="איחוד: " + ", ".join(str(c["var"] if not isinstance(c["var"], list) else f"{c['var'][0]}..") for c in ctx.expo_components)))
    dig = np.zeros(ctx.n, bool)
    any_dig = False
    dmap = {}
    for e in ctx.map["questions"]:
        if e.get("include", True) and e.get("dict_var") in DIGITAL_RECS:
            for v in e["vars"]:
                dmap[v] = True
    for c in ctx.expo_components:
        cols = c["var"] if isinstance(c["var"], list) else [c["var"]]
        if any(v in dmap for v in cols):
            any_dig = True
            for v in cols:
                dig |= ctx.df[v].isin(c.get("values", [1])).values
    if any_dig:
        rows.append(ctx.row("Total Exposed Digital", 1, "סה\"כ חשיפה דיגיטלית", ctx.pct(dig, valid), section="summary",
                            note="איחוד ערוצים עם משתנה מילון דיגיטלי (RECVDG/VSO/IMB/IMF/INF)"))
    return dict(key="TOTAL_EXPOSURE", title="חשיפה כוללת לקמפיין (Total Exposed)", question="נגזר מאיחוד שאלות החשיפה", dict_var="Total Exposed",
                type="derived", rows=rows, notes=[])


TWIN_NAMES = {"SPONTIMPRESSION": "SPONTIMP_E"}   # dictionary twin names that are not simply <VAR>_E


def twin_rows(ctx, tables):
    """X -> X_E : same measure, exposed base, for every computed slot whose X_E twin exists in the dictionary."""
    rows = []
    for t in tables:
        for r in list(t["rows"]):
            v = r["var"]
            tw = TWIN_NAMES.get(v, v + "_E")
            if not r["united"] or not v or v.endswith("_E") or tw not in ctx.codes:
                continue
            c = ctx.item_codes(tw).get(r["slot"])
            if not c:
                continue
            vals = {k: (r["vals"]["exposed"] if k == "sample" else r["vals"][k]) for k in ALL_LEVELS + ["notexposed"]}
            rows.append(ctx.row(tw, r["slot"], c["label"] + " — בקרב הנחשפים", vals, section="summary", export="exposed",
                                note="תאום בסיס-נחשפים (אבחוני בלבד); ל-DATA נלקח מעמודת הנחשפים"))
    if not rows:
        return []
    return [dict(key="TWINS_E", title="תאומי בסיס-נחשפים (_E)", question="אותו חישוב בקרב הנחשפים (הגדרת חשיפה: איחוד ערוצי המדיה)",
                 dict_var=None, type="twin", rows=rows, notes=["בסיס הנחשפים כאן = איחוד ערוצי המדיה (Total Exposed) ולא בהכרח בסיס 'נחשפים' ששימש בהרצות קודמות"])]


def run_all(ctx):
    tables = []
    for e in ctx.map["questions"]:
        if not e.get("include", True):
            continue
        if e.get("dict_var") and e.get("confidence") not in TRUSTED and not e.get("confirmed"):
            e = dict(e)
            e["review"] = list(e.get("review", [])) + [f"התאמה ({e.get('confidence')}) ל-{e['dict_var']} לא אושרה (confirmed:true חסר) — הטבלה הופקה כניתוח בלבד, ללא united"]
            e["dict_var"] = None
            e.pop("nets", None); e.pop("option_slots", None)
        h = HANDLERS.get(e.get("type"))
        if not h:
            ctx.log.append(f"{e['key']}: סוג לא נתמך {e.get('type')}")
            continue
        try:
            rows = h(ctx, e)
        except Exception as ex:  # keep going, surface the failure
            ctx.log.append(f"{e['key']}: שגיאה {type(ex).__name__}: {ex}")
            continue
        tables.append(dict(key=e["key"], title=(e.get("dict_var") or e["key"]), question=e.get("question", ""),
                           dict_var=e.get("dict_var"), type=e.get("type"), rows=rows, notes=e.get("review", []),
                           sav_vars=e["vars"], confidence=e.get("confidence", "")))
    tables.append(total_exposed_table(ctx))
    tables.extend(twin_rows(ctx, tables))

    def order(iv):
        i, t = iv
        if t["key"] == "TOTAL_EXPOSURE":
            return (-1, 0, 0, i)
        if t["type"] == "twin":
            return (9, 0, 0, i)
        v = ctx.vars.get(t.get("dict_var") or "")
        if not v:
            return (5, 0, 0, i)             # analysis-only tables after the dictionary ones
        return (1, v["chapter"], v["varsort"], i)
    tables = [t for _, t in sorted(enumerate(tables), key=order)]
    # sum-to-100 check on single-choice scales
    for t in tables:
        if t["type"] in ("scale", "single"):
            its = [r for r in t["rows"] if r["section"] in ("item", "analysis") and r["vals"]["sample"][0] is not None]
            if its:
                tot = sum(r["vals"]["sample"][0] for r in its)
                ctx.checks.append((f"{t['key']}: סכום התשובות = 100", f"{tot:.1f}", "OK" if abs(tot - 100) < 0.6 else "בדוק"))
    # partial-base note
    nsamp = int(ctx.masks["sample"].sum())
    for t in tables:
        ns = [r["vals"]["sample"][1] for r in t["rows"] if r["united"] or r["section"] == "item"]
        ns = [n for n in ns if n]
        if ns and min(ns) < nsamp and t["type"] not in ("twin", "derived"):
            t["notes"] = list(t.get("notes", [])) + [f"בסיס השאלה: n={min(ns)} מתוך N={nsamp} (השאלה נשאלה רק לחלק מהמדגם) — אחוזים מחושבים על הנשאלים"]
    # the same united code must be produced once
    seen = {}
    for t in tables:
        for r in t["rows"]:
            if r["united"]:
                seen.setdefault(r["united"], []).append(t["key"])
    dup = {u: k for u, k in seen.items() if len(k) > 1}
    if dup:
        ctx.checks.append(("united כפול בין טבלאות", "; ".join(f"{u}: {','.join(k)}" for u, k in list(dup.items())[:6]), "בדוק"))
    ctx.tables = tables
    return tables
