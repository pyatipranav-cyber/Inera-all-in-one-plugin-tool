"""Recurring automations: schedule maths and persistence."""
import calendar
import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import config
import db

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def tzinfo(name: str):
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _times(schedule) -> list:
    out = []
    for t in schedule.get("times") or ["09:00"]:
        try:
            h, m = (int(x) for x in str(t).split(":")[:2])
            if 0 <= h < 24 and 0 <= m < 60:
                out.append((h, m))
        except ValueError:
            continue
    return sorted(set(out)) or [(9, 0)]


def next_run(schedule: dict, tz_name: str, after: dt.datetime = None):
    """Return the next run as an aware UTC datetime strictly after `after`."""
    tz = tzinfo(tz_name)
    after = after or dt.datetime.now(dt.timezone.utc)
    kind = schedule.get("type")
    if kind == "interval":
        minutes = max(config.MIN_INTERVAL_MINUTES, int(schedule.get("minutes") or 60))
        return after + dt.timedelta(minutes=minutes)
    if kind == "once":
        try:
            at = dt.datetime.fromisoformat(schedule["at"])
        except (KeyError, ValueError):
            return None
        at = at.replace(tzinfo=tz) if at.tzinfo is None else at
        at = at.astimezone(dt.timezone.utc)
        return at if at > after else None
    local_after = after.astimezone(tz)
    times = _times(schedule)
    for offset in range(0, 400):
        day = (local_after + dt.timedelta(days=offset)).date()
        if kind == "weekly" and day.weekday() not in (schedule.get("days") or [0]):
            continue
        if kind == "monthly":
            want = int(schedule.get("day") or 1)
            last = calendar.monthrange(day.year, day.month)[1]
            if day.day != min(want, last):
                continue
        for h, m in times:
            cand = dt.datetime(day.year, day.month, day.day, h, m, tzinfo=tz)
            if cand > local_after:
                return cand.astimezone(dt.timezone.utc)
    return None


def describe(schedule: dict) -> str:
    kind = schedule.get("type")
    times = ", ".join(f"{h:02d}:{m:02d}" for h, m in _times(schedule))
    if kind == "daily":
        return f"Every day at {times}"
    if kind == "weekly":
        days = schedule.get("days") or [0]
        if sorted(days) == [0, 1, 2, 3, 4]:
            label = "Every weekday"
        elif sorted(days) == [5, 6]:
            label = "Every weekend day"
        else:
            label = "Every " + ", ".join(DAY_NAMES[d] for d in sorted(days))
        return f"{label} at {times}"
    if kind == "monthly":
        d = int(schedule.get("day") or 1)
        suffix = "th" if 11 <= d <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th")
        return f"On the {d}{suffix} of every month at {times}"
    if kind == "interval":
        mins = int(schedule.get("minutes") or 60)
        if mins % 1440 == 0:
            return f"Every {mins // 1440} day(s)"
        if mins % 60 == 0:
            return f"Every {mins // 60} hour(s)" if mins != 60 else "Every hour"
        return f"Every {mins} minutes"
    if kind == "once":
        return f"Once at {schedule.get('at', '').replace('T', ' ')[:16]}"
    return "Custom schedule"


def create(user: dict, problem: str, plan: dict, schedule: dict, input_ids: list, approved: bool) -> dict:
    count = db.query_one("SELECT COUNT(*) AS n FROM automations WHERE user_id=?", (user["id"],))["n"]
    if count >= config.MAX_AUTOMATIONS_PER_USER:
        raise ValueError(f"Automation limit reached ({config.MAX_AUTOMATIONS_PER_USER}). Delete one first.")
    tz = (user.get("profile") or {}).get("timezone") or "UTC"
    nxt = next_run(schedule, tz)
    aid = db.new_id("a_")
    steps = [s for s in plan.get("steps", []) if s.get("plugin") != "automation_scheduler"]
    stored_plan = {k: v for k, v in plan.items() if k not in ("steps", "_secrets")}
    stored_plan["steps"] = [{"plugin": s["plugin"], "params": s.get("params", {})} for s in steps]
    name = (plan.get("title") or problem)[:80]
    db.execute("INSERT INTO automations (id,user_id,name,problem,plan_json,schedule_json,timezone,input_ids_json,"
               "state_json,next_run_at,enabled,approved,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (aid, user["id"], name, problem, db.jdump(stored_plan), db.jdump(schedule), tz, db.jdump(input_ids),
                "{}", nxt.timestamp() if nxt else None, 1 if nxt else 0, 1 if approved else 0, db.now()))
    return get(aid, user["id"])


def get(aid: str, user_id: str):
    a = db.query_one("SELECT * FROM automations WHERE id=? AND user_id=?", (aid, user_id))
    return public(a) if a else None


def public(a: dict) -> dict:
    schedule = db.jload(a["schedule_json"], {})
    plan = db.jload(a["plan_json"], {})
    return {"id": a["id"], "name": a["name"], "problem": a["problem"], "schedule": schedule,
            "schedule_text": describe(schedule), "timezone": a["timezone"],
            "plugins": [s["plugin"] for s in plan.get("steps", [])], "next_run_at": a["next_run_at"],
            "last_run_at": a["last_run_at"], "last_status": a["last_status"], "last_job_id": a["last_job_id"],
            "run_count": a["run_count"], "enabled": bool(a["enabled"]), "approved": bool(a["approved"]),
            "input_count": len(db.jload(a["input_ids_json"], [])), "created_at": a["created_at"]}
