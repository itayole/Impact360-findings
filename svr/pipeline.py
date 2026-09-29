# -*- coding: utf-8 -*-
"""svr.pipeline — high-level entry points used by both the web app and the CLI."""
import datetime

from . import __version__, lib as L
from .profile import profile as _profile
from .report import compute_results, render_xlsx, summary_counts


def build_stamp(dictionary_path):
    return dict(app_version=__version__, dictionary_version=L.dictionary_version(dictionary_path),
                built_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


def run_profile(sav_path, dictionary_path, brand="", campaign_id="", omnibus=False, sav_name=None, qnr=None, extra_aliases=None):
    """Load the SAV + dictionary and propose a mapping.  Returns (mapping, catalog)."""
    vars_, codes = L.load_dictionary(dictionary_path)
    df, meta = L.load_sav(sav_path)
    mapping, catalog = _profile(df, meta, vars_, codes, dictionary_path=dictionary_path, brand=brand, qnr=qnr, extra_aliases=extra_aliases,
                                campaign_id=campaign_id, omnibus=omnibus,
                                sav_name=sav_name or sav_path.replace("\\", "/").rsplit("/", 1)[-1])
    return mapping, catalog


def apply_nets(mapping, nets):
    """Merge Net Builder output (`{blocks: {key: {nets, base}}}`) into the mapping (in place)."""
    byk = {e["key"]: e for e in mapping["questions"]}
    for k, b in (nets or {}).get("blocks", {}).items():
        if k in byk:
            byk[k].setdefault("nets", {}).update(b.get("nets", {}))
            if b.get("base"):
                byk[k]["base"] = b["base"]
    return mapping


def run_findings(sav_path, mapping, dictionary_path=None):
    """Compute all levels and render the workbook.  Returns (xlsx_bytes, summary, ctx)."""
    dictionary_path = dictionary_path or mapping["project"]["dictionary"]
    vars_, codes = L.load_dictionary(dictionary_path)
    df, meta = L.load_sav(sav_path)
    ctx = compute_results(df, meta, vars_, codes, mapping)
    xlsx = render_xlsx(ctx, build_stamp(dictionary_path))
    return xlsx, summary_counts(ctx), ctx
