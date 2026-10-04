"""Plugin registry and the execution context handed to every plugin."""
import mimetypes
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import config
import db
import security
import textkit
from llm import engine as llm_engine

PLUGINS: dict = {}

CATEGORIES = [
    ("research", "Research & Knowledge"),
    ("writing", "Writing & Language"),
    ("learning", "Learning Studio"),
    ("documents", "Document Studio"),
    ("pdf", "PDF & File Tools"),
    ("media", "Image & Media"),
    ("data", "Data & Business"),
    ("social", "Social & Marketing"),
    ("delivery", "Delivery & Automation"),
    ("dev", "Developer"),
]

# Order in which stages run when the planner composes a pipeline.
STAGES = ["input", "research", "content", "transform", "render", "learning", "media", "deliver", "schedule"]


class PluginError(Exception):
    """A user-facing failure with a clear explanation."""


@dataclass
class Plugin:
    id: str
    name: str
    category: str
    stage: str
    description: str
    icon: str
    run: Callable
    keywords: list = field(default_factory=list)
    params: dict = field(default_factory=dict)
    needs: list = field(default_factory=list)       # e.g. ["files:pdf"], ["vault:smtp"]
    side_effect: bool = False                      # acts outside the platform (sends/posts)
    ai_enhanced: bool = True
    example: str = ""

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "category": self.category, "stage": self.stage,
                "description": self.description, "icon": self.icon, "params": self.params,
                "needs": self.needs, "side_effect": self.side_effect, "ai_enhanced": self.ai_enhanced,
                "example": self.example}


def plugin(id, name, category, stage, description, icon="spark", keywords=None, params=None,
           needs=None, side_effect=False, ai_enhanced=True, example=""):
    def deco(fn):
        PLUGINS[id] = Plugin(id=id, name=name, category=category, stage=stage, description=description,
                             icon=icon, run=fn, keywords=keywords or [], params=params or {},
                             needs=needs or [], side_effect=side_effect, ai_enhanced=ai_enhanced,
                             example=example)
        return fn
    return deco


KIND_BY_EXT = {
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image", ".gif": "image",
    ".mp4": "video", ".webm": "video", ".mp3": "audio", ".wav": "audio", ".m4a": "audio",
    ".pdf": "pdf", ".docx": "word", ".pptx": "slides", ".xlsx": "sheet", ".csv": "sheet",
    ".zip": "zip", ".md": "markdown", ".txt": "text", ".html": "html", ".json": "data", ".svg": "image",
}


def guess_mime(name: str) -> str:
    ext = Path(name).suffix.lower()
    extra = {".md": "text/markdown", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
             ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             ".webp": "image/webp", ".mp4": "video/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav"}
    return extra.get(ext) or mimetypes.guess_type(name)[0] or "application/octet-stream"


class Cancelled(Exception):
    pass


class Ctx:
    def __init__(self, job_id: str, user: dict, problem: str, plan: dict, state: dict,
                 inputs: list, log_fn: Callable, automation: dict = None, preview: bool = False):
        self.job_id = job_id
        self.user = user
        self.problem = problem
        self.plan = plan
        self.state = state
        self.inputs = inputs
        self.outputs = []
        self._log = log_fn
        self.automation = automation
        self.preview = preview
        self.llm = llm_engine
        self.current_step = None
        self.job_dir = config.FILES_DIR / user["id"] / job_id
        self.job_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ helpers
    @property
    def profile(self) -> dict:
        return self.user.get("profile") or {}

    @property
    def business(self) -> str:
        return (self.profile.get("business_name") or self.user.get("name") or "My Business").strip()

    def log(self, message: str, level: str = "info"):
        self._log(message, level, self.current_step)

    def check_cancel(self):
        row = db.query_one("SELECT cancel_requested FROM jobs WHERE id=?", (self.job_id,))
        if row and row["cancel_requested"]:
            raise Cancelled()

    def out_path(self, filename: str) -> Path:
        name = security.safe_filename(filename, "output")
        path = self.job_dir / name
        stem, suffix, n = path.stem, path.suffix, 2
        while path.exists():
            path = self.job_dir / f"{stem}-{n}{suffix}"
            n += 1
        return path

    def add_output(self, path, label: str = "", kind: str = None, register: bool = True) -> dict:
        path = Path(path)
        kind = kind or KIND_BY_EXT.get(path.suffix.lower(), "file")
        rec = {"name": path.name, "label": label or path.name, "kind": kind,
               "size": path.stat().st_size, "mime": guess_mime(path.name), "step": self.current_step}
        if register:
            fid = db.new_id("f_")
            db.execute("INSERT INTO files (id,user_id,name,path,mime,size,origin,kind,label,job_id,created_at) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (fid, self.user["id"], path.name, str(path), rec["mime"], rec["size"], "output",
                        kind, rec["label"], self.job_id, time.time()))
            rec["file_id"] = fid
        self.outputs.append(rec)
        self.state.setdefault("produced", []).append(
            {"file_id": rec.get("file_id"), "path": str(path), "name": path.name, "kind": kind})
        return rec

    def add_text_output(self, filename: str, text: str, label: str = "", kind: str = None) -> dict:
        path = self.out_path(filename)
        path.write_text(text, encoding="utf-8")
        return self.add_output(path, label, kind)

    def input_files(self, exts=None) -> list:
        if exts is None:
            return list(self.inputs)
        exts = {e.lower() for e in exts}
        return [f for f in self.inputs if Path(f["name"]).suffix.lower() in exts]

    def produced(self, exts=None) -> list:
        items = self.state.get("produced", [])
        if exts is None:
            return list(items)
        exts = {e.lower() for e in exts}
        return [p for p in items if Path(p["name"]).suffix.lower() in exts]

    def input_text(self) -> str:
        if "input_text" not in self.state:
            parts = []
            lang = self.state.get("ocr_lang") or config.OCR_LANGS
            for f in self.inputs:
                ext = Path(f["name"]).suffix.lower()
                if ext in textkit.IMAGE_EXT and len(self.inputs) > 1 and not self.state.get("ocr_images"):
                    continue  # image libraries (e.g. post photos) are not text sources
                t = textkit.file_to_text(f["path"], lang=lang)
                if t.strip():
                    parts.append(f"## {f['name']}\n\n{t.strip()}")
            self.state["input_text"] = "\n\n".join(parts)[:400000]
        return self.state["input_text"]

    def source_text(self) -> str:
        """Best available knowledge text: uploads, then research, then current doc."""
        txt = self.input_text()
        research = self.state.get("research_text", "")
        if research:
            txt = (txt + "\n\n" + research).strip()
        if not txt and self.state.get("doc"):
            txt = textkit.doc_plain_text(self.state["doc"])
        return txt

    def secret(self, kind: str) -> dict:
        row = db.query_one("SELECT data_enc FROM secrets WHERE user_id=? AND kind=?", (self.user["id"], kind))
        return security.decrypt_json(row["data_enc"]) if row else {}

    def topic(self) -> str:
        return (self.state.get("topic") or self.plan.get("topic") or "").strip()

    def copy_in(self, src, filename=None) -> Path:
        dst = self.out_path(filename or Path(src).name)
        shutil.copyfile(src, dst)
        return dst


def catalog() -> list:
    order = {c: i for i, (c, _) in enumerate(CATEGORIES)}
    return sorted((p.public() for p in PLUGINS.values()), key=lambda p: (order.get(p["category"], 99), p["name"]))
