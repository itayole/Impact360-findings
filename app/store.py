"""File-based state: uploads, projects, dictionaries, decision log, retention.  No respondent values are ever logged."""
import datetime
import json
import logging
import os
import re
import shutil
import threading
import time
import uuid

from . import config

log = logging.getLogger("i360.store")
_LOCK = threading.RLock()
PID_RE = re.compile(r"^[0-9a-f]{12}$")


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _write(path, obj):
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


def _xlsx_files(d):
    return [f for f in os.listdir(d) if f.lower().endswith(".xlsx") and not f.startswith("~$")]


class Store:
    def __init__(self, data_dir=None):
        self.root = data_dir or config.DATA_DIR
        self.uploads = os.path.join(self.root, "uploads")
        self.projects = os.path.join(self.root, "projects")
        self.library = os.path.join(self.root, "library")
        self.dicts = os.path.join(self.library, "dictionaries")
        self.logs = os.path.join(self.root, "logs")
        for d in (self.uploads, self.projects, self.library, self.dicts, self.logs):
            os.makedirs(d, exist_ok=True)
        self._seed_dictionary()

    # ------------------------------------------------------------------ dictionaries
    def _seed_dictionary(self):
        if _xlsx_files(self.dicts):
            return
        if os.path.isdir(config.SEED_DIR):
            for f in _xlsx_files(config.SEED_DIR):
                shutil.copy2(os.path.join(config.SEED_DIR, f), os.path.join(self.dicts, f))
                log.info("seeded dictionary %s", f)

    def dictionaries(self):
        files = sorted(_xlsx_files(self.dicts), key=lambda f: os.path.getmtime(os.path.join(self.dicts, f)), reverse=True)
        active = self.active_dictionary()
        return [dict(file=f, active=(f == active),
                     uploaded_at=datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(self.dicts, f))).isoformat(timespec="seconds"))
                for f in files]

    def active_dictionary(self):
        a = (_read(os.path.join(self.library, "active_dictionary.json"), {}) or {}).get("file")
        if a and os.path.exists(os.path.join(self.dicts, a)):
            return a
        files = _xlsx_files(self.dicts)
        return max(files, key=lambda f: os.path.getmtime(os.path.join(self.dicts, f))) if files else None

    def set_active_dictionary(self, file):
        if not os.path.exists(os.path.join(self.dicts, os.path.basename(file))):
            raise FileNotFoundError(file)
        _write(os.path.join(self.library, "active_dictionary.json"), dict(file=os.path.basename(file)))

    def dictionary_path(self, file=None):
        f = os.path.basename(file) if file else self.active_dictionary()
        if not f:
            raise FileNotFoundError("אין מילון בספריה")
        p = os.path.join(self.dicts, f)
        if not os.path.exists(p):
            raise FileNotFoundError(f)
        return p

    # ------------------------------------------------------------------ projects
    def pdir(self, pid):
        if not PID_RE.match(pid or ""):
            raise KeyError(pid)
        return os.path.join(self.projects, pid)

    def new_project(self, name, sav_name, dictionary, user=""):
        pid = uuid.uuid4().hex[:12]
        os.makedirs(self.pdir(pid), exist_ok=True)
        p = dict(id=pid, name=name, sav_name=sav_name, dictionary=dictionary, created_at=now(), created_by=user,
                 brand="", campaign_id="", omnibus=False, qnr_name="", stage="uploaded")
        _write(os.path.join(self.pdir(pid), "project.json"), p)
        return p

    def project(self, pid):
        p = _read(os.path.join(self.pdir(pid), "project.json"))
        if p is None:
            raise KeyError(pid)
        return p

    def save_project(self, p):
        p["updated_at"] = now()
        _write(os.path.join(self.pdir(p["id"]), "project.json"), p)

    def projects_list(self, limit=50):
        out = []
        for pid in os.listdir(self.projects):
            if PID_RE.match(pid):
                p = _read(os.path.join(self.projects, pid, "project.json"))
                if p:
                    out.append(p)
        out.sort(key=lambda p: p.get("updated_at", p["created_at"]), reverse=True)
        return out[:limit]

    def sav_path(self, pid):
        return os.path.join(self.uploads, f"{pid}.sav")

    def qnr_path(self, pid):
        return os.path.join(self.uploads, f"{pid}.docx")

    def mapping(self, pid):
        return _read(os.path.join(self.pdir(pid), "mapping.json"))

    def save_mapping(self, pid, mapping):
        with _LOCK:
            _write(os.path.join(self.pdir(pid), "mapping.json"), mapping)

    def output_path(self, pid):
        return os.path.join(self.pdir(pid), "output.xlsx")

    def save_json(self, pid, name, obj):
        _write(os.path.join(self.pdir(pid), name), obj)

    def load_json(self, pid, name, default=None):
        return _read(os.path.join(self.pdir(pid), name), default)

    def snapshots(self, pid):
        d = os.path.join(self.pdir(pid), "snapshots")
        out = []
        if os.path.isdir(d):
            for f in os.listdir(d):
                s = _read(os.path.join(d, f))
                if s:
                    out.append(dict(id=s["id"], name=s["name"], created_at=s["created_at"], created_by=s.get("created_by", ""),
                                    auto=bool(s.get("auto"))))
        return sorted(out, key=lambda s: s["created_at"], reverse=True)

    def save_snapshot(self, pid, name, mapping, user="", auto=False):
        with _LOCK:
            sid = uuid.uuid4().hex[:8]
            _write(os.path.join(self.pdir(pid), "snapshots", f"{sid}.json"),
                   dict(id=sid, name=name, created_at=now(), created_by=user, auto=auto, mapping=mapping))
            return sid

    def get_snapshot(self, pid, sid):
        if not re.match(r"^[0-9a-f]{8}$", sid or ""):
            raise KeyError(sid)
        s = _read(os.path.join(self.pdir(pid), "snapshots", f"{sid}.json"))
        if s is None:
            raise KeyError(sid)
        return s

    def delete_snapshot(self, pid, sid):
        self.get_snapshot(pid, sid)
        os.remove(os.path.join(self.pdir(pid), "snapshots", f"{sid}.json"))

    def delete_project(self, pid):
        shutil.rmtree(self.pdir(pid), ignore_errors=True)
        try:
            os.rmdir(self.pdir(pid))        # OneDrive/AV can leave an empty folder behind
        except OSError:
            pass
        for p in (self.sav_path(pid), self.qnr_path(pid)):
            if os.path.exists(p):
                os.remove(p)

    # ------------------------------------------------------------------ metrics (no respondent data)
    def metric(self, obj):
        with _LOCK, open(os.path.join(self.logs, "metrics.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(at=now(), **obj), ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ retention
    def cleanup(self, now_ts=None):
        """Delete uploads older than UPLOAD_RETENTION_DAYS and whole projects older than PROJECT_RETENTION_DAYS."""
        now_ts = now_ts or time.time()
        removed = dict(uploads=0, projects=0)
        for f in os.listdir(self.uploads):
            p = os.path.join(self.uploads, f)
            if now_ts - os.path.getmtime(p) > config.UPLOAD_RETENTION_DAYS * 86400:
                os.remove(p)
                removed["uploads"] += 1
        for pid in os.listdir(self.projects):
            pj = os.path.join(self.projects, pid, "project.json")
            if PID_RE.match(pid) and os.path.exists(pj) and now_ts - os.path.getmtime(pj) > config.PROJECT_RETENTION_DAYS * 86400:
                self.delete_project(pid)
                removed["projects"] += 1
        if any(removed.values()):
            log.info("retention cleanup: %s", removed)
        return removed
