"""Business logic behind the API routes (kept out of main.py so it can be tested without HTTP)."""
import copy
import os
import shutil
import time

from svr import __version__ as SVR_VERSION
from svr import lib as L
from svr import messages as M
from svr import preview as PV
from svr import pipeline as P
from svr import questionnaire as Q
from svr import templates as T
from svr.profile import brand_options, profile as run_profile_fn, needs_approval
from svr.report import compute_results, render_xlsx, summary_counts, open_assumptions
from svr.compute import TRUSTED

import logging

from . import config, runtime

log = logging.getLogger("i360.service")
from .store import Store, now

ALLOWED_Q_FIELDS = {"include", "confirmed", "nets", "base", "option_slots", "value_slots", "net_exclude"}
APP_VERSION = SVR_VERSION


class Bad(Exception):
    """User-facing 400."""


def build_info():
    return dict(app_version=APP_VERSION, build_time=config.BUILD_TIME)


# ------------------------------------------------------------------------------------------ create
def create_project(store: Store, name, sav_tmp_path, sav_name, qnr_tmp_path=None, qnr_name="", dictionary=None, user=""):
    dpath = store.dictionary_path(dictionary)
    p = store.new_project(name or os.path.splitext(sav_name)[0], sav_name, os.path.basename(dpath), user)
    pid = p["id"]
    shutil.move(sav_tmp_path, store.sav_path(pid))
    warnings = []
    try:
        meta = L.load_meta(store.sav_path(pid))
    except Exception as ex:  # noqa: BLE001
        store.delete_project(pid)
        log.warning("SAV read failed: %r", ex)
        raise Bad(f"לא ניתן לקרוא את קובץ ה-SAV ({type(ex).__name__}). ודא/י שזה קובץ SPSS תקין.")
    if qnr_tmp_path:
        shutil.move(qnr_tmp_path, store.qnr_path(pid))
        qnr = Q.parse_docx(store.qnr_path(pid))
        store.save_json(pid, "qnr.json", qnr.to_dict())
        p["qnr_name"] = qnr_name
        warnings = list(qnr.warnings)
    fp = T.fingerprint(None, meta)
    store.save_json(pid, "fingerprint.json", fp)
    lib = T.Library(store.library)
    p["n"] = int(meta.number_rows or 0)
    p["stage"] = "uploaded"
    store.save_project(p)
    return dict(project=p, brand_options=brand_options(None, meta), template_suggestions=lib.suggest(fp),
                questionnaire_warnings=warnings, n_columns=len(meta.column_names))


def reattach_sav(store, pid, sav_tmp_path):
    store.project(pid)
    shutil.move(sav_tmp_path, store.sav_path(pid))
    runtime.sav_cache._d.clear()
    return dict(ok=True)


# ------------------------------------------------------------------------------------------ profile
def _qnr(store, pid):
    if not os.path.exists(store.qnr_path(pid)):
        return None
    return Q.parse_docx(store.qnr_path(pid))


def run_profile(store, pid, brand="", campaign_id="", omnibus=False, template_id=None, template_version=None, user=""):
    p = store.project(pid)
    df, meta = runtime.load_sav(store, pid)
    dpath = store.dictionary_path(p["dictionary"])
    vars_, codes = runtime.load_dictionary(dpath)
    lib = T.Library(store.library)
    mapping, catalog = run_profile_fn(df, meta, vars_, codes, dictionary_path=dpath, brand=brand, campaign_id=campaign_id,
                                      omnibus=omnibus, sav_name=p["sav_name"], qnr=_qnr(store, pid),
                                      extra_aliases=lib.aliases())
    mapping["project"]["name"] = p["name"]
    mapping["decisions"] = []
    if template_id:
        t = lib.get(template_id, template_version)
        if not t:
            raise Bad("התבנית לא נמצאה")
        T.apply_template(mapping, t)
        _log(mapping, user, "template", f"הוחלה התבנית '{t['name']}' v{t['version']}")
    p.update(brand=brand, campaign_id=campaign_id, omnibus=bool(omnibus), stage="reviewed" if template_id else "profiled",
             template=dict(id=template_id, version=template_version) if template_id else None)
    store.save_project(p)
    store.save_mapping(pid, mapping)
    return review_payload(store, pid, mapping, df, meta)


def review_payload(store, pid, mapping=None, df=None, meta=None):
    mapping = mapping or store.mapping(pid)
    if mapping is None:
        raise Bad("טרם הורץ פרופיל")
    if meta is None:
        df, meta = runtime.load_sav(store, pid)
    dpath = mapping["project"]["dictionary"]
    vars_, codes = runtime.load_dictionary(dpath)
    ctx = C_ctx(df, meta, vars_, codes, mapping)
    mo = M.message_options(mapping, meta)
    sug = (mapping.get("questionnaire") or {}).get("message_suggestion")
    slim = _slim_mapping(mapping, vars_)
    return dict(mapping=slim, levels=PV.level_summary(ctx), messages=dict(options=mo, suggestion=sug, roles=list(M.ROLES)),
                pending=[e["key"] for e in mapping["questions"] if e.get("include", True) and needs_approval(e)],
                build=build_info(), dictionary=L.dictionary_version(dpath))


def C_ctx(df, meta, vars_, codes, mapping):
    from svr.compute import Ctx
    return Ctx(df, meta, vars_, codes, mapping)


def _slim_mapping(mapping, vars_):
    """What the UI needs; everything is aggregate/metadata — no respondent values."""
    m = copy.deepcopy(mapping)
    for e in m["questions"]:
        e["dict_title"] = (vars_.get(e["dict_var"] or "") or {}).get("title", "")
        e["needs_approval"] = needs_approval(e)
    return m


# ------------------------------------------------------------------------------------------ decisions
def _log(mapping, user, key, what):
    mapping.setdefault("decisions", []).append(dict(key=key, user=user or "anonymous", at=now(), what=what))


def apply_patch(store, pid, patch, user=""):
    p = store.project(pid)
    mapping = store.mapping(pid)
    if mapping is None:
        raise Bad("טרם הורץ פרופיל")
    by = {e["key"]: e for e in mapping["questions"]}
    # ---- remap = a human picked the dictionary variable: rebuild the block around it
    remap = patch.get("remap") or {}
    if remap:
        df, meta = runtime.load_sav(store, pid)
        vars_, codes = runtime.load_dictionary(mapping["project"]["dictionary"])
        for k, dv in remap.items():
            if k not in by:
                raise Bad(f"בלוק לא קיים: {k}")
            if dv and dv not in vars_:
                raise Bad(f"משתנה מילון לא קיים: {dv}")
        forced = dict(mapping.get("forced") or {})
        forced.update({k: (dv or None) for k, dv in remap.items()})
        fresh, _ = run_profile_fn(df, meta, vars_, codes, dictionary_path=mapping["project"]["dictionary"],
                                  brand=mapping["project"].get("brand", ""), campaign_id=mapping["project"].get("campaign_id", ""),
                                  omnibus=p.get("omnibus", False), sav_name=p["sav_name"], qnr=_qnr(store, pid),
                                  extra_aliases=T.Library(store.library).aliases(), forced=forced)
        fresh_by = {e["key"]: e for e in fresh["questions"]}
        freed = {by[k].get("dict_var") for k in remap if by[k].get("dict_var")} | {dv for dv in remap.values() if dv}
        replace = set(remap) | {k for k, e in by.items() if e.get("dict_var") in freed}
        for i, e in enumerate(mapping["questions"]):
            if e["key"] in replace and e["key"] in fresh_by:
                old = e
                mapping["questions"][i] = fresh_by[e["key"]]
                if e["key"] in remap:
                    _log(mapping, user, e["key"], f"שונה משתנה מילון: {old.get('dict_var') or '—'} -> {remap[e['key']] or '—'}")
                else:
                    _log(mapping, user, e["key"], f"הותאם מחדש אוטומטית (התנגשות משתנה מילון): {old.get('dict_var') or '—'} -> {fresh_by[e['key']].get('dict_var') or '—'}")
        mapping["forced"] = forced
        by = {e["key"]: e for e in mapping["questions"]}
    # ---- plain per-block fields
    for k, fields in (patch.get("questions") or {}).items():
        e = by.get(k)
        if not e:
            raise Bad(f"בלוק לא קיים: {k}")
        for f, v in fields.items():
            if f not in ALLOWED_Q_FIELDS:
                raise Bad(f"שדה לא ניתן לעדכון: {f}")
            if e.get(f) == v:
                continue
            e[f] = v
            what = {"include": lambda: "נכלל בניתוח" if v else "הוחרג מהניתוח (לא רלוונטי)",
                    "confirmed": lambda: f"{'אושרה' if v else 'בוטל אישור'} התאמה ל-{e.get('dict_var') or '—'}",
                    "nets": lambda: "עודכנו סיכומי הקודים", "base": lambda: f"בסיס הוגדר: {v}"}.get(f, lambda: f"עודכן {f}")()
            _log(mapping, user, k, what)
    if patch.get("confirm_all"):
        n = 0
        for e in mapping["questions"]:
            if e.get("include", True) and needs_approval(e):
                e["confirmed"] = True
                n += 1
        if n:
            _log(mapping, user, "*", f"אושרו {n} התאמות בבת אחת")
    # ---- exposure / customer / project
    for idx, en in (patch.get("exposure_enabled") or {}).items():
        comps = mapping["exposure"]["components"]
        i = int(idx)
        if not 0 <= i < len(comps):
            raise Bad("רכיב חשיפה לא קיים")
        if comps[i].get("enabled", True) != bool(en):
            comps[i]["enabled"] = bool(en)
            _log(mapping, user, "exposure", f"רכיב חשיפה {comps[i].get('question', comps[i]['var'])[:40] if isinstance(comps[i].get('question'), str) else i}: {'נכלל' if en else 'הוחרג'}")
    if patch.get("customer_var"):
        opts = {o["var"]: o for o in mapping.get("customer_options", [])}
        cv = patch["customer_var"]
        if cv not in opts:
            raise Bad("אפשרות לקוחות לא קיימת")
        cu = mapping.get("customer") or dict(customer_values=[1], noncustomer_values=[0], nan_as="noncustomer")
        cu.update(var=cv, source_block=opts[cv]["block"], option_text=opts[cv]["text"])
        cu["review"] = "נבחר על ידי המשתמש"
        mapping["customer"] = cu
        _log(mapping, user, "customer", f"מותג נבדק (לקוחות): {opts[cv]['text']}")
    for f, v in (patch.get("project") or {}).items():
        if f in ("name", "brand", "campaign_id", "weight_var"):
            if mapping["project"].get(f) != v:
                mapping["project"][f] = v
                p[f] = v if f in p else p.get(f)
                _log(mapping, user, "project", f"{f} = {v}")
    if "roles" in patch:
        df, meta = runtime.load_sav(store, pid)
        try:
            changed = M.apply_roles(mapping, meta, patch["roles"])
        except ValueError as ex:
            raise Bad(str(ex))
        _log(mapping, user, "messages", "סדר/תפקיד המסרים אושר: " + ", ".join(r or "—" for r in patch["roles"]))
    p["stage"] = "reviewed"
    store.save_project(p)
    store.save_mapping(pid, mapping)
    return dict(ok=True, decisions=len(mapping.get("decisions", [])))


# ------------------------------------------------------------------------------------------ preview / warnings
def preview(store, pid, block=None, nets=None):
    mapping = store.mapping(pid)
    if mapping is None:
        raise Bad("טרם הורץ פרופיל")
    df, meta = runtime.load_sav(store, pid)
    vars_, codes = runtime.load_dictionary(mapping["project"]["dictionary"])
    ctx = C_ctx(df, meta, vars_, codes, mapping)
    if not block:
        return PV.level_summary(ctx)
    e = next((x for x in mapping["questions"] if x["key"] == block), None)
    if not e:
        raise Bad("בלוק לא קיים")
    try:
        return PV.block_preview(ctx, e, nets)
    except ValueError as ex:
        raise Bad(str(ex))


def warnings(store, pid):
    mapping = store.mapping(pid)
    if mapping is None:
        raise Bad("טרם הורץ פרופיל")
    df, meta = runtime.load_sav(store, pid)
    vars_, codes = runtime.load_dictionary(mapping["project"]["dictionary"])
    ctx = compute_results(df, meta, vars_, codes, mapping)
    return PV.project_warnings(ctx, mapping)


def results(store, pid):
    """Findings tables for on-screen verification (same numbers as the workbook)."""
    mapping = store.mapping(pid)
    if mapping is None:
        raise Bad("טרם הורץ פרופיל")
    df, meta = runtime.load_sav(store, pid)
    vars_, codes = runtime.load_dictionary(mapping["project"]["dictionary"])
    ctx = compute_results(df, meta, vars_, codes, mapping)
    return PV.results_tables(ctx)


def coded_blocks(store, pid):
    """The blocks the Net Builder works on, with the dictionary nets each one is expected to feed."""
    mapping = store.mapping(pid)
    if mapping is None:
        raise Bad("טרם הורץ פרופיל")
    vars_, codes = runtime.load_dictionary(mapping["project"]["dictionary"])
    from svr.profile import FAMILY_NETS
    ulabel = {c["united"]: c["label"] for cl in codes.values() for c in cl if c["united"]}
    out = []
    for e in mapping["questions"]:
        if e.get("type") not in ("coded_open", "multi") or not e.get("include", True):
            continue
        names = e.get("code_names") or e.get("option_names") or {}
        out.append(dict(key=e["key"], dict_var=e.get("dict_var"), question=e.get("question", ""), type=e["type"],
                        base=e.get("base", "asked"), confidence=e.get("confidence"),
                        wanted=[dict(united=u, label=ulabel.get(u, u)) for u in FAMILY_NETS.get(e.get("dict_var") or "", [])],
                        nets=e.get("nets") or {}, codes=[dict(var=v, label=names.get(v, v)) for v in e["vars"]]))
    return out


# ------------------------------------------------------------------------------------------ run
def metrics_for(mapping):
    """Per identification layer: how many blocks, and how many the researcher changed (spec 5א — measures)."""
    per = {}
    for e in mapping["questions"]:
        pr = e.get("proposal") or {}
        layer = pr.get("confidence") or "none"
        row = per.setdefault(layer, dict(blocks=0, changed=0))
        row["blocks"] += 1
        if pr.get("dict_var") != e.get("dict_var"):
            row["changed"] += 1
    return per


def start_run(store, pid, user=""):
    mapping = store.mapping(pid)
    if mapping is None:
        raise Bad("טרם הורץ פרופיל")
    p = store.project(pid)
    if not os.path.exists(store.sav_path(pid)):
        raise Bad("קובץ ה-SAV נמחק לפי מדיניות הניקוי — יש להעלות אותו מחדש")

    def work(progress):
        progress("טוען נתונים", 8)
        df, meta = runtime.load_sav(store, pid)
        dpath = mapping["project"]["dictionary"]
        vars_, codes = runtime.load_dictionary(dpath)
        m = store.mapping(pid)
        progress("מחשב את כל הרמות", 30)
        ctx = compute_results(df, meta, vars_, codes, m)
        progress("מפיק אקסל", 75)
        xlsx = render_xlsx(ctx, P.build_stamp(dpath))
        with open(store.output_path(pid), "wb") as f:
            f.write(xlsx)
        summ = summary_counts(ctx)
        ex = m.get("exposure") or {}
        res = dict(
            bases=ctx.bases(), summary=summ,
            exposure=dict(label=ex.get("label"), components=[str(c.get("question", ""))[:70] for c in ex.get("components", []) if c.get("enabled", True)]),
            checks=[list(c) for c in ctx.checks], open_assumptions=open_assumptions(m),
            build=P.build_stamp(dpath), finished_at=now(), size=len(xlsx),
            filename=f"{(m['project'].get('name') or p['name'] or 'Impact360')}_FINDINGS_SAV.xlsx")
        p2 = store.project(pid)
        p2.update(stage="done", last_run=dict(at=res["finished_at"], filename=res["filename"], user=user))
        store.save_project(p2)
        store.save_json(pid, "last_run.json", res)
        store.metric(dict(event="run", project=pid, slots=summ["slots"], tables=summ["tables"], errors=len(summ["errors"]),
                          layers=metrics_for(m), app=APP_VERSION))
        return res

    return runtime.jobs.submit(pid, work)


# ------------------------------------------------------------------------------------------ templates
def save_template(store, pid, name, user="", client="", tracker="", template_id=None):
    mapping = store.mapping(pid)
    if mapping is None:
        raise Bad("טרם הורץ פרופיל")
    pend = [e["key"] for e in mapping["questions"] if e.get("include", True) and needs_approval(e)]
    if pend:
        raise Bad("לא ניתן לשמור תבנית עם התאמות שלא אושרו: " + ", ".join(pend[:8]))
    meta = runtime.load_sav(store, pid)[1] if os.path.exists(store.sav_path(pid)) else None
    fp = T.fingerprint(None, meta) if meta is not None else store.load_json(pid, "fingerprint.json", [])
    lib = T.Library(store.library)
    t = lib.save(name, mapping, fp, user=user, client=client, tracker=tracker, template_id=template_id)
    _log(mapping, user, "template", f"נשמרה תבנית '{t['name']}' v{t['version']}")
    store.save_mapping(pid, mapping)
    return dict(id=t["id"], version=t["version"], changes=t["changes"])
