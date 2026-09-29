# -*- coding: utf-8 -*-
"""svr_profile — step 1: read the SAV, find the advertising-effectiveness questions and propose a mapping.

    python svr_profile.py <file.sav> --out mapping.json [--brand "האגיס"] [--campaign-id I360-2026-0XX]
                          [--dictionary <xlsx>] [--search-root <dir> ...]

Writes  mapping.json  (machine) + mapping_review.xlsx (human).  NOTHING is computed here.
The proposal is a DRAFT: every entry carries `confidence` and `review` flags — the researcher
(and Claude) confirm it before svr_run.py is executed.
"""
import argparse
import json
import os
import re
import sys

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from rapidfuzz import fuzz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import svr_lib as L  # noqa: E402

PARADATA = {"record", "uuid", "date", "start_date", "markers", "url", "session", "qtime", "status", "source",
            "list", "declang", "dcua", "useragent", "vlist", "vdropout", "vbrowser", "vos", "vosr15oe",
            "vmobiledevice", "vmobileos", "endcomment", "optin", "use", "ad1play_count", "ad1time_elapsed",
            "ad2play_count", "ad2time_elapsed", "total", "vbrowserr15oe"}
PARADATA_PREFIX = ("user", "vbrowser", "vos", "vmobile", "ad1", "ad2", "noanswer")
DEMOG = {"age", "agegroups", "area", "city", "education", "family", "gender", "income", "incomecombined",
         "incomesingle", "persons", "practice", "religion", "work", "q1", "q2", "q3"}

# SAV name  ->  dictionary VAR_NAME  (Shiluv Decipher template conventions; extend as new SAVs appear)
ALIASES = {
    "BRANDING": "CLEAR_BRANDING",
    "MAIN_MESSAGE_TAKEOUT": "MAIN MESSAGE_TAKEOUT",
    "TOTAL_MESSAGE_TAKEOUT": "Total MESSAGE_TAKEOUT",
    "vq36_coded": "LIKES", "vq37_coded": "DISLIKES",
    "vSLOGAN_coded": "SLOGAN", "vSPONTIMPRESSION_coded": "SPONTIMPRESSION",
    "vq32_coded": "SEMIAEX-VD", "vq5_coded": "UNEXPOSEB",
    "q45_47": "",  # prefix stripped, remainder matched by name
}
EXPOSURE_WORDS = ("ראית", "נחשפת", "שמעת", "יצא לך לראות", "נחשפ")
NONE_WORDS = ("לא ראיתי", "אף אחד", "לא נחשפ", "אין לי", "לא עוקב")
DK_WORDS = ("לא יודע", "אין דעה", "לא בטוח")


def norm(s):
    return re.sub(r"[\s_\-]+", "_", str(s)).lower()


_BR = re.compile(r"\[[^\]]*\]|\([^)]*\)")


def _clean_q(t):
    return _BR.sub(" ", str(t)).replace("\n", " ")


def match_dictionary(stem, question, vars_, codes=None, ans_labels=None):
    """(dict_var, confidence, score).
    Stage 1 = question text (partial + token-set ratio); stage 2 = SAV answer labels vs dictionary answer labels.
    Name equality / alias only count when the question text does not contradict them."""
    q = _clean_q(question)
    names = {norm(v): v for v in vars_}
    cand = stem
    for pre in ("q45_47",):
        if cand.startswith(pre):
            cand = cand[len(pre):]

    def qscore(v):
        dq = _clean_q(vars_[v]["question"])
        if not dq.strip() or len(q.strip()) < 12:
            return 0
        return max(fuzz.partial_ratio(q[:130], dq[:220]), fuzz.token_set_ratio(q[:130], dq[:220]) * 0.9)

    def ascore(v):
        if not ans_labels or not codes:
            return None
        dl = [c["label"] for c in codes.get(v, []) if c["role"] in ("scale", "item") and c["label"]]
        if not dl:
            return None
        return sum(max(fuzz.token_set_ratio(a, d) for d in dl) for a in ans_labels) / len(ans_labels)

    # likes vs dislikes share most of their wording — decide by the negation first
    if any(k in q for k in ("לא מצא חן", "לא מצאה חן", "הפריע", "הפריעה", "לא אהבת")) and "DISLIKES" in vars_:
        return "DISLIKES", "keyword", 90
    if any(k in q for k in ("מצא חן", "מצאה חן", "אהבת")) and "LIKES" in vars_ and "לא " not in q.split("חן")[0][-6:]:
        return "LIKES", "keyword", 90
    # exact / alias (sanity-checked by the question text)
    hit = None
    if norm(cand) in names:
        hit, kind = names[norm(cand)], "exact"
    elif stem in ALIASES and ALIASES[stem]:
        hit, kind = ALIASES[stem], "alias"
    if hit:
        qs = qscore(hit)
        if kind == "exact" or qs >= 60:
            return hit, kind, max(qs, 100 if kind == "exact" else qs)
    # fuzzy over every non-computed dictionary variable
    best, bs = None, 0
    if len(q.strip()) < 25:
        return None, "none", 0
    for v, d in vars_.items():
        if not d["question"] or d["base"].startswith("Computed") or v.endswith("_E"):
            continue
        qs = qscore(v)
        a2 = ascore(v)
        sc = qs if a2 is None else 0.65 * qs + 0.35 * a2
        if sc > bs:
            best, bs = v, sc
    FAMILY_BASE = {"SPONTIMP_CORRECT": "SPONTIMPRESSION", "SPONTIMP_MAIN": "SPONTIMPRESSION", "SPONTIMP_SEC": "SPONTIMPRESSION",
                   "SPONTIMPRESS_BRD": "SPONTIMPRESSION", "SEMIAEX-VD_gross": "SEMIAEX-VD", "SEMIAEX-VD_NET": "SEMIAEX-VD",
                   "SEMIAEX-VD_PRS": "SEMIAEX-VD", "SEMIAEX-VD_LNG": "SEMIAEX-VD", "SEMIAEX-VD_MSG": "SEMIAEX-VD",
                   "SEMIAEX-VD_BRD": "SEMIAEX-VD"}
    best = FAMILY_BASE.get(best, best)   # one question feeds a family — the base variable carries the block
    if best and bs >= 85:
        return best, "fuzzy-high", bs
    if best and bs >= 62:
        return best, "fuzzy-low", bs
    return None, "none", bs


REC_KEYWORDS = [  # (keywords in question, dictionary REC variable)
    (("טלוויזיה", "שזה עתה ראית"), "RECVD"), (("משפיענים",), "RECINF_BR"), (("רשתות החברתיות",), "RECINF"),
    (("שלטי חוצות",), "RECBB"), (("ברדיו", "שמעת פרסומת"), "RECOR"), (("בעיתונ",), "RECNEWS"),
    (("נקודות המכירה", "נקודת מכירה"), "RECPOS"), (("באנרים", "בסלולאר"), "RECIMB"), (("בפייסבוק",), "RECIMF"),
    (("באינטרנט",), "RECIMB"), (("פעילות", "תוכנית", "אירוע"), "REC_ACT"),
]


def rec_suggestion(question):
    for kws, v in REC_KEYWORDS:
        if any(k in question for k in kws):
            return v
    return None


def is_yesno(series):
    return set(series.dropna().unique().tolist()) <= {1, 2, 1.0, 2.0} and series.nunique() >= 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sav")
    ap.add_argument("--out", default="mapping.json")
    ap.add_argument("--brand", default="")
    ap.add_argument("--campaign-id", default="")
    ap.add_argument("--omnibus", action="store_true",
                    help="omnibus study: blocks with no dictionary variable are set include=false (other clients' questions)")
    ap.add_argument("--dictionary", default=None)
    ap.add_argument("--search-root", action="append", default=[])
    a = ap.parse_args()

    dpath = L.find_dictionary(a.dictionary, a.search_root)
    vars_, codes = L.load_dictionary(dpath)
    df, meta = L.load_sav(a.sav)
    blocks = L.detect_blocks(df, meta)
    labels = dict(zip(meta.column_names, meta.column_labels))
    vlabels = meta.variable_value_labels

    entries, skipped = [], []
    exposure_candidates, usage_candidates, verify_candidates = [], [], []

    for stem, cols in blocks.items():
        low = stem.lower()
        first = cols[0]
        opt, q = L.split_label(first, labels[first])
        question = q or opt
        # --- paradata / demographics / free text
        if low in PARADATA or low.startswith(PARADATA_PREFIX) or "Captured variable" in str(labels[first]):
            skipped.append(dict(block=stem, vars=cols, reason="paradata")); continue
        if low in DEMOG or (low.startswith("income")):
            skipped.append(dict(block=stem, vars=cols, reason="demographic — not an effectiveness question (v1)")); continue
        if stem.endswith("_coded_data") or (len(cols) == 1 and df[first].dtype == object):
            skipped.append(dict(block=stem, vars=cols, reason="raw verbatim / code-slot text")); continue
        if stem.startswith("q11_27") or (any("c" in re.findall(r"r\d+(c\d+)", c) or False for c in cols[:1]) and len(cols) > 20):
            skipped.append(dict(block=stem, vars=cols, reason="brand-image grid (brand x statement) — not in the effectiveness dictionary; run separately if needed"))
            continue

        binary = all(L.is_binary(df[c]) for c in cols)
        dvar, conf, score = match_dictionary(stem, question, vars_, codes, list((vlabels.get(first) or {}).values()) if len(cols) == 1 else None)
        ent = dict(key=stem, vars=cols, dict_var=dvar, confidence=conf, score=round(float(score), 1),
                   question=question[:200], include=True, review=[])

        # --- verify variable: DP pre-computed "exposed at least once"
        for c in cols:
            if L.is_binary(df[c]) and "חשיפה לפחות" in str(labels[c]):
                verify_candidates.append(c)
        # --- USAGE (3 months) candidate
        if "שלושת החודשים" in question or "3 חודשים" in question:
            usage_candidates.append(dict(block=stem, vars=cols, options={c: L.split_label(c, labels[c])[0] for c in cols}))

        if len(cols) == 1 and not binary:
            vl = vlabels.get(first) or {}
            ser = df[first]
            if len(vl) == 0 or ser.nunique() > 12:
                skipped.append(dict(block=stem, vars=cols, reason="no value labels / numeric or open — not tabulated (v1)")); continue
            # yes/no exposure candidate
            if is_yesno(ser) and any(w in question for w in EXPOSURE_WORDS):
                rs = rec_suggestion(question)
                if rs and rs in vars_:
                    ent["dict_var"] = dvar = rs; ent["confidence"] = "keyword"; ent["score"] = 0
                exposure_candidates.append(dict(var=first, values=[1], question=question[:120], dict_var=dvar, kind="single"))
                ent["type"] = "single"; ent["note"] = "yes/no exposure question — used in exposure union"
                ent["review"].append(f"exposure channel -> {dvar}: confirm which media channel this is")
            dvals = sorted(int(k) for k in vl)
            dk = [k for k, v in vl.items() if any(w in str(v) for w in DK_WORDS)]
            slots = {}
            for k in dvals:
                slots[str(k)] = 88 if (str(k) in {str(int(x)) for x in dk} and any(c["slot"] == 88 for c in codes.get(dvar or "", []))) else k
            if dvar == "MAIN MESSAGE_TAKEOUT":     # #02 main, #03 sec1, #04 sec2, #05 buy/try (position order = questionnaire order)
                slots = {str(k): (k + 1 if k <= 4 else None) for k in dvals}
                ent["review"].append("MAIN MESSAGE_TAKEOUT: options 1-4 mapped by POSITION (1=main,2=sec1,3=sec2,4=buy/try) — confirm against the questionnaire")
            ent["value_slots"] = slots
            # 4-point wording variant of a 5-point dictionary scale -> "<VAR>-KC version"
            if dvar and len(dvals) == 4 and dvar in vars_:
                item5 = [c for c in codes.get(dvar, []) if c["role"] == "scale" and c["slot"] == 5]
                kc = [v for v in vars_ if v.startswith(dvar) and "KC version" in v and v != dvar]
                if item5 and kc:
                    ent["dict_var"] = dvar = kc[0]
                    ent["review"].append(f"4-point scale -> dictionary variant {dvar}")
            roles = {c["role"] for c in codes.get(dvar or "", [])}
            ent.setdefault("type", "scale" if ({"scale", "T2B"} & roles) else "single")
            if dvar and conf in ("fuzzy-low", "fuzzy-high"):
                ent["review"].append("dictionary match is fuzzy — confirm")
            if dvar is None:
                ent["review"].append("no dictionary variable — will be tabulated as analysis-only (no united code)")
            nvals = len(dvals)
            item_slots = [c["slot"] for c in codes.get(dvar or "", []) if c["role"] in ("scale", "item") and isinstance(c["slot"], int)]
            if item_slots and nvals != max(item_slots) and ent["type"] == "scale":
                ent["review"].append(f"SAV has {nvals} scale points, dictionary has {max(item_slots)} — slots without data will be blank")
        elif binary and len(cols) >= 1:
            names = [L.split_label(c, labels[c])[0] or labels[c] for c in cols]
            if stem == "DESCRIBE" or (dvar == "DESCRIBE"):
                ent["type"] = "describe"
                ent["attr_names"] = {c: L.split_label(c, labels[c])[0] for c in cols}
            elif stem.endswith("_coded"):
                ent["type"] = "coded_open"
                ent["code_names"] = {c: L.split_label(c, labels[c])[0] for c in cols}
                excl = [c for c, n in ent["code_names"].items() if any(w in n for w in DK_WORDS + ("לא זוכר", "לא אהבתי כלום", "אהבתי הכל" if dvar == "DISLIKES" else "§§"))]
                ent["nets"] = {}
                brand = a.brand
                brand_codes = [c for c, n in ent["code_names"].items() if brand and brand in n]
                if dvar in ("LIKES", "DISLIKES", "SPONTIMPRESSION", "SEMIAEX-VD"):
                    ent["nets"][f"{dvar}#01"] = dict(exclude=excl)
                    ent["review"].append("net #01 = any substantive code — confirm the excluded (non-substantive) codes")
                if dvar == "SLOGAN":
                    ent["review"].append("SLOGAN#01 = the CORRECT slogan code(s): choose them from the code list and add `nets: {\"SLOGAN#01\": {\"include\": [codeVar,...]}}` (do NOT use 'any code')")
                if dvar == "SEMIAEX-VD":
                    ent["review"].append("SEMIAEX-VD_gross/_NET/_PRS/_LNG/_MSG/_BRD need code roles (proof of exposure) — ask the researcher / codebook, then add to `nets`")
                if dvar == "SPONTIMPRESSION":
                    ent["review"].append("SPONTIMP_CORRECT/_MAIN/_SEC/SPONTIMPRESS_BRD need the correct / main / secondary message codes from the brief+codebook — add to `nets`")
                if dvar == "UNEXPOSEB":
                    if brand_codes:
                        ent["nets"]["UNEXPOSEB#01"] = dict(include=brand_codes, note="המותג הנבדק בטבלת סה\"כ אזכורים")
                    ent["review"].append("UNEXPOSEB#01 = tested brand in the TOTAL-mentions table — confirm the brand code")
                if dvar in ("SEMIAEX-VD", "SEMIAEX-CAT", "UNEXPOSEB", "SLOGAN", "SPONTIMPRESSION"):
                    ent["base"] = "all"
            else:
                ent["type"] = "multi"
                ent["option_names"] = {c: L.split_label(c, labels[c])[0] for c in cols}
                any_expo = ("נחשפת" in question) and not stem.lower().startswith("vctq")  # vctq* = DP pre-computed groupings
                if any_expo and len(cols) > 3:
                    comps = [c for c, n in ent["option_names"].items() if not any(w in n for w in NONE_WORDS)]
                    rs = rec_suggestion(question)
                    if rs and rs in vars_:
                        ent["dict_var"] = dvar = rs; ent["confidence"] = "keyword"
                    exposure_candidates.append(dict(var=comps, values=[1], question=question[:120], dict_var=dvar, kind="any_of"))
                    ent["note"] = "exposure grid — used in exposure union (options except 'none')"
                if stem == "TOTAL_MESSAGE_TAKEOUT":
                    ent["type"] = "message_takeout"
                    ent["review"].append("map options to main/secondary1/secondary2/buy from the QUESTIONNAIRE answer list (default = position order)")
            if dvar == "SEMIAEX-CAT" and a.brand:
                inc = [c for c, n in ent["option_names"].items() if a.brand in n]
                if inc:
                    ent["nets"] = {"SEMIAEX-CAT#01": dict(include=inc, note="המותג הנבדק בשאלת הקטגוריה")}
                    ent["base"] = "all"
                    ent["review"].append("SEMIAEX-CAT#01 = tested-brand row — confirm")
            if dvar is None:
                ent["review"].append("no dictionary variable — analysis-only table")
            # option -> dictionary slot by label similarity (multi / coded)
            if dvar and ent["type"] in ("multi", "message_takeout"):
                items = {c["slot"]: c["label"] for c in codes.get(dvar, []) if c["role"] in ("item", "scale") and isinstance(c["slot"], int)}
                osl = {}
                for c, n in (ent.get("option_names") or {}).items():
                    best = max(items.items(), key=lambda kv: fuzz.token_set_ratio(n, kv[1]), default=None)
                    if best and fuzz.token_set_ratio(n, best[1]) >= 80:
                        osl[c] = best[0]
                if osl:
                    ent["option_slots"] = osl
                    ent["review"].append("option->slot assigned by label similarity — confirm")
            if ent["type"] == "message_takeout":
                real = [c for c, n in ent["option_names"].items() if not any(w in n for w in ("אף אחד",) + DK_WORDS)]
                ent["option_slots"] = {c: i + 1 for i, c in enumerate(real[:4])}
                ent["main_var"] = "MAIN_MESSAGE_TAKEOUT"
                ent["main_positions"] = {"1": 1, "2": 2, "3": 3, "4": 4}
        else:
            skipped.append(dict(block=stem, vars=cols, reason="mixed / unsupported block shape")); continue
        entries.append(ent)

    if a.omnibus:
        for e in entries:
            if not e["dict_var"] and not e.get("type") == "describe":
                e["include"] = False
                e["review"].append("omnibus: no dictionary variable — excluded (set include:true to tabulate)")

    # --- one dictionary variable can be carried by ONE block only
    rank = {"exact": 5, "alias": 4, "keyword": 3, "fuzzy-high": 2, "fuzzy-low": 1, "none": 0}
    by = {}
    for e in entries:
        if e["dict_var"]:
            by.setdefault(e["dict_var"], []).append(e)
    for dv_, lst in by.items():
        if len(lst) > 1:
            lst.sort(key=lambda x: -rank.get(x["confidence"], 0))
            for e in lst[1:]:
                e["review"].append(f"{dv_} already carried by block {lst[0]['key']} — this block demoted to analysis-only (re-assign if it is the right one)")
                e["dict_var"] = None; e["confidence"] = "none"
                e.pop("nets", None); e.pop("option_slots", None)
                if e.get("value_slots") and e.get("type") == "scale":
                    e["type"] = "single"

    # --- brand-usage default
    customer = None
    if usage_candidates:
        u = usage_candidates[0]
        pick = None
        for c, o in u["options"].items():
            if a.brand and a.brand in o:
                pick = c
        pick = pick or list(u["options"])[0]
        customer = dict(var=pick, customer_values=[1], noncustomer_values=[0], nan_as="noncustomer",
                        source_block=u["block"], option_text=u["options"][pick],
                        review="confirm this option is the TESTED brand; NaN treated as non-customer (multi-select unticked)")

    mapping = dict(
        project=dict(name="", campaign_id=a.campaign_id, brand=a.brand, sav=os.path.basename(a.sav),
                     dictionary=dpath, weight_var=None, n=int(len(df))),
        exposure=dict(label="נחשפו ל-1+ מדיה (Total Exposed)", components=exposure_candidates,
                      verify_var=verify_candidates[0] if verify_candidates else None,
                      note="union across media channels; verify_var = DP pre-computed 'exposed at least once' if present"),
        customer=customer,
        questions=entries, skipped=skipped,
    )
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=1)

    # --- human-readable review file
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "mapping_review"; ws.sheet_view.rightToLeft = True
    hdr = ["#", "בלוק SAV", "# משתנים", "סוג", "משתנה מילון", "ביטחון", "ציון", "שאלה", "לבדיקה", "כלול"]
    ws.append(hdr)
    for i, e in enumerate(entries, 1):
        ws.append([i, e["key"], len(e["vars"]), e.get("type"), e["dict_var"], e["confidence"], e["score"],
                   e["question"], "; ".join(e["review"]), "כן"])
    ws2 = wb.create_sheet("skipped"); ws2.sheet_view.rightToLeft = True
    ws2.append(["בלוק", "# משתנים", "סיבה"])
    for s in skipped:
        ws2.append([s["block"], len(s["vars"]), s["reason"]])
    for w in (ws, ws2):
        for c in w[1]:
            c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="1F3864")
        for col in w.columns:
            w.column_dimensions[col[0].column_letter].width = 22
    wb.save(os.path.splitext(a.out)[0] + "_review.xlsx")
    print(f"dictionary: {dpath}")
    print(f"blocks: {len(blocks)} | proposed questions: {len(entries)} | skipped: {len(skipped)}")
    print(f"exposure components: {len(exposure_candidates)} | verify var: {mapping['exposure']['verify_var']} | customer var: {customer and customer['var']}")
    # --- catalog for the Net Builder artifact (codes per coded / multi block + the nets the dictionary wants)
    FAM = {"SPONTIMPRESSION": ["SPONTIMPRESSION#01", "SPONTIMP_CORRECT#01", "SPONTIMP_MAIN#01", "SPONTIMP_SEC#01", "SPONTIMPRESS_BRD#01"],
           "SEMIAEX-VD": ["SEMIAEX-VD#01", "SEMIAEX-VD_gross#01", "SEMIAEX-VD_NET#01", "SEMIAEX-VD_PRS#01", "SEMIAEX-VD_LNG#01",
                          "SEMIAEX-VD_MSG#01", "SEMIAEX-VD_BRD#01"],
           "SLOGAN": ["SLOGAN#01"], "UNEXPOSEB": ["UNEXPOSEB#01"], "SEMIAEX-CAT": ["SEMIAEX-CAT#01"], "LIKES": ["LIKES#01"],
           "DISLIKES": ["DISLIKES#01"], "SPONTBRANDING": ["SPONTBRANDING FOR BRAND LINKAGE#01"], "Language": ["Language#01", "Language1#01"]}
    ulabel = {c["united"]: c["label"] for cl in codes.values() for c in cl if c["united"]}
    cat = []
    for e in entries:
        if e.get("type") not in ("coded_open", "multi") or not e.get("include", True):
            continue
        names = e.get("code_names") or e.get("option_names") or {}
        lst = [dict(var=v, label=names.get(v, v), n=int((df[v] == 1).sum())) for v in e["vars"]]
        fam = FAM.get(e["dict_var"] or "", [])
        cat.append(dict(key=e["key"], dict_var=e["dict_var"], question=e["question"], type=e["type"], base=e.get("base", "asked"),
                        n_total=int(len(df)), codes=lst,
                        wanted=[dict(united=u, label=ulabel.get(u, u)) for u in fam],
                        current={u: v for u, v in (e.get("nets") or {}).items()}))
    with open(os.path.splitext(a.out)[0] + "_codes_catalog.json", "w", encoding="utf-8") as f:
        json.dump(dict(project=mapping["project"]["sav"], brand=a.brand, blocks=cat), f, ensure_ascii=False, indent=1)
    print("wrote", os.path.splitext(a.out)[0] + "_codes_catalog.json", "(load it in the Net Builder artifact)")
    need = [e["key"] for e in entries if str(e["confidence"]).startswith("fuzzy") and e["dict_var"]]
    if need:
        print("NEEDS `confirmed: true` (fuzzy dictionary match — otherwise analysis-only):", ", ".join(need))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
