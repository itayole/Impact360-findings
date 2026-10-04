# -*- coding: utf-8 -*-
"""svr.preview — server-side live results for the Net Builder (spec 3 / 7).

Uses the SAME handlers as the workbook (compute.do_multi), so a live number equals the Excel number.
Nothing respondent-level ever leaves this module: only aggregated % / n per level and significance letters.
"""
import copy

import numpy as np

from . import compute as C
from . import lib as L
from .report import MIN_N, sig_letters


def _serialize(row, ctx, counts=None):
    out = dict(label=row["label"], united=row["united"], section=row["section"], role=row.get("role", ""), kind=row["kind"], note=row["note"],
               values={}, letters={}, n={})
    for lv in ctx.display:
        v = row["vals"][lv]
        out["values"][lv] = None if v[0] is None else round(v[0], 3)
        out["n"][lv] = v[1]
        out["letters"][lv] = sig_letters(row, lv, ctx)
    if counts is not None:
        out["counts"] = counts
    if row.get("members") is not None:
        out["members"] = row["members"]
        out["members_mode"] = row["members_mode"]
        out["members_text"] = C.members_text(row["members"], row["members_mode"], limit=6)
        out["members_full"] = C.members_text(row["members"], row["members_mode"])
    return out


def bases(ctx):
    b = ctx.bases()
    return {k: b[k] for k in ctx.display}


def columns(ctx):
    """The displayed columns, in order: the UI renders its tables from this (fixed levels + user segments)."""
    b = ctx.bases()
    return [dict(key=k, letter=ctx.letter[k], name=ctx.names[k], n=b[k], segment=k.startswith("seg:")) for k in ctx.display]


def level_summary(ctx):
    """Bases + the automatic checks that concern the level definitions (exposure union vs DP variable, customers)."""
    return dict(bases=bases(ctx), columns=columns(ctx), checks=[list(c) for c in ctx.checks[:3]])


def block_preview(ctx, entry, nets=None):
    """Rows for one coded/multi block, optionally with candidate `nets` (dict united|key -> spec).

    Per-code rows come first (section item/analysis, with respondent counts per level), then one row per net."""
    if entry.get("type") not in ("coded_open", "multi"):
        raise ValueError("preview is defined for coded / multi-choice blocks")
    e = copy.deepcopy(entry)
    if nets is not None:
        e["nets"] = nets
    if str(e.get("confidence", "")).startswith(("fuzzy", "keyword", "structure")) and not e.get("confirmed"):
        pass    # preview shows what the run would compute; the run itself gates untrusted matches
    rows = C.do_multi(ctx, e, coded=(e["type"] == "coded_open"))
    # respondent counts per code (ticked = 1) for the 5 levels
    flags = {v: (ctx.df[v] == 1).values for v in e["vars"]}
    out_codes, out_nets = [], []
    code_iter = iter(e["vars"])
    for r in rows:
        if r["section"] == "summary":
            ns = _serialize(r, ctx)
            ns["counts"] = {lv: _count(r["vals"][lv][0], r["vals"][lv][1], r["kind"]) for lv in ctx.display}
            out_nets.append(ns)
        else:
            v = next(code_iter, None)
            counts = {lv: int((flags[v] & ctx.masks[lv]).sum()) for lv in ctx.display} if v else None
            s = _serialize(r, ctx, counts)
            s["var"] = v
            out_codes.append(s)
    return dict(key=e["key"], codes=out_codes, nets=out_nets, bases=bases(ctx),
                base_note="all" if e.get("base") == "all" else "asked", letters=ctx.letter, columns=columns(ctx), min_n=MIN_N)


def project_warnings(ctx, mapping):
    """Everything still open, aggregated for the review screen."""
    from .report import open_assumptions
    warns = []
    for e in mapping.get("questions", []):
        if e.get("include", True) and e.get("dict_var") and e.get("confidence") not in C.TRUSTED and not e.get("confirmed"):
            warns.append(dict(kind="unconfirmed", key=e["key"], text=f"{e['key']}: התאמה {e.get('confidence')} ל-{e['dict_var']} לא אושרה — ניתוח בלבד"))
        for w in e.get("warnings", []) or []:
            warns.append(dict(kind="structure", key=e["key"], text=f"{e['key']}: {w}"))
    low = [(t["key"], x["united"], x["vals"]["sample"][1]) for t in ctx.tables for x in t["rows"]
           if x["united"] and x["vals"]["sample"][0] is not None and x["vals"]["sample"][1] < MIN_N]
    for k, u, n in low[:50]:
        warns.append(dict(kind="low_base", key=k, text=f"{u}: בסיס נמוך מ-{MIN_N} (n={n})"))
    for c in ctx.checks:
        if c[2] != "OK":
            warns.append(dict(kind="check", key="", text=f"{c[0]}: {c[1]}"))
    q = mapping.get("questionnaire") or {}
    for w in q.get("warnings", []):
        warns.append(dict(kind="questionnaire", key="", text=w))
    for w in q.get("cross_check", [])[:40]:
        warns.append(dict(kind="questionnaire", key="", text=w))
    return warns


def _count(v, n, kind):
    """Respondent count behind a percentage (unweighted runs: pct = 100*count/n, so the rounding is exact)."""
    return None if (v is None or kind != "pct" or not n) else int(round(v * n / 100.0))


def results_tables(ctx):
    """Every findings table as the workbook has it: 5 columns, significance letters, n and respondent counts.
    Aggregates only."""
    out = []
    for t in ctx.tables:
        rows = []
        nets_ = [r for r in t["rows"] if r.get("members") is not None]
        for r in t["rows"]:
            s = _serialize(r, ctx)
            if r.get("code_idx") is not None:        # which summaries this answer belongs to (tags shown next to the answer)
                s["in_nets"] = [n["label"] for n in nets_ if r["code_idx"] in n.get("member_idx", [])]
            s["counts"] = {lv: _count(r["vals"][lv][0], r["vals"][lv][1], r["kind"]) for lv in ctx.display}
            s["status"] = r.get("status", "")
            rows.append(s)
        out.append(dict(key=t["key"], title=t["title"], question=t.get("question", ""), dict_var=t.get("dict_var"),
                        type=t.get("type"), confidence=t.get("confidence", ""), notes=t.get("notes", []), rows=rows))
    return dict(bases=bases(ctx), letters=ctx.letter, columns=columns(ctx), min_n=MIN_N, tables=out)
