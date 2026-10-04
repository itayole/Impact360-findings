"""Impact360 SAV Runner — FastAPI app (API + static frontend).  No outbound network calls anywhere."""
import base64
from contextlib import asynccontextmanager
import hmac
import logging
import os
import re
import shutil
import tempfile
import threading
from urllib.parse import quote, unquote

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from svr import lib as L
from svr import templates as T

from . import config, runtime, service
from .store import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("i360")

store = Store()


@asynccontextmanager
async def lifespan(_app):
    _cleanup_loop()
    log.info("Impact360 SAV Runner %s ready (data=%s)", service.APP_VERSION, store.root)
    yield


app = FastAPI(title="Impact360 SAV Runner", version=service.APP_VERSION, docs_url=None, redoc_url=None, openapi_url=None,       # Swagger UI loads JS from a CDN: not allowed here
              
              lifespan=lifespan)


# ------------------------------------------------------------------------------------------ plumbing
def user_of(request: Request):
    return unquote(request.headers.get("x-user") or "anonymous")[:60]


@app.middleware("http")
async def guard(request: Request, call_next):
    if config.BASIC_AUTH_USER and request.url.path != "/api/health":
        ok = False
        h = request.headers.get("authorization", "")
        if h.lower().startswith("basic "):
            try:
                u, _, pw = base64.b64decode(h[6:]).decode("utf-8").partition(":")
                ok = (bool(config.BASIC_AUTH_PASS)               # a user without a password configured is a misconfiguration: never let anyone in
                      and hmac.compare_digest(u.encode("utf-8"), config.BASIC_AUTH_USER.encode("utf-8"))
                      and hmac.compare_digest(pw.encode("utf-8"), config.BASIC_AUTH_PASS.encode("utf-8")))
            except Exception:  # noqa: BLE001
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Impact360"'})
    resp = await call_next(request)
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"        # respondent-derived aggregates must not linger in browser caches
    elif not request.url.path.startswith("/fonts/"):
        resp.headers["Cache-Control"] = "no-cache"        # always revalidate app.js/css/html so upgrades reach users at once
    return resp


@app.exception_handler(service.Bad)
async def bad_handler(request, exc):
    return JSONResponse(status_code=400, content=dict(detail=str(exc)))


@app.exception_handler(KeyError)
async def key_handler(request, exc):
    return JSONResponse(status_code=404, content=dict(detail="הפרויקט לא נמצא — ייתכן שנמחק. חזור/י לשלב 1 (פרויקט חדש / קיימים)"))


@app.exception_handler(FileNotFoundError)
async def gone_handler(request, exc):
    # OS errors carry file paths: only our own (Hebrew, path-free) messages are shown
    msg = str(exc) if (exc.filename is None and exc.args and isinstance(exc.args[0], str) and exc.args[0]) else "הקובץ לא קיים עוד"
    return JSONResponse(status_code=410, content=dict(detail=msg))


def _disposition(fn):
    """Content-Disposition for a download (UTF-8 name, percent-encoded). Kept out of an f-string: Python 3.11 (the image) rejects nested same-type quotes."""
    return "attachment; filename*=UTF-8''" + quote(_safe_name(fn), safe="")


def _safe_name(fn):
    """Download name: no path separators, quotes or control characters."""
    return re.sub(r'[\\/"\x00-\x1f]+', "_", fn or "") or "download"


async def _save_upload(up: UploadFile, suffix):
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    fd, path = tempfile.mkstemp(suffix=suffix, dir=store.uploads)
    size = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = await up.read(1 << 20)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"הקובץ גדול מ-{config.MAX_UPLOAD_MB}MB")
                out.write(chunk)
    except Exception:
        if os.path.exists(path):
            os.remove(path)
        raise
    return path


# ------------------------------------------------------------------------------------------ meta
@app.get("/api/health")
def health():
    ok = os.access(store.root, os.W_OK)
    return JSONResponse(status_code=200 if ok else 503, content=dict(status="ok" if ok else "data dir not writable"))


@app.get("/api/version")
def version():
    d = store.active_dictionary()
    return dict(**service.build_info(), dictionary=L.dictionary_version(store.dictionary_path(d)) if d else None)


# ------------------------------------------------------------------------------------------ projects
@app.get("/api/projects")
def projects():
    return store.projects_list()


@app.post("/api/projects")
async def create_project(request: Request, sav: UploadFile = File(...), qnr: UploadFile = File(None), name: str = Form(""),
                         dictionary: str = Form("")):
    if not (sav.filename or "").lower().endswith(".sav"):
        raise service.Bad("יש להעלות קובץ .sav")
    sav_path = await _save_upload(sav, ".sav")
    qnr_path = None
    try:
        if qnr is not None and qnr.filename:
            if not qnr.filename.lower().endswith(".docx"):
                raise service.Bad("השאלון חייב להיות בפורמט .docx")
            qnr_path = await _save_upload(qnr, ".docx")
    except BaseException:
        os.remove(sav_path)                      # never leave the first upload behind when the second one fails
        raise
    log.info("upload project sav=%r bytes=%s", (sav.filename or "")[:80], os.path.getsize(sav_path))
    return service.create_project(store, name, sav_path, sav.filename, qnr_path, qnr.filename if qnr_path else "",
                                  dictionary or None, user_of(request))


@app.get("/api/projects/{pid}")
def project(pid: str):
    p = store.project(pid)
    p["has_mapping"] = store.mapping(pid) is not None
    p["has_sav"] = os.path.exists(store.sav_path(pid))
    p["has_output"] = os.path.exists(store.output_path(pid))
    p["last_run"] = store.load_json(pid, "last_run.json")
    return p


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    store.project(pid)
    store.delete_project(pid)
    return dict(ok=True)


@app.post("/api/projects/{pid}/sav")
async def reattach(pid: str, sav: UploadFile = File(...)):
    store.project(pid)                           # 404 before anything is written
    if not (sav.filename or "").lower().endswith(".sav"):
        raise service.Bad("יש להעלות קובץ .sav")
    path = await _save_upload(sav, ".sav")
    return service.reattach_sav(store, pid, path)


@app.post("/api/projects/{pid}/profile")
def profile(pid: str, request: Request, body: dict = Body(...)):
    return service.run_profile(store, pid, name=body.get("name", ""), brand=body.get("brand", ""), campaign_id=body.get("campaign_id", ""),
                               omnibus=bool(body.get("omnibus")), template_id=body.get("template_id"),
                               template_version=body.get("template_version"), user=user_of(request))


@app.get("/api/projects/{pid}/review")
def review(pid: str):
    return service.review_payload(store, pid)


@app.put("/api/projects/{pid}/mapping")
def update_mapping(pid: str, request: Request, body: dict = Body(...)):
    service.apply_patch(store, pid, body, user_of(request))
    return service.review_payload(store, pid)


@app.get("/api/projects/{pid}/catalog")
def catalog(pid: str):
    return service.coded_blocks(store, pid)


@app.post("/api/projects/{pid}/preview")
def preview(pid: str, body: dict = Body(default={})):
    return service.preview(store, pid, body.get("block"), body.get("nets"))


@app.get("/api/projects/{pid}/results")
def results(pid: str):
    return service.results(store, pid)


@app.get("/api/projects/{pid}/charts")
def charts(pid: str):
    store.project(pid)
    return service.charts(store, pid)


@app.put("/api/projects/{pid}/charts/settings")
def charts_settings(pid: str, body: dict = Body(...)):
    store.project(pid)
    return service.save_chart_settings(store, pid, body)


@app.post("/api/projects/{pid}/charts/base")
async def charts_base(pid: str, request: Request, file: UploadFile = File(...)):
    store.project(pid)
    fn = file.filename or ""
    if not fn.lower().endswith((".pptx", ".potx")):
        raise service.Bad("יש להעלות קובץ .pptx או .potx")
    path = await _save_upload(file, ".pptx")
    try:
        return service.set_chart_base(store, pid, path, fn, user_of(request))
    finally:
        if os.path.exists(path):
            os.remove(path)


@app.delete("/api/projects/{pid}/charts/base")
def charts_base_delete(pid: str, request: Request):
    store.project(pid)
    service.remove_chart_base(store, pid, user_of(request))
    return dict(ok=True)


@app.get("/api/projects/{pid}/charts.pptx")
def charts_pptx(pid: str):
    store.project(pid)
    data, fn = service.charts_pptx(store, pid)
    return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    headers={"Content-Disposition": _disposition(fn)})


@app.get("/api/projects/{pid}/variables")
def variables(pid: str):
    store.project(pid)
    return service.variables(store, pid)


@app.get("/api/projects/{pid}/variables/{name}")
def variable_values(pid: str, name: str):
    store.project(pid)
    return service.variable_values(store, pid, name)


@app.get("/api/projects/{pid}/snapshots")
def snapshots(pid: str):
    store.project(pid)
    return store.snapshots(pid)


@app.post("/api/projects/{pid}/snapshots")
def create_snapshot(pid: str, request: Request, body: dict = Body(...)):
    return service.save_snapshot(store, pid, body.get("name", ""), user_of(request))


@app.post("/api/projects/{pid}/snapshots/{sid}/load")
def load_snapshot(pid: str, sid: str, request: Request):
    return service.load_snapshot(store, pid, sid, user_of(request))


@app.delete("/api/projects/{pid}/snapshots/{sid}")
def delete_snapshot(pid: str, sid: str):
    store.delete_snapshot(pid, sid)
    return dict(ok=True)


@app.get("/api/projects/{pid}/warnings")
def warnings(pid: str):
    return service.warnings(store, pid)


@app.get("/api/projects/{pid}/decisions")
def decisions(pid: str):
    m = store.mapping(pid) or {}
    return m.get("decisions", [])


@app.post("/api/projects/{pid}/run")
def run(pid: str, request: Request):
    job = service.start_run(store, pid, user_of(request))
    return dict(job_id=job["id"])


@app.get("/api/jobs/{jid}")
def job(jid: str):
    j = runtime.jobs.get(jid)
    if not j:
        raise KeyError(jid)
    return j


@app.get("/api/projects/{pid}/download")
def download(pid: str):
    p = store.project(pid)
    path = store.output_path(pid)
    if not os.path.exists(path):
        raise service.Bad("טרם הופק קובץ — יש להריץ קודם")
    res = store.load_json(pid, "last_run.json", {}) or {}
    fn = res.get("filename") or f"{p['name']}_FINDINGS_SAV.xlsx"
    return FileResponse(path, filename=fn,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": _disposition(fn)})


# ------------------------------------------------------------------------------------------ library
@app.get("/api/library/templates")
def templates():
    return T.Library(store.library).list()


@app.get("/api/library/templates/{tid}")
def template(tid: str):
    t = T.Library(store.library).get(tid)
    if not t:
        raise KeyError(tid)
    t.pop("fingerprint", None)
    return t


@app.get("/api/library/templates/{tid}/history")
def template_history(tid: str):
    return T.Library(store.library).history(tid)


@app.post("/api/library/templates")
def save_template(request: Request, body: dict = Body(...)):
    if not (body.get("name") or "").strip():
        raise service.Bad("חסר שם תבנית")
    return service.save_template(store, body["project_id"], body["name"].strip(), user_of(request), body.get("client", ""),
                                 body.get("tracker", ""), body.get("template_id"))


@app.get("/api/library/dictionaries")
def dictionaries():
    return store.dictionaries()


@app.get("/api/library/dictionary/vars")
def dictionary_vars(file: str = ""):
    vars_, codes = runtime.load_dictionary(store.dictionary_path(file or None))
    return [dict(var=v, title=d["title"], module=d["module"], type=d["type"]) for v, d in vars_.items()
            if not str(d["base"]).startswith("Computed")]


@app.post("/api/library/dictionaries")
async def upload_dictionary(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise service.Bad("המילון חייב להיות קובץ .xlsx")
    path = await _save_upload(file, ".xlsx")
    try:
        vars_, codes = L.load_dictionary(path)
        if not vars_:
            raise ValueError("no variables")
    except Exception as ex:  # noqa: BLE001
        os.remove(path)
        raise service.Bad(f"המילון אינו תקין (נדרשים הגליונות DATA_Dictionary ו-DATA_Dictionary_CODES): {type(ex).__name__}")
    dest = os.path.join(store.dicts, os.path.basename(file.filename))
    if os.path.exists(dest):
        os.remove(path)
        raise service.Bad("קיים כבר מילון בשם זה — שנה/י את שם הקובץ (כל גרסה נשמרת בנפרד)")
    shutil.move(path, dest)
    return dict(ok=True, file=os.path.basename(dest), variables=len(vars_))


@app.put("/api/library/dictionary/active")
def set_active_dictionary(body: dict = Body(...)):
    store.set_active_dictionary(body["file"])
    return dict(ok=True)


# ------------------------------------------------------------------------------------------ housekeeping + static
def _cleanup_loop():
    try:
        store.cleanup()
    except Exception:  # noqa: BLE001
        log.exception("cleanup failed")
    t = threading.Timer(3600, _cleanup_loop)
    t.daemon = True
    t.start()



def _asset_version():
    """Changes whenever app.js / style.css change, so a browser can never keep serving a stale copy."""
    m = 0
    for f in ("app.js", "style.css", "index.html"):
        p = os.path.join(config.STATIC_DIR, f)
        if os.path.exists(p):
            m = max(m, int(os.path.getmtime(p)))
    return f"{service.APP_VERSION}-{m}"


@app.get("/", include_in_schema=False)
@app.get("/index.html", include_in_schema=False)
def index():
    with open(os.path.join(config.STATIC_DIR, "index.html"), encoding="utf-8") as f:
        html = f.read().replace("{{v}}", _asset_version())
    return Response(html, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})


if os.path.isdir(config.STATIC_DIR):
    app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")
