# -*- coding: utf-8 -*-
"""svr.messages — role of each message option in MAIN / TOTAL MESSAGE_TAKEOUT (spec 6, step 2.4).

Roles: main | sec1 | sec2 | buy  (or '' = not a brief message).  The default is questionnaire POSITION order
(main, sec1, sec2, buy); the researcher confirms or changes it here — never taken silently from the questionnaire.
"""
import re

from . import lib as L

ROLES = ("main", "sec1", "sec2", "buy")
MAIN_SLOT = {"main": 2, "sec1": 3, "sec2": 4, "buy": 5}     # MAIN MESSAGE_TAKEOUT #02..#05
TOTAL_SLOT = {"main": 1, "sec1": 2, "sec2": 3, "buy": 4}    # Total MESSAGE_TAKEOUT #01..#04
NOT_MESSAGE = ("אף אחד", "לא יודע", "אין דעה", "לא בטוח")
_IMG = re.compile(r"\[[^\]]*\]")


def _entries(mapping):
    by = {e["key"]: e for e in mapping.get("questions", [])}
    return by.get("MAIN_MESSAGE_TAKEOUT"), by.get("TOTAL_MESSAGE_TAKEOUT")


def message_options(mapping, meta):
    """[{value, label, role}] for the real message options of MAIN_MESSAGE_TAKEOUT, in SAV order."""
    main, _ = _entries(mapping)
    if not main:
        return []
    var = main["vars"][0]
    vl = (meta.variable_value_labels or {}).get(var) or {}
    slot_role = {v: k for k, v in MAIN_SLOT.items()}
    out = []
    for val in sorted(vl):
        lab = _IMG.sub("", str(vl[val])).strip()
        if any(w in lab for w in NOT_MESSAGE):
            continue
        slot = (main.get("value_slots") or {}).get(str(int(val)))
        out.append(dict(value=int(val), label=lab, role=slot_role.get(slot, "")))
    return out


def apply_roles(mapping, meta, roles):
    """roles: list aligned with message_options().  Returns the list of changed entry keys."""
    main, total = _entries(mapping)
    if not main:
        raise ValueError("MAIN_MESSAGE_TAKEOUT לא קיים בפרויקט")
    picked = [r for r in roles if r]
    if len(picked) != len(set(picked)) or any(r not in ROLES for r in picked):
        raise ValueError("כל תפקיד (main / sec1 / sec2 / buy) יכול להופיע פעם אחת לכל היותר")
    opts = message_options(mapping, meta)
    if len(roles) != len(opts):
        raise ValueError(f"מספר התפקידים ({len(roles)}) שונה ממספר המסרים ({len(opts)})")
    vl = (meta.variable_value_labels or {}).get(main["vars"][0]) or {}
    vs = {str(int(k)): None for k in vl}
    for o, r in zip(opts, roles):
        vs[str(o["value"])] = MAIN_SLOT.get(r)
    main["value_slots"] = vs
    main["review"] = [x for x in main.get("review", []) if "mapped by POSITION" not in x]
    main["confirmed"] = True
    changed = [main["key"]]
    if total:
        names = total.get("option_names") or {}
        real = [c for c, n in names.items() if not any(w in _IMG.sub("", n) for w in NOT_MESSAGE)]
        if len(real) != len(opts):
            raise ValueError(f"TOTAL_MESSAGE_TAKEOUT: {len(real)} אפשרויות מסרים מול {len(opts)} ב-MAIN")
        total["option_slots"] = {c: TOTAL_SLOT[r] for c, r in zip(real, roles) if r}
        total["main_positions"] = {str(o["value"]): TOTAL_SLOT[r] for o, r in zip(opts, roles) if r}
        total["review"] = [x for x in total.get("review", []) if "answer list" not in x]
        total["confirmed"] = True
        changed.append(total["key"])
    return changed
