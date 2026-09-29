"""In-process caches (SAV data, dictionaries) and the job runner.  Respondent-level frames never leave this process."""
import logging
import os
import threading
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from svr import lib as L

from . import config

log = logging.getLogger("i360.runtime")


class Cache:
    def __init__(self, size):
        self.size = size
        self._d = OrderedDict()
        self._lock = threading.RLock()
        self._loading = {}

    def get(self, key, loader):
        with self._lock:
            if key in self._d:
                self._d.move_to_end(key)
                return self._d[key]
            lock = self._loading.setdefault(key, threading.Lock())
        with lock:                      # one loader per key; others wait for it
            with self._lock:
                if key in self._d:
                    return self._d[key]
            val = loader()
            with self._lock:
                self._d[key] = val
                while len(self._d) > self.size:
                    self._d.popitem(last=False)
                self._loading.pop(key, None)
            return val

    def drop(self, key):
        with self._lock:
            self._d.pop(key, None)


sav_cache = Cache(config.CACHE_SAVS)
dict_cache = Cache(8)


def load_sav(store, pid):
    path = store.sav_path(pid)
    if not os.path.exists(path):
        raise FileNotFoundError("קובץ ה-SAV נמחק לפי מדיניות הניקוי — יש להעלות אותו מחדש")
    key = (pid, os.path.getmtime(path))
    return sav_cache.get(key, lambda: L.load_sav(path))


def load_dictionary(path):
    key = (path, os.path.getmtime(path))
    return dict_cache.get(key, lambda: L.load_dictionary(path))


# ------------------------------------------------------------------------------------------ jobs
class Jobs:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=config.WORKERS, thread_name_prefix="run")
        self.jobs = {}
        self._lock = threading.Lock()

    def submit(self, project_id, fn):
        jid = uuid.uuid4().hex[:12]
        job = dict(id=jid, project_id=project_id, status="queued", stage="ממתין בתור", pct=0, result=None, error=None)
        with self._lock:
            self.jobs[jid] = job

        def wrapped():
            job.update(status="running")
            try:
                job["result"] = fn(lambda stage, pct: job.update(stage=stage, pct=pct))
                job.update(status="done", stage="הסתיים", pct=100)
            except Exception as ex:  # noqa: BLE001 - surfaced to the user, never swallowed
                log.exception("job %s failed", jid)
                job.update(status="error", error=f"{type(ex).__name__}: {ex}")

        self.pool.submit(wrapped)
        return job

    def get(self, jid):
        return self.jobs.get(jid)


jobs = Jobs()
