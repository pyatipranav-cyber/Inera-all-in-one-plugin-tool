"""Developer plugins: generate complete starter projects as a ZIP.
Generated code is never executed on the server."""
import html
import json
import re
import zipfile
from pathlib import PurePosixPath

import textkit as tk
from llm import LLMError
from registry import PluginError, plugin


def _clean_path(p: str):
    p = str(p or "").replace("\\", "/").strip().lstrip("/")
    parts = [x for x in PurePosixPath(p).parts if x not in ("", ".", "..")]
    if not parts or len(parts) > 6:
        return None
    clean = "/".join(re.sub(r"[^\w.\-]", "_", x)[:60] for x in parts)
    return clean if not clean.startswith(".git/") else None


def _templates(name: str, problem: str) -> tuple:
    low = problem.lower()
    title = html.escape(name)
    if "chrome extension" in low or "browser extension" in low:
        return "chrome-extension", {
            "manifest.json": json.dumps({"manifest_version": 3, "name": name, "version": "1.0.0",
                                         "description": problem[:120], "action": {"default_popup": "popup.html"},
                                         "permissions": ["storage"]}, indent=2),
            "popup.html": f"<!doctype html><html><head><meta charset='utf-8'><link rel='stylesheet' href='popup.css'>"
                          f"</head><body><h1>{title}</h1><button id='go'>Run</button><p id='out'></p>"
                          "<script src='popup.js'></script></body></html>",
            "popup.css": "body{font-family:system-ui;width:280px;padding:16px}button{padding:8px 14px}",
            "popup.js": "document.getElementById('go').addEventListener('click', async () => {\n"
                        "  const { count = 0 } = await chrome.storage.local.get('count');\n"
                        "  await chrome.storage.local.set({ count: count + 1 });\n"
                        "  document.getElementById('out').textContent = `Clicked ${count + 1} times`;\n});\n",
            "README.md": f"# {name}\n\nLoad unpacked: chrome://extensions → Developer mode → Load unpacked → select this folder.\n"}
    if "react" in low:
        return "react-app", {
            "package.json": json.dumps({"name": tk.slugify(name), "private": True, "version": "1.0.0", "type": "module",
                                        "scripts": {"dev": "vite", "build": "vite build", "preview": "vite preview"},
                                        "dependencies": {"react": "^18.3.1", "react-dom": "^18.3.1"},
                                        "devDependencies": {"vite": "^5.4.0", "@vitejs/plugin-react": "^4.3.1"}},
                                       indent=2),
            "vite.config.js": "import { defineConfig } from 'vite'\nimport react from '@vitejs/plugin-react'\n"
                              "export default defineConfig({ plugins: [react()] })\n",
            "index.html": f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' "
                          f"content='width=device-width,initial-scale=1'><title>{title}</title></head><body>"
                          "<div id='root'></div><script type='module' src='/src/main.jsx'></script></body></html>",
            "src/main.jsx": "import React from 'react'\nimport { createRoot } from 'react-dom/client'\nimport App from './App.jsx'\n"
                            "import './styles.css'\ncreateRoot(document.getElementById('root')).render(<App />)\n",
            "src/App.jsx": "import { useState } from 'react'\nexport default function App() {\n  const [items, setItems] = useState([])\n"
                           "  const [text, setText] = useState('')\n  return (<main><h1>" + title + "</h1>\n"
                           "    <form onSubmit={e => { e.preventDefault(); if (text) { setItems([...items, text]); setText('') } }}>\n"
                           "      <input value={text} onChange={e => setText(e.target.value)} placeholder='Add item' />\n"
                           "      <button>Add</button></form>\n    <ul>{items.map((t, i) => <li key={i}>{t}</li>)}</ul></main>)\n}\n",
            "src/styles.css": "body{font-family:system-ui;max-width:640px;margin:40px auto;padding:0 16px}",
            "README.md": f"# {name}\n\n```\nnpm install\nnpm run dev\n```\n"}
    if any(w in low for w in ("node", "express", "javascript api")):
        return "node-api", {
            "package.json": json.dumps({"name": tk.slugify(name), "version": "1.0.0", "main": "server.js",
                                        "scripts": {"start": "node server.js"}, "dependencies": {"express": "^4.19.2"}},
                                       indent=2),
            "server.js": "const express = require('express');\nconst app = express();\napp.use(express.json());\n"
                         "const items = [];\napp.get('/api/items', (req, res) => res.json(items));\n"
                         "app.post('/api/items', (req, res) => {\n  const { name } = req.body || {};\n"
                         "  if (!name || typeof name !== 'string') return res.status(400).json({ error: 'name required' });\n"
                         "  const item = { id: items.length + 1, name: name.slice(0, 200) };\n  items.push(item);\n"
                         "  res.status(201).json(item);\n});\napp.listen(process.env.PORT || 3000, () => console.log('Listening'));\n",
            "README.md": f"# {name}\n\n```\nnpm install\nnpm start\n```\n"}
    if any(w in low for w in ("api", "backend", "rest", "fastapi", "flask", "server")):
        return "python-api", {
            "main.py": "from fastapi import FastAPI, HTTPException\nfrom pydantic import BaseModel, Field\n\n"
                       f"app = FastAPI(title={json.dumps(name)})\n\n\nclass Item(BaseModel):\n"
                       "    name: str = Field(min_length=1, max_length=200)\n    note: str = ''\n\n\nDB: dict[int, Item] = {}\n\n\n"
                       "@app.get('/items')\ndef list_items():\n    return [{'id': k, **v.model_dump()} for k, v in DB.items()]\n\n\n"
                       "@app.post('/items', status_code=201)\ndef create_item(item: Item):\n    new_id = max(DB, default=0) + 1\n"
                       "    DB[new_id] = item\n    return {'id': new_id, **item.model_dump()}\n\n\n"
                       "@app.delete('/items/{item_id}', status_code=204)\ndef delete_item(item_id: int):\n"
                       "    if DB.pop(item_id, None) is None:\n        raise HTTPException(404, 'Not found')\n",
            "requirements.txt": "fastapi>=0.110\nuvicorn>=0.29\n",
            "README.md": f"# {name}\n\n```\npip install -r requirements.txt\nuvicorn main:app --reload\n```\nDocs at /docs\n"}
    if any(w in low for w in ("script", "automation", "python", "cli", "bot")):
        return "python-script", {
            "main.py": '"""' + name + '"""\nimport argparse\nimport csv\nimport sys\n\n\ndef run(path: str) -> int:\n'
                       "    with open(path, newline='', encoding='utf-8') as fh:\n        rows = list(csv.DictReader(fh))\n"
                       "    print(f'Loaded {len(rows)} rows')\n    return 0\n\n\nif __name__ == '__main__':\n"
                       "    ap = argparse.ArgumentParser(description=" + json.dumps(problem[:100]) + ")\n"
                       "    ap.add_argument('input', help='CSV file to process')\n    sys.exit(run(ap.parse_args().input))\n",
            "README.md": f"# {name}\n\n```\npython main.py data.csv\n```\n"}
    return "website", {
        "index.html": f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
                      f"content='width=device-width,initial-scale=1'><title>{title}</title><link rel='stylesheet' "
                      f"href='styles.css'></head><body><header><h1>{title}</h1></header><main><section class='card'>"
                      f"<h2>Welcome</h2><p>{html.escape(problem[:240])}</p><button id='cta'>Get started</button></section>"
                      "</main><script src='script.js'></script></body></html>",
        "styles.css": ":root{--accent:#C9A55C}body{margin:0;font-family:system-ui;background:#faf8f4;color:#1a1814}"
                      "header{background:#121110;color:#f5efe2;padding:48px 20px}main{max-width:900px;margin:auto;padding:24px}"
                      ".card{background:#fff;border-radius:14px;padding:24px;box-shadow:0 2px 10px rgba(0,0,0,.05)}"
                      "button{background:var(--accent);border:0;padding:12px 22px;border-radius:999px;font-weight:600}",
        "script.js": "document.getElementById('cta').addEventListener('click', () => alert('Hello!'));\n",
        "README.md": f"# {name}\n\nOpen index.html in a browser, or upload the folder to any static host.\n"}


@plugin("code_project_builder", "Code & Project Builder", "dev", "render",
        "Generates complete starter projects — websites, React apps, Python/Node APIs, scripts, browser extensions — "
        "as a ready-to-run ZIP with README.",
        icon="code", keywords=["code", "app", "project", "program", "script", "api", "react", "python", "javascript",
                               "build me", "extension", "software", "github"],
        example="Build a Python FastAPI app to manage customer bookings")
def code_project_builder(ctx):
    name = tk.title_case(ctx.topic() or "My Project")[:60]
    files, kind = {}, "custom"
    if ctx.llm.available():
        ctx.log("Designing the project with the AI engine…")
        try:
            data = ctx.llm.complete_json(
                f"Build a complete, working starter project for: {ctx.problem}\n"
                'Return JSON {"name": str, "files": [{"path": str, "content": str}], "run": str}. Include a README.md '
                "with setup and run steps, input validation, no hard-coded secrets (use environment variables), "
                "max 15 files, keep each file under 400 lines.", max_tokens=12000, temperature=0.2)
            for f in (data.get("files") if isinstance(data, dict) else []) or []:
                path = _clean_path(f.get("path") if isinstance(f, dict) else None)
                content = f.get("content") if isinstance(f, dict) else None
                if path and isinstance(content, str) and len(content) < 200000:
                    files[path] = content
            if isinstance(data, dict) and data.get("name"):
                name = str(data["name"])[:60]
        except LLMError as exc:
            ctx.log(f"AI engine failed ({exc}); using a starter template.", "warn")
    if not files:
        kind, files = _templates(name, ctx.problem)
        ctx.log(f"Generated the “{kind}” starter template. Connect an AI engine for fully custom code.", "warn")
    files = dict(list(files.items())[:40])
    zpath = ctx.out_path(tk.slugify(name) + ".zip")
    root = tk.slugify(name)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for path, content in files.items():
            z.writestr(f"{root}/{path}", content)
    ctx.add_output(zpath, f"Project “{name}” · {len(files)} files")
    listing = "\n".join(f"- `{p}` ({len(c.splitlines())} lines)" for p, c in files.items())
    readme = files.get("README.md", "")
    ctx.add_text_output("project-overview.md", f"# {name}\n\n## Files\n\n{listing}\n\n{readme}", "Project overview",
                        "markdown")
    ctx.log("Review generated code before deploying it — never run code you don't understand.")
