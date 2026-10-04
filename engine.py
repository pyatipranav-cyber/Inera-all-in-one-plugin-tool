"""Agentic execution engine: background job runner, approval gate for actions
that leave the platform, recurring-automation scheduler and housekeeping."""
import datetime as dt
import logging
import shutil
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import automations
import config
import db
import planner
# importing the plugin modules registers every plugin
import plg_content  # noqa: F401
import plg_dev  # noqa: F401
import plg_docs  # noqa: F401
import plg_learning  # noqa: F401
import plg_pdftools  # noqa: F401
import plg_social  # noqa: F401
from llm import LLMError
from registry import PLUGINS, Cancelled, Ctx, PluginError

log = logging.getLogger("inera.engine")
_executor = ThreadPoolExecutor(max_workers=config.WORKERS, thread_name_prefix="inera-job")
_log_lock = threading.Lock()
_pending = {}      # job_id -> original problem text (memory only, may contain secrets)
_secrets = {}      # job_id -> extracted secrets (memory only, never written to disk)
_stop = threading.Event()
ACTIVE = ("queued", "planning", "running")


CRITICAL_STEPS = {"translator"}


class QuotaError(Exception):
    pass


def _precheck(p, user) -> str:
    """Return a human message if a side-effect plugin cannot possibly run."""
    for need in p.needs:
        if need.startswith("vault:"):
            kind = need[6:]
            if not db.query_one("SELECT 1 AS ok FROM secrets WHERE user_id=? AND kind=?", (user["id"], kind)):
                label = {"instagram": "Instagram", "smtp": "E-mail (SMTP)", "messenger": "a messenger"}.get(kind, kind)
                return f"Not connected yet — open Connections and connect {label}, then run again. Your content is ready below."
        if need == "public_url":
            base = config.PUBLIC_BASE_URL
            if not base.startswith("https://") or any(h in base for h in ("localhost", "127.0.0.1", "0.0.0.0")):
                return ("Instagram downloads the image from your server, so the server must be on a public HTTPS "
                        "address (set PUBLIC_BASE_URL). Your post is ready below to post manually.")
    return ""


# ====================================================================== logging
def _append_log(job_id: str, msg: str, level: str = "info", step=None):
    with _log_lock:
        row = db.query_one("SELECT log_json FROM jobs WHERE id=?", (job_id,))
        if not row:
            return
        entries = db.jload(row["log_json"], [])
        entries.append({"t": round(time.time(), 2), "msg": str(msg)[:1200], "level": level, "step": step})
        db.execute("UPDATE jobs SET log_json=? WHERE id=?", (db.jdump(entries[-400:]), job_id))


def _set(job_id: str, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = [db.jdump(v) if k.endswith("_json") else v for k, v in fields.items()]
    db.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*vals, job_id))


# ====================================================================== create
def _user_files(user_id: str, ids: list) -> list:
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    rows = db.query(f"SELECT id,name,path,mime,size FROM files WHERE user_id=? AND id IN ({marks})", (user_id, *ids))
    by_id = {r["id"]: r for r in rows if Path(r["path"]).exists()}
    return [by_id[i] for i in ids if i in by_id]


def create_job(user: dict, problem: str, file_ids: list, source: str = "manual", automation: dict = None,
               enforce_cap: bool = False) -> str:
    problem = (problem or "").strip()
    if not problem:
        raise ValueError("Describe the problem first.")
    if len(problem) > 8000:
        raise ValueError("Problem statement is too long (max 8,000 characters).")
    since = time.time() - 86400
    today = db.query_one("SELECT COUNT(*) AS n FROM jobs WHERE user_id=? AND created_at>?", (user["id"], since))["n"]
    if today >= config.MAX_RUNS_PER_DAY:
        raise QuotaError(f"Daily limit of {config.MAX_RUNS_PER_DAY} runs reached. Try again tomorrow.")
    if source == "manual" or enforce_cap:
        active = db.query_one(f"SELECT COUNT(*) AS n FROM jobs WHERE user_id=? AND status IN ({','.join('?' * len(ACTIVE))})",
                              (user["id"], *ACTIVE))["n"]
        if active >= config.MAX_CONCURRENT_JOBS_PER_USER:
            raise QuotaError("You already have runs in progress. Wait for one to finish.")
    files = _user_files(user["id"], (file_ids or [])[:config.MAX_FILES_PER_RUN])
    clean, secrets = planner.split_secrets(problem)
    job_id = db.new_id("j_")
    db.execute("INSERT INTO jobs (id,user_id,problem,status,input_ids_json,source,automation_id,created_at) "
               "VALUES (?,?,?,?,?,?,?,?)",
               (job_id, user["id"], clean, "queued", db.jdump([f["id"] for f in files]), source,
                automation["id"] if automation else None, time.time()))
    _pending[job_id] = problem
    if secrets:
        _secrets[job_id] = secrets
    _executor.submit(_run_safely, job_id, automation)
    return job_id


def _run_safely(job_id, automation=None, resume=False):
    try:
        run_job(job_id, automation, resume)
    except Exception as exc:  # last-resort guard: never kill the worker thread
        log.error("job %s crashed: %s", job_id, traceback.format_exc())
        _append_log(job_id, f"Unexpected error: {type(exc).__name__}: {exc}", "error")
        _set(job_id, status="failed", error=str(exc)[:500], finished_at=time.time())
    finally:
        _pending.pop(job_id, None)
        row = db.query_one("SELECT status FROM jobs WHERE id=?", (job_id,))
        if not row or row["status"] != "awaiting_approval":
            _secrets.pop(job_id, None)


# ====================================================================== run
def run_job(job_id: str, automation: dict = None, resume: bool = False):
    job = db.query_one("SELECT * FROM jobs WHERE id=?", (job_id,))
    if not job:
        return
    user = db.get_user(job["user_id"])
    if not user:
        return
    if automation is None and job["automation_id"] and job["source"] == "schedule":
        automation = db.query_one("SELECT * FROM automations WHERE id=?", (job["automation_id"],))
    if resume and job["status"] != "running":
        return  # cancelled between approval and resume — nothing is sent
    inputs = _user_files(user["id"], db.jload(job["input_ids_json"], []))
    _set(job_id, status="planning" if not resume else "running", started_at=job["started_at"] or time.time())

    if resume:
        plan = db.jload(job["plan_json"], {})
    elif automation:
        plan = db.jload(automation["plan_json"], {})
        plan["schedule"] = None  # this IS the scheduled run
        plan.setdefault("summary", planner.summarize_plan(plan))
        plan["notes"] = []
        for s in plan["steps"]:
            s["status"] = "pending"
        _append_log(job_id, f"Scheduled run of “{automation['name']}”.")
    else:
        _append_log(job_id, "Understanding the problem and choosing plugins…")
        try:
            plan = planner.make_plan(_pending.get(job_id, job["problem"]), inputs, user)
        except LLMError as exc:
            _append_log(job_id, f"AI planner unavailable ({exc}); using rule planner.", "warn")
            plan = planner.make_plan(_pending.get(job_id, job["problem"]), inputs, {**user, "profile": {}})
        secrets = plan.pop("_secrets", {})
        if secrets:
            _secrets[job_id] = {**_secrets.get(job_id, {}), **secrets}
        plan.pop("clean_problem", None)
        for s in plan["steps"]:
            s["status"] = "pending"
        _append_log(job_id, plan["summary"])
        for note in plan.get("notes", []):
            _append_log(job_id, note, "warn")
    plan["steps"] = [s for s in plan.get("steps", []) if s.get("plugin") in PLUGINS]
    _set(job_id, plan_json=plan, status="running")

    state = db.jload(job["state_json"], {}) if resume else {}
    if automation and not resume:
        state["auto_state"] = db.jload(automation["state_json"], {})
    if not state.get("topic"):
        state["topic"] = plan.get("topic", "")
    ctx = Ctx(job_id, user, job["problem"], plan, state, inputs, lambda m, lvl, st: _append_log(job_id, m, lvl, st),
              automation=automation, preview=bool(plan.get("schedule")) and not automation)
    outputs = db.jload(job["outputs_json"], []) if resume else []
    auto_ok = bool(user["profile"].get("auto_approve"))
    approved = bool(automation and automation.get("approved")) or auto_ok
    steps = plan["steps"]
    total = max(1, len(steps))
    failed = False
    for i, step in enumerate(steps):
        if step.get("status") in ("done", "skipped", "scheduled"):
            continue
        p = PLUGINS[step["plugin"]]
        try:
            ctx.check_cancel()
        except Cancelled:
            _finish_cancel(job_id, plan, outputs, ctx)
            return
        if p.side_effect:
            problem_note = _precheck(p, user)
            if problem_note and not ctx.preview:
                failed = True
                step["status"], step["error"] = "failed", problem_note
                _append_log(job_id, f"{p.name}: {problem_note}", "error", p.id)
                continue
            if ctx.preview:
                step["status"] = "scheduled"
                _append_log(job_id, f"{p.name}: will run on schedule (preview only now).", "info", p.id)
                continue
            if failed:
                step["status"] = "skipped"
                step["error"] = "Skipped because an earlier step failed — nothing was sent."
                _append_log(job_id, f"{p.name}: skipped for safety because an earlier step failed.", "warn", p.id)
                continue
            if not (approved or step.get("approved")):
                step["status"] = "awaiting_approval"
                _save(job_id, plan, outputs + ctx.outputs, ctx.state, status="awaiting_approval",
                      progress=i / total)
                _append_log(job_id, f"Ready to run “{p.name}”. Review the outputs and approve to continue.", "warn", p.id)
                return
        step["status"] = "running"
        step["started"] = time.time()
        ctx.current_step = p.id
        _set(job_id, plan_json=plan, progress=round(i / total, 3))
        _append_log(job_id, f"▶ {p.name}", "step", p.id)
        params = dict(step.get("params") or {})
        if p.id in ("protect_pdf", "unlock_pdf", "qr_generator") and _secrets.get(job_id, {}).get("password"):
            params["password"] = _secrets[job_id]["password"]
        params = {k: v for k, v in params.items() if k in p.params}
        try:
            p.run(ctx, **params)
            step["status"] = "done"
        except Cancelled:
            step["status"] = "cancelled"
            _finish_cancel(job_id, plan, outputs, ctx)
            return
        except PluginError as exc:
            failed = True
            step["status"], step["error"] = "failed", str(exc)
            _append_log(job_id, f"{p.name}: {exc}", "error", p.id)
            if p.id in CRITICAL_STEPS:
                for later in steps[i + 1:]:
                    if later.get("status") == "pending":
                        later["status"], later["error"] = "skipped", f"Skipped because {p.name} failed."
                _append_log(job_id, f"Stopped the remaining steps because {p.name} failed.", "warn")
                step["seconds"] = round(time.time() - step["started"], 1)
                break
        except LLMError as exc:
            failed = True
            step["status"], step["error"] = "failed", f"AI engine error: {exc}"
            _append_log(job_id, f"{p.name}: AI engine error — {exc}", "error", p.id)
        except Exception as exc:
            failed = True
            log.error("plugin %s failed: %s", p.id, traceback.format_exc())
            step["status"], step["error"] = "failed", f"{type(exc).__name__}: {str(exc)[:300]}"
            _append_log(job_id, f"{p.name} failed: {type(exc).__name__}: {str(exc)[:300]}", "error", p.id)
        step["seconds"] = round(time.time() - step["started"], 1)
        ctx.current_step = None
        _set(job_id, plan_json=plan, outputs_json=outputs + ctx.outputs)
    statuses = [s["status"] for s in steps]
    if all(s in ("done", "scheduled") for s in statuses):
        status = "completed"
    elif any(s == "done" for s in statuses):
        status = "completed_with_errors"
    else:
        status = "failed"
    _save(job_id, plan, outputs + ctx.outputs, ctx.state, status=status, progress=1.0, finished=True)
    if automation:
        db.execute("UPDATE automations SET state_json=?, last_status=?, last_job_id=? WHERE id=?",
                   (db.jdump(ctx.state.get("auto_state", {})), status, job_id, automation["id"]))
    elif ctx.state.get("automation_id"):
        db.execute("UPDATE automations SET state_json=? WHERE id=?",
                   (db.jdump(ctx.state.get("auto_state", {})), ctx.state["automation_id"]))
    _append_log(job_id, {"completed": "All done ✓", "completed_with_errors": "Finished with some errors.",
                         "failed": "Run failed."}[status], "done" if status == "completed" else "warn")
    _cleanup_temp(ctx.job_dir)


def _save(job_id, plan, outputs, state, status, progress, finished=False):
    slim = {k: v for k, v in state.items() if k not in ("input_text", "research_raw")}
    if len(slim.get("research_text", "")) > 120000:
        slim["research_text"] = slim["research_text"][:120000]
    fields = dict(plan_json=plan, outputs_json=outputs, state_json=slim, status=status, progress=progress)
    if finished:
        fields["finished_at"] = time.time()
    _set(job_id, **fields)


def _finish_cancel(job_id, plan, outputs, ctx):
    for s in plan["steps"]:
        if s.get("status") in ("pending", "running"):
            s["status"] = "cancelled"
    _save(job_id, plan, outputs + ctx.outputs, ctx.state, status="cancelled", progress=1.0, finished=True)
    _append_log(job_id, "Cancelled.", "warn")
    _cleanup_temp(ctx.job_dir)


def _cleanup_temp(job_dir: Path):
    try:
        for p in job_dir.glob("_*"):
            if p.is_file():
                p.unlink(missing_ok=True)
    except OSError:
        pass


def approve_job(job_id: str, user_id: str) -> bool:
    row = db.query_one("SELECT plan_json FROM jobs WHERE id=? AND user_id=? AND status='awaiting_approval'",
                       (job_id, user_id))
    if not row:
        return False
    plan = db.jload(row["plan_json"], {})
    for step in plan.get("steps", []):
        if step.get("status") == "awaiting_approval":
            step["status"], step["approved"] = "pending", True  # approve exactly this step
            break
    n = db.execute("UPDATE jobs SET status='running', plan_json=? WHERE id=? AND user_id=? "
                   "AND status='awaiting_approval'", (db.jdump(plan), job_id, user_id))
    if n:
        _append_log(job_id, "Approved by you — continuing.", "info")
        _executor.submit(_run_safely, job_id, None, True)
    return bool(n)


def cancel_job(job_id: str, user_id: str) -> bool:
    row = db.query_one("SELECT status FROM jobs WHERE id=? AND user_id=?", (job_id, user_id))
    if not row:
        return False
    if row["status"] == "awaiting_approval":
        n = db.execute("UPDATE jobs SET status='cancelled', finished_at=? WHERE id=? AND status='awaiting_approval'",
                       (time.time(), job_id))
        if n:
            _secrets.pop(job_id, None)
            _append_log(job_id, "Cancelled — nothing was sent.", "warn")
            return True
        row = db.query_one("SELECT status FROM jobs WHERE id=?", (job_id,))
    return db.execute("UPDATE jobs SET cancel_requested=1 WHERE id=? AND user_id=? AND status IN (?,?,?)",
                      (job_id, user_id, *ACTIVE)) > 0


def run_automation_now(aid: str, user: dict) -> str:
    a = db.query_one("SELECT * FROM automations WHERE id=? AND user_id=?", (aid, user["id"]))
    if not a:
        raise ValueError("Automation not found.")
    if not a["approved"]:
        raise ValueError("Approve the automation first.")
    job_id = create_job(user, a["problem"], db.jload(a["input_ids_json"], []), source="schedule", automation=a,
                        enforce_cap=True)
    db.execute("UPDATE automations SET last_job_id=?, last_run_at=?, run_count=run_count+1 WHERE id=?",
               (job_id, time.time(), aid))
    return job_id


# ====================================================================== scheduler
def _scheduler_tick():
    now = time.time()
    due = db.query("SELECT * FROM automations WHERE enabled=1 AND approved=1 AND next_run_at IS NOT NULL "
                   "AND next_run_at<=? ORDER BY next_run_at LIMIT 25", (now,))
    for a in due:
        schedule = db.jload(a["schedule_json"], {})
        nxt = automations.next_run(schedule, a["timezone"], dt.datetime.now(dt.timezone.utc))
        claimed = db.execute("UPDATE automations SET next_run_at=?, last_run_at=?, run_count=run_count+1, enabled=? "
                             "WHERE id=? AND next_run_at=?",
                             (nxt.timestamp() if nxt else None, now, 1 if nxt else 0, a["id"], a["next_run_at"]))
        if not claimed:
            continue  # another process took it
        user = db.get_user(a["user_id"])
        if not user:
            continue
        try:
            job_id = create_job(user, a["problem"], db.jload(a["input_ids_json"], []), source="schedule", automation=a)
            db.execute("UPDATE automations SET last_job_id=?, last_status='running' WHERE id=?", (job_id, a["id"]))
        except (QuotaError, ValueError) as exc:
            db.execute("UPDATE automations SET last_status=? WHERE id=?", (f"skipped: {exc}"[:200], a["id"]))


def _housekeeping():
    now = time.time()
    db.execute("DELETE FROM sessions WHERE expires_at<?", (now,))
    db.execute("UPDATE files SET public_token=NULL, public_expires=NULL WHERE public_expires IS NOT NULL AND public_expires<?",
               (now,))
    if config.RETENTION_DAYS > 0:
        cutoff = now - config.RETENTION_DAYS * 86400
        keep = set()
        for a in db.query("SELECT input_ids_json FROM automations"):
            keep.update(db.jload(a["input_ids_json"], []))
        old = db.query("SELECT id, path FROM files WHERE created_at<?", (cutoff,))
        for f in old:
            if f["id"] in keep:
                continue
            try:
                Path(f["path"]).unlink(missing_ok=True)
            except OSError:
                pass
            db.execute("DELETE FROM files WHERE id=?", (f["id"],))
        db.execute("DELETE FROM jobs WHERE created_at<? AND status NOT IN (?,?,?,?)", (cutoff, *ACTIVE, "awaiting_approval"))
        for d in config.FILES_DIR.glob("*/*"):
            try:
                if d.is_dir() and not any(d.iterdir()):
                    d.rmdir()
            except OSError:
                pass
    for p in config.TMP_DIR.glob("*"):
        try:
            if p.stat().st_mtime < now - 86400:
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
        except OSError:
            pass


def _loop():
    last_house = 0.0
    while not _stop.is_set():
        try:
            _scheduler_tick()
            if time.time() - last_house > 3600:
                _housekeeping()
                last_house = time.time()
        except Exception:
            log.error("scheduler error: %s", traceback.format_exc())
        _stop.wait(15)


def start():
    db.init()
    db.execute("UPDATE jobs SET status='failed', error='Interrupted by a server restart — please run it again.', "
               f"finished_at=? WHERE status IN ({','.join('?' * len(ACTIVE))})", (time.time(), *ACTIVE))
    if config.SERVERLESS:
        log.warning("Serverless host detected: background scheduler disabled (functions sleep between requests).")
        return
    t = threading.Thread(target=_loop, name="inera-scheduler", daemon=True)
    t.start()


def stop():
    _stop.set()
    _executor.shutdown(wait=False, cancel_futures=True)
