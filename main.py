"""InEra All-in-One Plugins — web server and REST API.

Run:  python main.py        (or: uvicorn main:app --host 0.0.0.0 --port 8000)
Use ONE process (the built-in scheduler and job runner live inside it); scale
with WORKERS (threads) instead of multiple uvicorn workers.
"""
import sys
sys.dont_write_bytecode = True  # keep the app folder flat: no __pycache__

import datetime as dt
import json
import logging
import re
import shutil
import smtplib
import time
from contextlib import asynccontextmanager
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response

import automations
import brand
import config
import db
import engine
import planner
import plg_pdftools
import security
from llm import engine as llm
from registry import CATEGORIES, PLUGINS, catalog, guess_mime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)  # their INFO lines contain URLs with tokens
log = logging.getLogger("inera")

SESSION_COOKIE, CSRF_COOKIE = "inera_session", "inera_csrf"
STATIC = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/app.css": "app.css",
          "/logo.svg": "logo.svg", "/logo_mark.svg": "logo_mark.svg", "/logo.png": "logo.png",
          "/logo_mark.png": "logo_mark.png", "/favicon.png": "favicon.png", "/marcellus.woff2": "marcellus.woff2",
          "/jost.woff2": "jost.woff2"}
UPLOAD_EXT = {".pdf", ".docx", ".doc", ".odt", ".rtf", ".pptx", ".ppt", ".odp", ".xlsx", ".xls", ".xlsm", ".ods",
              ".csv", ".tsv", ".txt", ".md", ".markdown", ".json", ".html", ".htm", ".xml",
              ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
INLINE_SAFE = {"image/png", "image/jpeg", "image/webp", "image/gif", "application/pdf", "audio/mpeg", "audio/wav",
               "audio/x-wav", "audio/mp4", "video/mp4", "text/plain", "text/markdown", "text/csv", "application/json"}
PROFILE_FIELDS = {"business_name": 120, "industry": 80, "description": 600, "audience": 200, "brand_voice": 120,
                  "website": 200, "instagram": 60, "phone": 40, "public_email": 120, "address": 300, "city": 80,
                  "country": 60, "timezone": 60, "brand_color": 7, "gstin": 20, "upi_id": 80, "bank_details": 300,
                  "tagline": 160, "wiki_lang": 5}
PROFILE_FLAGS = {"auto_approve", "signature"}
VAULT_FIELDS = {
    "instagram": {"ig_user_id": False, "access_token": True},
    "smtp": {"host": False, "port": False, "security": False, "username": False, "password": True,
             "from_email": False, "from_name": False},
    "messenger": {"telegram_bot_token": True, "telegram_chat_id": False, "discord_webhook": True,
                  "slack_webhook": True, "webhook_url": True},
}


@asynccontextmanager
async def lifespan(_app):
    engine.start()
    log.info("InEra started — data dir %s — AI engine: %s", config.DATA_DIR, llm.describe()["label"])
    yield
    engine.stop()


app = FastAPI(title=config.APP_NAME, version=config.APP_VERSION, lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)


class BodyLimit:
    """Counts request-body bytes as they arrive (works for chunked uploads too)."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.inner(scope, receive, send)
        cap = (config.MAX_UPLOAD_MB * config.MAX_FILES_PER_RUN + 5) * 1024 * 1024 \
            if scope.get("path") == "/api/files" else 2 * 1024 * 1024
        seen = 0

        async def limited():
            nonlocal seen
            message = await receive()
            if message.get("type") == "http.request":
                seen += len(message.get("body", b""))
                if seen > cap:
                    raise HTTPException(413, "Request too large.")
            return message
        await self.inner(scope, limited, send)


# ====================================================================== middleware
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "media-src 'self' blob:; connect-src 'self'; frame-src 'self'; frame-ancestors 'self'; base-uri 'none'; "
       "form-action 'self'; object-src 'none'")


@app.middleware("http")
async def security_layer(request: Request, call_next):
    path = request.url.path
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and path.startswith("/api/"):
        cookie = request.cookies.get(CSRF_COOKIE, "")
        header = request.headers.get("x-csrf-token", "")
        if not cookie or not security.hmac_equal(cookie, header):
            return JSONResponse({"detail": "Security token missing or invalid. Reload the page."}, status_code=403)
        if path == "/api/files" and not current_user(request, required=False):
            return JSONResponse({"detail": "Please sign in."}, status_code=401)
        length = request.headers.get("content-length")
        limit = (config.MAX_UPLOAD_MB * config.MAX_FILES_PER_RUN + 5) * 1024 * 1024 if path == "/api/files" \
            else 2 * 1024 * 1024
        if length and length.isdigit() and int(length) > limit:
            return JSONResponse({"detail": "Request too large."}, status_code=413)
    try:
        response = await call_next(request)
    except Exception as exc:
        http_exc = _find_http_exc(exc)
        if http_exc is not None:  # e.g. body limit hit while the request was still streaming
            response = JSONResponse({"detail": http_exc.detail}, status_code=http_exc.status_code)
        else:
            log.exception("unhandled error on %s", path)
            response = JSONResponse({"detail": "Internal error."}, status_code=500)
    h = response.headers
    h.setdefault("Content-Security-Policy", CSP)
    h["X-Content-Type-Options"] = "nosniff"
    h["Referrer-Policy"] = "same-origin"
    h["X-Frame-Options"] = "SAMEORIGIN"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    if config.COOKIE_SECURE:
        h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if path.startswith("/api/"):
        h["Cache-Control"] = "no-store"
    if not request.cookies.get(CSRF_COOKIE):
        response.set_cookie(CSRF_COOKIE, security.new_token(24), httponly=False, samesite="strict",
                            secure=config.COOKIE_SECURE, path="/")
    return response


app.add_middleware(BodyLimit)


def _find_http_exc(exc):
    from starlette.exceptions import HTTPException as StarletteHTTPException
    if isinstance(exc, StarletteHTTPException):
        return exc
    for inner in getattr(exc, "exceptions", ()) or ():
        found = _find_http_exc(inner)
        if found is not None:
            return found
    cause = exc.__cause__ or exc.__context__
    return _find_http_exc(cause) if cause is not None and cause is not exc else None


def client_ip(request: Request) -> str:
    # With TRUST_PROXY, uvicorn already replaced the client address using X-Forwarded-For,
    # but only for requests coming from FORWARDED_ALLOW_IPS (your reverse proxy).
    return request.client.host if request.client else "unknown"


def limit(key: str, n: int, window: float):
    if not security.limiter.allow(key, n, window):
        raise HTTPException(429, "Too many requests — slow down and try again shortly.")


# ====================================================================== auth helpers
def current_user(request: Request, required: bool = True):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        row = db.query_one("SELECT user_id, expires_at FROM sessions WHERE token_hash=?", (security.sha256(token),))
        if row and row["expires_at"] > time.time():
            user = db.get_user(row["user_id"])
            if user:
                if row["expires_at"] - time.time() < (config.SESSION_DAYS - 1) * 86400:
                    db.execute("UPDATE sessions SET expires_at=? WHERE token_hash=?",
                               (time.time() + config.SESSION_DAYS * 86400, security.sha256(token)))
                return user
    if required:
        raise HTTPException(401, "Please sign in.")
    return None


def start_session(request: Request, response: Response, user_id: str):
    token = security.new_token(32)
    db.execute("INSERT INTO sessions (token_hash,user_id,expires_at,created_at,ip,ua) VALUES (?,?,?,?,?,?)",
               (security.sha256(token), user_id, time.time() + config.SESSION_DAYS * 86400, time.time(),
                client_ip(request), request.headers.get("user-agent", "")[:200]))
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=config.COOKIE_SECURE,
                        max_age=config.SESSION_DAYS * 86400, path="/")


def public_user(u: dict) -> dict:
    return {"id": u["id"], "email": u["email"], "name": u["name"], "is_admin": bool(u["is_admin"]),
            "profile": u.get("profile") or {}, "created_at": u["created_at"]}


def clean_profile(raw: dict, existing: dict = None) -> dict:
    prof = dict(existing or {})
    for key, maxlen in PROFILE_FIELDS.items():
        if key in raw:
            prof[key] = str(raw.get(key) or "").strip()[:maxlen]
    for key in PROFILE_FLAGS:
        if key in raw:
            prof[key] = bool(raw[key])
    tz = prof.get("timezone") or "UTC"
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        prof["timezone"] = "UTC"
    if prof.get("brand_color") and not re.fullmatch(r"#[0-9a-fA-F]{6}", prof["brand_color"]):
        prof["brand_color"] = ""
    prof.setdefault("signature", True)
    prof.setdefault("auto_approve", False)
    return prof


async def body(request: Request) -> dict:
    try:
        data = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, "Invalid JSON body.")
    if not isinstance(data, dict):
        raise HTTPException(400, "Invalid JSON body.")
    return data


# ====================================================================== static
def _static(name: str, max_age: int):
    path = config.APP_DIR / name
    media = {".js": "text/javascript", ".woff2": "font/woff2", ".css": "text/css", ".html": "text/html",
             ".svg": "image/svg+xml"}.get(path.suffix, guess_mime(name))
    resp = FileResponse(path, media_type=media)
    resp.headers["Cache-Control"] = f"public, max-age={max_age}" if max_age else "no-cache"
    return resp


for _route, _file in STATIC.items():
    def _make(file=_file):
        async def handler():
            return _static(file, 0 if file.endswith((".html", ".js", ".css")) else 86400)
        return handler
    app.add_api_route(_route, _make(), methods=["GET"], include_in_schema=False)


@app.get("/api/health")
async def health():
    return {"ok": True, "version": config.APP_VERSION, "time": time.time()}


@app.get("/api/config")
async def get_config(request: Request):
    user = current_user(request, required=False)
    return {"app": config.APP_NAME, "version": config.APP_VERSION, "registration": config.ALLOW_REGISTRATION,
            "user": public_user(user) if user else None, "engine": llm.describe(),
            "capabilities": {"tts": brand.tts_engine(), "ffmpeg": bool(brand.ffmpeg_bin()),
                             "office": bool(plg_pdftools._soffice()), "ocr": _ocr_ok(),
                             "public_url": config.PUBLIC_BASE_URL.startswith("https://"),
                             "web_research": config.WEB_RESEARCH},
            "limits": {"max_upload_mb": config.MAX_UPLOAD_MB, "max_files": config.MAX_FILES_PER_RUN,
                       "runs_per_day": config.MAX_RUNS_PER_DAY},
            "categories": [{"id": c, "label": l} for c, l in CATEGORIES]}


def _ocr_ok() -> bool:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


# ====================================================================== auth
@app.post("/api/auth/register")
async def register(request: Request):
    if not config.ALLOW_REGISTRATION:
        raise HTTPException(403, "Registration is closed on this server.")
    limit(f"reg:{client_ip(request)}", 6, 3600)
    data = await body(request)
    email = str(data.get("email", "")).strip().lower()
    name = str(data.get("name", "")).strip()[:80]
    password = str(data.get("password", ""))
    if not security.valid_email(email):
        raise HTTPException(400, "Enter a valid e-mail address.")
    if len(name) < 2:
        raise HTTPException(400, "Enter your name.")
    problem = security.password_problem(password, email)
    if problem:
        raise HTTPException(400, problem)
    if not data.get("accept_terms"):
        raise HTTPException(400, "Please accept the terms and privacy notice.")
    profile = clean_profile(data.get("profile") or {})
    if not profile.get("business_name"):
        raise HTTPException(400, "Tell us your business or brand name (use your own name if you're an individual).")
    pw_hash = await run_in_threadpool(security.hash_password, password)
    uid = db.new_id("u_")
    is_admin = 1 if (db.count_users() == 0 or email in config.ADMIN_EMAILS) else 0
    try:
        db.execute("INSERT INTO users (id,email,pw_hash,name,is_admin,profile_json,created_at) VALUES (?,?,?,?,?,?,?)",
                   (uid, email, pw_hash, name, is_admin, db.jdump(profile), time.time()))
    except Exception:
        raise HTTPException(409, "An account with this e-mail already exists. Sign in instead.")
    resp = JSONResponse({"user": public_user(db.get_user(uid))})
    start_session(request, resp, uid)
    return resp


@app.post("/api/auth/login")
async def login(request: Request):
    data = await body(request)
    email = str(data.get("email", "")).strip().lower()
    ip = client_ip(request)
    limit(f"login-ip:{ip}", 20, 300)
    limit(f"login-email:{email}", 8, 300)
    user = db.get_user_by_email(email) if email else None
    ok = await run_in_threadpool(security.verify_password, str(data.get("password", "")),
                                 user["pw_hash"] if user else security.DUMMY_HASH)
    if not user or not ok:
        raise HTTPException(401, "Wrong e-mail or password.")
    resp = JSONResponse({"user": public_user(user)})
    start_session(request, resp, user["id"])
    return resp


@app.post("/api/auth/logout")
async def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (security.sha256(token),))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@app.get("/api/me")
async def me(request: Request):
    return {"user": public_user(current_user(request))}


@app.put("/api/me")
async def update_me(request: Request):
    user = current_user(request)
    data = await body(request)
    name = str(data.get("name") or user["name"]).strip()[:80]
    profile = clean_profile(data.get("profile") or {}, user["profile"])
    db.execute("UPDATE users SET name=?, profile_json=? WHERE id=?", (name, db.jdump(profile), user["id"]))
    return {"user": public_user(db.get_user(user["id"]))}


@app.post("/api/me/password")
async def change_password(request: Request):
    user = current_user(request)
    limit(f"pw:{user['id']}", 5, 600)
    data = await body(request)
    if not await run_in_threadpool(security.verify_password, str(data.get("current", "")), user["pw_hash"]):
        raise HTTPException(400, "Current password is wrong.")
    new = str(data.get("new", ""))
    problem = security.password_problem(new, user["email"])
    if problem:
        raise HTTPException(400, problem)
    db.execute("UPDATE users SET pw_hash=? WHERE id=?", (await run_in_threadpool(security.hash_password, new), user["id"]))
    token = request.cookies.get(SESSION_COOKIE, "")
    db.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (user["id"], security.sha256(token)))
    return {"ok": True}


@app.get("/api/me/export")
async def export_me(request: Request):
    user = current_user(request)
    data = {"exported_at": dt.datetime.utcnow().isoformat() + "Z", "user": public_user(user),
            "jobs": [{k: j[k] for k in ("id", "problem", "status", "created_at", "finished_at")}
                     for j in db.query("SELECT * FROM jobs WHERE user_id=? ORDER BY created_at DESC", (user["id"],))],
            "automations": [automations.public(a) for a in db.query("SELECT * FROM automations WHERE user_id=?",
                                                                    (user["id"],))],
            "files": db.query("SELECT id,name,mime,size,origin,created_at FROM files WHERE user_id=?", (user["id"],)),
            "vault_connections": [r["kind"] for r in db.query("SELECT kind FROM secrets WHERE user_id=?", (user["id"],))]}
    return Response(json.dumps(data, indent=2, default=str), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="inera-my-data.json"'})


@app.delete("/api/me")
async def delete_me(request: Request):
    user = current_user(request)
    data = await body(request)
    if not await run_in_threadpool(security.verify_password, str(data.get("password", "")), user["pw_hash"]):
        raise HTTPException(400, "Password is wrong.")
    db.execute("DELETE FROM users WHERE id=?", (user["id"],))
    shutil.rmtree(config.FILES_DIR / user["id"], ignore_errors=True)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


# ====================================================================== plugins & plans
@app.get("/api/plugins")
async def plugins(request: Request):
    current_user(request)
    return {"plugins": catalog(), "categories": [{"id": c, "label": l} for c, l in CATEGORIES]}


def _plan_public(plan: dict) -> dict:
    steps = []
    for s in plan.get("steps", []):
        p = PLUGINS.get(s["plugin"])
        if not p:
            continue
        steps.append({"plugin": p.id, "name": p.name, "icon": p.icon, "category": p.category,
                      "side_effect": p.side_effect, "status": s.get("status", "pending"), "error": s.get("error"),
                      "seconds": s.get("seconds")})
    return {"steps": steps, "summary": plan.get("summary", ""), "notes": plan.get("notes", []),
            "title": plan.get("title", ""), "topic": plan.get("topic", ""), "engine": plan.get("engine", "rules"),
            "schedule": plan.get("schedule"),
            "schedule_text": automations.describe(plan["schedule"]) if plan.get("schedule") else ""}


@app.post("/api/plan")
async def preview_plan(request: Request):
    user = current_user(request)
    limit(f"plan:{user['id']}", 30, 60)
    data = await body(request)
    problem = str(data.get("problem", "")).strip()[:8000]
    if not problem:
        raise HTTPException(400, "Describe the problem first.")
    files = engine._user_files(user["id"], [str(i) for i in (data.get("file_ids") or [])][:config.MAX_FILES_PER_RUN])
    plan = await run_in_threadpool(planner.make_plan, problem, files, user)
    return _plan_public(plan)


@app.post("/api/run")
async def run(request: Request):
    user = current_user(request)
    limit(f"run:{user['id']}", 20, 60)
    data = await body(request)
    try:
        job_id = engine.create_job(user, str(data.get("problem", "")),
                                   [str(i) for i in (data.get("file_ids") or [])][:config.MAX_FILES_PER_RUN])
    except engine.QuotaError as exc:
        raise HTTPException(429, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"job_id": job_id}


def _job_public(j: dict, full: bool = True) -> dict:
    plan = db.jload(j["plan_json"], {})
    outputs = db.jload(j["outputs_json"], [])
    out = {"id": j["id"], "problem": j["problem"], "status": j["status"], "progress": j["progress"],
           "created_at": j["created_at"], "finished_at": j["finished_at"], "source": j["source"],
           "automation_id": j["automation_id"], "title": plan.get("title") or "", "error": j["error"],
           "output_count": len(outputs)}
    if full:
        state = db.jload(j["state_json"], {})
        out.update({"plan": _plan_public(plan), "log": db.jload(j["log_json"], []), "outputs": outputs,
                    "automation_created": state.get("automation_id"),
                    "instagram": state.get("instagram")})
    else:
        out["plugins"] = [s["plugin"] for s in plan.get("steps", [])]
    return out


@app.get("/api/jobs")
async def list_jobs(request: Request, limit_: int = 50):
    user = current_user(request)
    rows = db.query("SELECT * FROM jobs WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                    (user["id"], max(1, min(200, limit_))))
    return {"jobs": [_job_public(r, full=False) for r in rows]}


def _own_job(request, job_id):
    user = current_user(request)
    j = db.query_one("SELECT * FROM jobs WHERE id=? AND user_id=?", (job_id, user["id"]))
    if not j:
        raise HTTPException(404, "Run not found.")
    return user, j


@app.get("/api/jobs/{job_id}")
async def get_job(request: Request, job_id: str):
    _, j = _own_job(request, job_id)
    return _job_public(j)


@app.post("/api/jobs/{job_id}/approve")
async def approve(request: Request, job_id: str):
    user, _ = _own_job(request, job_id)
    if not engine.approve_job(job_id, user["id"]):
        raise HTTPException(409, "This run is not waiting for approval.")
    return {"ok": True}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel(request: Request, job_id: str):
    user, _ = _own_job(request, job_id)
    if not engine.cancel_job(job_id, user["id"]):
        raise HTTPException(409, "This run can't be cancelled now.")
    return {"ok": True}


@app.delete("/api/jobs/{job_id}")
async def delete_job(request: Request, job_id: str):
    user, j = _own_job(request, job_id)
    if j["status"] in engine.ACTIVE:
        raise HTTPException(409, "Cancel the run first.")
    db.execute("DELETE FROM files WHERE job_id=? AND user_id=?", (job_id, user["id"]))
    db.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    shutil.rmtree(config.FILES_DIR / user["id"] / job_id, ignore_errors=True)
    return {"ok": True}


# ====================================================================== automations
@app.get("/api/automations")
async def list_automations(request: Request):
    user = current_user(request)
    rows = db.query("SELECT * FROM automations WHERE user_id=? ORDER BY created_at DESC", (user["id"],))
    return {"automations": [automations.public(a) for a in rows]}


@app.post("/api/automations/{aid}/{action}")
async def automation_action(request: Request, aid: str, action: str):
    user = current_user(request)
    a = db.query_one("SELECT * FROM automations WHERE id=? AND user_id=?", (aid, user["id"]))
    if not a:
        raise HTTPException(404, "Automation not found.")
    if action == "approve":
        db.execute("UPDATE automations SET approved=1 WHERE id=?", (aid,))
    elif action == "pause":
        db.execute("UPDATE automations SET enabled=0 WHERE id=?", (aid,))
    elif action == "resume":
        nxt = automations.next_run(db.jload(a["schedule_json"], {}), a["timezone"])
        if not nxt:
            raise HTTPException(409, "This schedule has no future runs. Edit the schedule first.")
        db.execute("UPDATE automations SET enabled=1, next_run_at=? WHERE id=?", (nxt.timestamp(), aid))
    elif action == "run":
        limit(f"autorun:{user['id']}", 10, 60)
        try:
            job_id = engine.run_automation_now(aid, user)
        except (ValueError, engine.QuotaError) as exc:
            raise HTTPException(409, str(exc))
        return {"ok": True, "job_id": job_id}
    elif action == "schedule":
        data = await body(request)
        sched = planner.parse_schedule(str(data.get("text", "")), a["timezone"], True)
        if not sched:
            raise HTTPException(400, "I couldn't read that schedule. Try “every day at 8 am” or “every Monday at 6 pm”.")
        nxt = automations.next_run(sched, a["timezone"])
        db.execute("UPDATE automations SET schedule_json=?, next_run_at=?, enabled=? WHERE id=?",
                   (db.jdump(sched), nxt.timestamp() if nxt else None, a["enabled"] if nxt else 0, aid))
    else:
        raise HTTPException(404, "Unknown action.")
    return {"automation": automations.get(aid, user["id"])}


@app.delete("/api/automations/{aid}")
async def delete_automation(request: Request, aid: str):
    user = current_user(request)
    if not db.execute("DELETE FROM automations WHERE id=? AND user_id=?", (aid, user["id"])):
        raise HTTPException(404, "Automation not found.")
    return {"ok": True}


# ====================================================================== files
def _sniff_ok(path: Path, ext: str) -> bool:
    head = path.read_bytes()[:16] if path.stat().st_size else b""
    if ext == ".pdf":
        return head.startswith(b"%PDF")
    if ext in (".docx", ".pptx", ".xlsx", ".xlsm", ".odt", ".odp", ".ods"):
        return head.startswith(b"PK")
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"):
        try:
            from PIL import Image
            with Image.open(path) as im:
                if im.width * im.height > 50_000_000:
                    return False
                im.verify()
            return True
        except Exception:
            return False
    return True


@app.post("/api/files")
async def upload(request: Request, files: list[UploadFile] = File(...)):
    user = current_user(request)
    limit(f"upload:{user['id']}", 60, 60)
    if len(files) > config.MAX_FILES_PER_RUN:
        raise HTTPException(400, f"Upload at most {config.MAX_FILES_PER_RUN} files at once.")
    folder = config.FILES_DIR / user["id"] / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    saved = []
    for up in files:
        name = security.safe_filename(up.filename or "file")
        ext = Path(name).suffix.lower()
        if ext not in UPLOAD_EXT:
            raise HTTPException(400, f"{name}: this file type isn't supported.")
        fid = db.new_id("f_")
        dest = folder / f"{fid}{ext}"
        size, cap = 0, config.MAX_UPLOAD_MB * 1024 * 1024
        with open(dest, "wb") as fh:
            while True:
                chunk = await up.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > cap:
                    fh.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(413, f"{name} is larger than {config.MAX_UPLOAD_MB} MB.")
                fh.write(chunk)
        if size == 0 or not await run_in_threadpool(_sniff_ok, dest, ext):
            dest.unlink(missing_ok=True)
            raise HTTPException(400, f"{name} looks empty or corrupted.")
        mime = guess_mime(name)
        db.execute("INSERT INTO files (id,user_id,name,path,mime,size,origin,kind,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                   (fid, user["id"], name, str(dest), mime, size, "upload", "file", time.time()))
        saved.append({"id": fid, "name": name, "size": size, "mime": mime})
    return {"files": saved}


@app.get("/api/files")
async def list_files(request: Request, origin: str = ""):
    user = current_user(request)
    sql = "SELECT id,name,mime,size,origin,kind,label,job_id,created_at FROM files WHERE user_id=?"
    params = [user["id"]]
    if origin in ("upload", "output"):
        sql += " AND origin=?"
        params.append(origin)
    rows = db.query(sql + " ORDER BY created_at DESC LIMIT 500", tuple(params))
    return {"files": rows}


@app.get("/api/files/{fid}")
async def download(request: Request, fid: str, inline: int = 0):
    user = current_user(request)
    f = db.query_one("SELECT * FROM files WHERE id=? AND user_id=?", (fid, user["id"]))
    if not f or not Path(f["path"]).exists():
        raise HTTPException(404, "File not found.")
    path = Path(f["path"]).resolve()
    if config.FILES_DIR.resolve() not in path.parents:
        raise HTTPException(404, "File not found.")
    mime = f["mime"]
    headers = {"Cache-Control": "private, no-store"}
    if inline and mime in INLINE_SAFE:
        media = "text/plain; charset=utf-8" if mime in ("text/markdown", "text/csv") else mime
        resp = FileResponse(path, media_type=media, headers=headers, content_disposition_type="inline",
                            filename=f["name"])
    elif inline and mime == "text/html":
        resp = FileResponse(path, media_type="text/html", headers=headers, content_disposition_type="inline",
                            filename=f["name"])
        resp.headers["Content-Security-Policy"] = ("sandbox; default-src 'none'; img-src data: https:; "
                                                   "style-src 'unsafe-inline'; font-src data:")
    else:
        resp = FileResponse(path, media_type=mime, headers=headers, filename=f["name"])
    return resp


@app.delete("/api/files/{fid}")
async def delete_file(request: Request, fid: str):
    user = current_user(request)
    f = db.query_one("SELECT * FROM files WHERE id=? AND user_id=?", (fid, user["id"]))
    if not f:
        raise HTTPException(404, "File not found.")
    Path(f["path"]).unlink(missing_ok=True)
    db.execute("DELETE FROM files WHERE id=?", (fid,))
    return {"ok": True}


@app.get("/p/{token}.jpg")
async def public_media(token: str):
    """Short-lived public link used only so Instagram's servers can fetch a post image."""
    if not re.fullmatch(r"[\w-]{20,64}", token):
        raise HTTPException(404)
    f = db.query_one("SELECT path, mime, public_expires FROM files WHERE public_token=?", (token,))
    if not f or not f["public_expires"] or f["public_expires"] < time.time() or f["mime"] != "image/jpeg":
        raise HTTPException(404)
    return FileResponse(f["path"], media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# ====================================================================== vault
@app.get("/api/vault")
async def get_vault(request: Request):
    user = current_user(request)
    out = {}
    rows = {r["kind"]: r for r in db.query("SELECT * FROM secrets WHERE user_id=?", (user["id"],))}
    for kind, fields in VAULT_FIELDS.items():
        data = security.decrypt_json(rows[kind]["data_enc"]) if kind in rows else {}
        out[kind] = {"configured": kind in rows, "updated_at": rows[kind]["updated_at"] if kind in rows else None,
                     "fields": {k: (security.mask(data.get(k, "")) if secret else data.get(k, ""))
                                for k, secret in fields.items()}}
    return {"vault": out}


@app.put("/api/vault/{kind}")
async def put_vault(request: Request, kind: str):
    user = current_user(request)
    if kind not in VAULT_FIELDS:
        raise HTTPException(404, "Unknown connection.")
    data = await body(request)
    row = db.query_one("SELECT data_enc FROM secrets WHERE user_id=? AND kind=?", (user["id"], kind))
    current = security.decrypt_json(row["data_enc"]) if row else {}
    for key in VAULT_FIELDS[kind]:
        if key in data:
            val = str(data[key] or "").strip()[:2000]
            if val and "•" not in val:
                current[key] = val
            elif val == "" and not VAULT_FIELDS[kind][key]:
                current[key] = ""
    if kind == "instagram" and current.get("ig_user_id") and not str(current["ig_user_id"]).isdigit():
        raise HTTPException(400, "Instagram user ID must be numeric (find it via the Graph API /me endpoint).")
    if kind == "smtp":
        if current.get("port") and not str(current["port"]).isdigit():
            raise HTTPException(400, "Port must be a number (587 for STARTTLS, 465 for SSL).")
        if current.get("security") and current["security"] not in ("starttls", "ssl", "none"):
            current["security"] = "starttls"
    db.execute("INSERT INTO secrets (user_id,kind,data_enc,updated_at) VALUES (?,?,?,?) "
               "ON CONFLICT(user_id,kind) DO UPDATE SET data_enc=excluded.data_enc, updated_at=excluded.updated_at",
               (user["id"], kind, security.encrypt_json(current), time.time()))
    return {"ok": True}


@app.delete("/api/vault/{kind}")
async def delete_vault(request: Request, kind: str):
    user = current_user(request)
    db.execute("DELETE FROM secrets WHERE user_id=? AND kind=?", (user["id"], kind))
    return {"ok": True}


@app.post("/api/vault/{kind}/test")
async def test_vault(request: Request, kind: str):
    user = current_user(request)
    limit(f"vtest:{user['id']}", 10, 60)
    row = db.query_one("SELECT data_enc FROM secrets WHERE user_id=? AND kind=?", (user["id"], kind))
    if not row:
        raise HTTPException(400, "Save the connection first.")
    cfg = security.decrypt_json(row["data_enc"])

    def check():
        if kind == "instagram":
            r = httpx.get(f"https://{config.IG_GRAPH_HOST}/{config.IG_GRAPH_VERSION}/me",
                          params={"fields": "user_id,username", "access_token": cfg.get("access_token", "")}, timeout=20)
            if r.status_code >= 400:
                return False, "Instagram rejected the token: " + r.text[:200]
            d = r.json()
            return True, f"Connected as @{d.get('username', '?')} (user id {d.get('user_id', d.get('id', '?'))})."
        if kind == "smtp":
            port = int(cfg.get("port") or 587)
            mode = cfg.get("security") or ("ssl" if port == 465 else "starttls")
            server = security.smtp_connect(cfg.get("host", ""), port, mode, timeout=20)
            try:
                server.login(cfg.get("username", ""), cfg.get("password", ""))
            finally:
                try:
                    server.quit()
                except Exception:
                    pass
            return True, "Mailbox login succeeded."
        if kind == "messenger":
            from plg_social import messenger as _m  # noqa: F401
            results = []
            if cfg.get("telegram_bot_token"):
                r = httpx.get(f"https://api.telegram.org/bot{cfg['telegram_bot_token']}/getMe", timeout=15)
                results.append("Telegram ✓" if r.status_code == 200 else "Telegram ✗ (token rejected)")
            for key, label, prefix in (("discord_webhook", "Discord", "https://discord.com/api/webhooks/"),
                                       ("slack_webhook", "Slack", "https://hooks.slack.com/")):
                if cfg.get(key):
                    ok = cfg[key].startswith(prefix) or (label == "Discord" and
                                                          cfg[key].startswith("https://discordapp.com/api/webhooks/"))
                    results.append(f"{label} {'✓ format OK' if ok else '✗ invalid URL'}")
            if cfg.get("webhook_url"):
                try:
                    security.assert_public_url(cfg["webhook_url"])
                    results.append("Webhook ✓ address allowed")
                except security.UnsafeURL as exc:
                    results.append(f"Webhook ✗ {exc}")
            return (bool(results) and all("✗" not in r for r in results)), ", ".join(results) or "Nothing configured."
        return False, "Unknown connection."
    try:
        ok, msg = await run_in_threadpool(check)
    except (security.UnsafeURL, smtplib.SMTPException, OSError, httpx.HTTPError, ValueError) as exc:
        ok, msg = False, f"{type(exc).__name__}: {str(exc)[:200]}"
    return {"ok": ok, "message": msg}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, proxy_headers=config.TRUST_PROXY,
                forwarded_allow_ips=config.FORWARDED_ALLOW_IPS, log_level="info")
