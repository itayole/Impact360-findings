# -*- coding: utf-8 -*-
"""svr.templates — shared template library (spec 8): fingerprint, match, save (versioned), apply, alias growth.

A template stores DECISIONS only (approved mapping, nets + bases, message order, exposure definition, customer
column) — never respondent data.  Files live under  <library>/templates/<template_id>/vNNN.json  and
<library>/aliases.json ; writes are atomic and serialised by a lock.
"""
import copy
import datetime
import hashlib
import json
import os
import re
import threading

from . import lib as L
from .compute import TRUSTED

MATCH_THRESHOLD = 0.90          # Jaccard; spec 8 [לאשר]
_LOCK = threading.RLock()
TID_RE = re.compile("[" + chr(92) + "w" + chr(92) + "-]{1,60}" + chr(92) + "Z")        # template ids are folder names: letters, digits, _ and - only


def valid_tid(tid):
    return isinstance(tid, str) and bool(TID_RE.match(tid))


DECISION_DROP = ("review", "warnings", "proposal", "needs_approval", "score", "qnr_item", "template_source")


def _norm(s):
    return re.sub(r"\s+", " ", re.sub(r"\[[^\]]*\]", "", str(s or ""))).strip().lower()


def fingerprint(df, meta):
    """Sorted list of 'name|normalised question text' — the set the Jaccard similarity is computed on."""
    labels = dict(zip(meta.column_names, meta.column_labels))
    out = set()
    for n in meta.column_names:
        _, q = L.split_label(n, labels.get(n))
        out.add(f"{n}|{_norm(q)[:80]}")
    return sorted(out)


def fingerprint_hash(fp):
    return hashlib.sha1("\n".join(fp).encode("utf-8")).hexdigest()[:16]


def jaccard(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if (a or b) else 0.0


def _atomic_write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _read(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


class Library:
    def __init__(self, root):
        self.root = root
        self.tdir = os.path.join(root, "templates")
        self.alias_path = os.path.join(root, "aliases.json")
        os.makedirs(self.tdir, exist_ok=True)

    # ------------------------------------------------------------------ read
    def _versions(self, tid):
        if not valid_tid(tid):
            return []
        d = os.path.join(self.tdir, tid)
        if not os.path.isdir(d):
            return []
        return sorted(int(m.group(1)) for f in os.listdir(d) if (m := re.match(r"v(\d+)\.json$", f)))

    def get(self, tid, version=None):
        vs = self._versions(tid)
        if not vs:
            return None
        v = version or vs[-1]
        if not isinstance(v, int) or v not in vs:
            return None
        return _read(os.path.join(self.tdir, tid, f"v{v:03d}.json"))

    def list(self):
        out = []
        for tid in sorted(os.listdir(self.tdir)):
            vs = self._versions(tid)
            if not vs:
                continue
            t = self.get(tid)
            out.append(dict(id=tid, name=t["name"], client=t.get("client", ""), tracker=t.get("tracker", ""),
                            version=t["version"], versions=vs, created_at=t["created_at"], created_by=t.get("created_by", ""),
                            n_questions=len(t["mapping"]["questions"])))
        return out

    def history(self, tid):
        res = []
        for v in self._versions(tid):
            t = self.get(tid, v)
            res.append(dict(version=v, created_at=t["created_at"], created_by=t.get("created_by", ""), changes=t.get("changes", [])))
        return res

    def suggest(self, fp, threshold=MATCH_THRESHOLD):
        """Templates whose fingerprint is similar enough — a SUGGESTION, never applied silently."""
        out = []
        for row in self.list():
            t = self.get(row["id"])
            sim = jaccard(fp, t["fingerprint"])
            if sim >= threshold:
                out.append(dict(id=row["id"], name=row["name"], version=t["version"], similarity=round(sim, 3),
                                client=row["client"], tracker=row["tracker"]))
        return sorted(out, key=lambda x: -x["similarity"])

    # ------------------------------------------------------------------ write
    def save(self, name, mapping, fp, user="", client="", tracker="", template_id=None):
        """Create the template or add a new version.  Returns the stored template dict."""
        with _LOCK:
            tid = template_id or re.sub(r"[^\w\-]+", "_", name, flags=re.U).strip("_")[:60] or "template"
            if not valid_tid(tid):
                raise ValueError("מזהה תבנית לא תקין")
            prev = self.get(tid)
            if prev and not template_id and prev["name"] != name:
                # "A B" and "A_B" give the same folder name: never turn another template into a new version silently
                raise ValueError(f"כבר קיימת תבנית אחרת בשם דומה ('{prev['name']}'). בחר/י שם אחר, או שמור כגרסה חדשה שלה")
            stored = _decisions_only(mapping)
            t = dict(id=tid, name=name, client=client, tracker=tracker, version=(prev["version"] + 1) if prev else 1,
                     created_at=datetime.datetime.now().isoformat(timespec="seconds"), created_by=user,
                     fingerprint=fp, fingerprint_hash=fingerprint_hash(fp), mapping=stored,
                     changes=diff_mappings(prev["mapping"], stored) if prev else ["גרסה ראשונה"])
            _atomic_write(os.path.join(self.tdir, tid, f"v{t['version']:03d}.json"), t)
            self._grow_aliases(mapping)
            return t

    # ------------------------------------------------------------------ client's chart design file (one per template version)
    def base_path(self, tid, version):
        return os.path.join(self.tdir, tid, f"v{int(version):03d}_charts_base.pptx")

    def find_base(self, tid, version):
        """The design file saved with that version (or the unversioned one written by 0.3.x)."""
        if not valid_tid(tid):
            return None
        for p in (self.base_path(tid, version), os.path.join(self.tdir, tid, "charts_base.pptx")):
            if os.path.exists(p):
                return p
        return None

    # ------------------------------------------------------------------ aliases (grown from approvals)
    def aliases(self):
        return _read(self.alias_path, {}) or {}

    def _grow_aliases(self, mapping):
        al = self.aliases()
        changed = False
        for e in mapping.get("questions", []):
            if e.get("dict_var") and e.get("confirmed") and e.get("confidence") not in ("exact", "alias", "template", "tag"):
                if al.get(e["key"]) != e["dict_var"]:
                    al[e["key"]] = e["dict_var"]
                    changed = True
        if changed:
            _atomic_write(self.alias_path, al)


def _decisions_only(mapping):
    m = copy.deepcopy(mapping)
    m["project"] = {k: m["project"].get(k) for k in ("brand", "weight_var")}
    for e in m.get("questions", []):
        for k in DECISION_DROP:
            e.pop(k, None)
    for k in ("skipped", "stats", "questionnaire", "template", "template_diff", "decisions"):
        m.pop(k, None)
    return m


def diff_mappings(old, new):
    """Human-readable list of what changed between two stored mappings (who/when is on the version record)."""
    out = []
    o = {e["key"]: e for e in old.get("questions", [])}
    n = {e["key"]: e for e in new.get("questions", [])}
    for k in n.keys() - o.keys():
        out.append(f"נוסף בלוק {k} ({n[k].get('dict_var') or 'ניתוח בלבד'})")
    for k in o.keys() - n.keys():
        out.append(f"הוסר בלוק {k}")
    for k in n.keys() & o.keys():
        a, b = o[k], n[k]
        if a.get("dict_var") != b.get("dict_var"):
            out.append(f"{k}: משתנה מילון {a.get('dict_var') or '—'} -> {b.get('dict_var') or '—'}")
        if bool(a.get("include", True)) != bool(b.get("include", True)):
            out.append(f"{k}: {'נכלל' if b.get('include', True) else 'הוחרג'}")
        if json.dumps(a.get("nets"), sort_keys=True) != json.dumps(b.get("nets"), sort_keys=True):
            out.append(f"{k}: שונו סיכומי הקודים (nets)")
        if a.get("value_slots") != b.get("value_slots") or a.get("option_slots") != b.get("option_slots"):
            out.append(f"{k}: שונה מיפוי תשובה->סלוט")
    for part in ("exposure", "customer"):
        if json.dumps(old.get(part), sort_keys=True) != json.dumps(new.get(part), sort_keys=True):
            out.append(f"שונתה הגדרת {'החשיפה' if part == 'exposure' else 'הלקוחות'}")
    if json.dumps(old.get("charts"), sort_keys=True) != json.dumps(new.get("charts"), sort_keys=True):
        out.append("שונו הגדרות הגרפים (סוג גרף / צבעים / קובץ עיצוב)")
    return out or ["ללא שינוי"]


# =============================================================================
def apply_template(mapping, template):
    """Apply an ACCEPTED template onto a fresh proposal (in place).

    A block is taken over only if its SAV variable set equals the template block's; then it counts as
    confidence 'template' (trusted).  Anything that differs is left as proposed, flagged, and listed in
    mapping['template_diff'] so the review screen shows it.  Returns the diff dict."""
    tm = template["mapping"]
    tq = {e["key"]: e for e in tm.get("questions", [])}
    seen, applied, changed_structure, new_blocks = set(), [], [], []
    for e in mapping["questions"]:
        t = tq.get(e["key"])
        if not t:
            new_blocks.append(e["key"])
            e["review"].append("בלוק חדש — לא קיים בתבנית; דורש אישור")
            e["needs_approval"] = bool(e.get("dict_var")) and e.get("confidence") not in ("exact", "tag", "template", "alias")
            continue
        seen.add(e["key"])
        if set(t.get("vars", [])) != set(e["vars"]):
            changed_structure.append(e["key"])
            e["review"].append(f"מבנה הבלוק השתנה מול התבנית '{template['name']}' v{template['version']} (משתני SAV שונים) — דורש אישור")
            e["needs_approval"] = bool(e.get("dict_var"))
            continue
        for k, v in t.items():
            if k in ("key", "vars", "question"):
                continue
            e[k] = copy.deepcopy(v)
        if t.get("dict_var") and t.get("confidence") not in TRUSTED and not t.get("confirmed"):
            # the template holds a match nobody approved (e.g. an unconfirmed fuzzy one) — it stays a proposal
            e["needs_approval"] = True
            e["review"] = ["התאמה שלא אושרה גם בתבנית — דורש אישור"]
            continue
        e["confidence"], e["layer"], e["needs_approval"] = "template", 2, False
        e["confirmed"] = True
        e["template_source"] = dict(id=template["id"], version=template["version"])
        e["review"] = []
        applied.append(e["key"])
    for part in ("exposure", "customer"):
        if tm.get(part) is not None:
            mapping[part] = copy.deepcopy(tm[part])
    if tm.get("charts"):
        mapping["charts"] = copy.deepcopy(tm["charts"])          # chart type / colours per question travel with the tracker
    if tm.get("segments") is not None:
        mapping["segments"] = copy.deepcopy(tm["segments"])      # extra columns travel with the tracker
    mapping["project"]["weight_var"] = tm.get("project", {}).get("weight_var") or mapping["project"].get("weight_var")
    diff = dict(applied=applied, missing=sorted(set(tq) - seen), new=new_blocks, structure_changed=changed_structure,
                template=dict(id=template["id"], name=template["name"], version=template["version"]))
    mapping["template_diff"] = diff
    return diff
