# InEra All-in-One Plugins

Describe a problem in plain words. InEra picks the right built-in plugins, chains them, runs them in the
background and hands you finished files — or turns the job into an automation that repeats on schedule.

> “Every day at 8 am, design and post an automobile tip with an image and caption on my Instagram”
> → Social Post Designer → Instagram Publisher → Automation Scheduler (daily 08:00, your time zone)

Everything — planning, writing, documents, PDF tools, media, scheduling — runs **inside this one app on your
server**. There is no Zapier-style middleman and no per-plugin account linking. The only outside calls are the
ones that are physically unavoidable (see *Reality check*).

---

## 1. Quick start

**Docker (recommended for servers)**
```bash
cp .env.example .env          # edit PUBLIC_BASE_URL, SECRET_KEY, AI engine…
docker compose up -d --build
# open http://localhost:8000 — the first account you create becomes admin
```

**Linux / macOS**: `./run.sh`  **Windows**: double-click `run.bat`  (Python 3.10+)

Optional system tools that unlock more plugins (Docker image already includes them):

| Tool | Unlocks | Install |
|---|---|---|
| ffmpeg | video overviews, MP3 podcasts | bundled via `imageio-ffmpeg`; or `apt install ffmpeg` |
| espeak-ng | voice for podcasts/videos (Windows & macOS use built-in voices) | `apt install espeak-ng` |
| Piper (optional) | natural-sounding voices | set `PIPER_MODEL` |
| Tesseract | OCR, scanned PDFs | `apt install tesseract-ocr tesseract-ocr-hin tesseract-ocr-kan` |
| LibreOffice | pixel-faithful Word/PPT/Excel → PDF | `apt install libreoffice-writer-nogui …` |

Check your install any time: `python selftest.py` (add `--full` to include video).

## 2. How it works

1. **Onboarding** — sign-up asks for your business details (name, industry, city, voice, handle, time zone).
   Every plugin uses them: posts carry your brand, invoices your GSTIN/UPI, websites your copy.
2. **Solve** — type the problem, attach files if needed, press Enter.
3. **Planner** — deterministic intent rules map the request to a pipeline (research → content → render →
   learning → media → delivery → schedule). If the rules can’t recognise a request and an AI engine is set,
   the AI proposes a plan, which is validated against the plugin catalogue.
4. **Engine** — runs the steps in background threads, streams progress (the “colonnade” of pillars), chains
   outputs (e.g. merge → page numbers → watermark → protect), and stores results in your Library.
5. **Approval gate** — any step that acts outside InEra (Instagram, e-mail, messengers) waits for your
   one-time approval unless you switch on *Approve automatically* in Profile. If an earlier step failed,
   outgoing steps are skipped so nothing half-finished is ever sent.
6. **Automations** — add a time (“every Monday at 6 pm”, “daily at 8”, “every 2 hours”, “on the 1st of every
   month”, “tomorrow at 9 am”) and the plan is saved as an automation. Library photos attached to it rotate,
   one per run, and post ideas never repeat back-to-back.

## 3. The 44 built-in plugins

| Area | Plugins |
|---|---|
| Research & knowledge | Web Research (Wikipedia + links you paste), Ask InEra |
| Writing | Content Writer (emails, blogs, captions, letters, proposals, scripts, resumes, policies…), Summarizer, Translator*, Rewrite & Proofread |
| Learning studio (NotebookLM-style) | Notebook Builder, Quiz & MCQ (interactive + PDF), Flashcards (interactive + Anki CSV + PDF), Mind Map, Audio Overview (two-host podcast), Video Overview (narrated MP4 + subtitles) |
| Document studio | PDF Creator, Word Document, Slide Deck (PPTX), Excel Builder (budget, expenses, inventory, sales, attendance, tasks, CRM — with formulas), Website Builder |
| PDF & file tools (iLovePDF-style) | PDF→Word, Office→PDF, Merge, Split, Rotate, Compress, Watermark, Page Numbers, Protect (AES-256), Unlock, PDF→Images, Images→PDF, OCR + searchable PDF, Extract Text, ZIP |
| Image & media | Image Converter & Resizer (social presets, metadata stripping), QR Code Generator |
| Data & business | Data Analyst (CSV/Excel → insights, charts, PDF report, workbook), Chart Maker, Invoice Generator (GST, amount in words) |
| Social & marketing | Social Post Designer (designed 4:5 JPEG or your own photo + caption + hashtags), Content Calendar (7–90 days, Excel) |
| Delivery & automation | Instagram Publisher, E-mail Sender (SMTP), Telegram / Discord / Slack / Webhook, Automation Scheduler |
| Developer | Code & Project Builder (websites, React, FastAPI, Node, scripts, browser extensions → ZIP) |

\* needs an AI engine. Everything else works fully offline; writing plugins become much better with one.

## 4. AI engine (optional, strongly recommended)

Without an engine InEra uses its built-in extractive engine: it summarises, structures and quizzes from real
sources (your files or Wikipedia) and uses curated template banks for posts and e-mails. That is useful, but
it is not creative writing. Pick one engine in `.env`:

* **Ollama — free and fully self-hosted.** `ollama pull llama3.1`, set `OLLAMA_URL`. Nothing leaves your server.
* **OpenAI-compatible** — `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` (works with Groq, Together, LM Studio, vLLM…).
* **Anthropic** — `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`.

## 5. Going live for the public

1. Put it behind HTTPS (Caddy, Nginx or Cloudflare). Example Caddyfile:
   ```
   plugins.yourdomain.com {
       reverse_proxy 127.0.0.1:8000
   }
   ```
2. In `.env`: `PUBLIC_BASE_URL=https://plugins.yourdomain.com`, `TRUST_PROXY=true`,
   `FORWARDED_ALLOW_IPS=<your proxy's IP>` (127.0.0.1 when Caddy/Nginx run on the same machine), a long `SECRET_KEY`.
3. Run **one** app process (the scheduler and job queue live inside it). Scale with `WORKERS` and a bigger
   machine, not with multiple uvicorn workers.
4. Back up the data folder (`/data` in Docker): it holds the database, files and — if you didn’t set
   `SECRET_KEY` — the key that decrypts saved connections.
5. Tune the public limits: `MAX_RUNS_PER_DAY`, `MAX_UPLOAD_MB`, `RETENTION_DAYS`, `ALLOW_REGISTRATION`.

### Instagram setup (per user, in *Connections*)
Instagram allows automated posting **only** through its official API: the account must be Business or
Creator, the user creates a Meta app with “Instagram API with Instagram Login”, generates a token with
`instagram_business_basic` + `instagram_business_content_publish`, and pastes the account ID + token.
Images must be JPEG and reachable over public HTTPS — InEra serves each one through a random link that
expires after an hour. Meta limits accounts to 100 API posts per 24 h. Tokens expire (~60 days).

## 6. Security model

* Passwords: scrypt; sessions: random tokens stored hashed, HttpOnly + SameSite cookies, Secure on HTTPS.
* CSRF: double-submit token on every state-changing request. Strict Content-Security-Policy, no inline
  scripts, no third-party scripts, fonts or CDNs. Clickjacking and MIME-sniffing headers set.
* Connection secrets encrypted at rest (Fernet/AES), masked in the UI, never returned to the browser.
* Uploads: extension allow-list, size caps, content sniffing (PDF/Office/image headers verified), random
  storage names, per-user ownership checks on every file, downloads as attachments; generated HTML previews
  are served with a `sandbox` CSP.
* SSRF guard on every user-supplied URL, webhook and SMTP host: private/loopback/link-local ranges blocked,
  the vetted IP is pinned for the connection (no DNS-rebinding), redirects re-checked, size and time capped.
  LibreOffice runs without network access (Linux `unshare`) and external links are stripped from Office files
  before conversion.
* Resource limits: request bodies are counted while streaming, image/page rendering is pixel-capped,
  page ranges are clamped, and PDF/table readers have page/row/column limits.
* Passwords typed into a problem (e.g. “protect with password …”) are redacted before anything is stored.
* Rate limits on sign-in, sign-up, runs and uploads; per-user daily quotas and concurrency limits.
* Generated code is never executed on the server.

## 7. Legal checklist before a public launch (not legal advice)

* **Privacy** — you process personal data of your users (and of people they e-mail). In India the Digital
  Personal Data Protection Act, 2023 applies; in the EU, the GDPR. Publish a privacy policy and terms on your
  domain, name a grievance contact, keep `RETENTION_DAYS` reasonable. Users can export and delete their data
  from Profile.
* **Platform terms** — Instagram/Meta Platform Terms (official API only, which this app uses), Telegram,
  Discord and Slack terms. Never add password-based or scraping posting: it violates those terms and gets
  accounts banned.
* **Anti-spam** — the e-mail plugin hides recipient lists (BCC) and adds an opt-out line to group mails; users
  must only e-mail people who expect it.
* **Content licences** — Wikipedia text is CC BY-SA 4.0; InEra lists sources and the licence in every
  notebook/PDF built from it. Users are responsible for the rights to photos they upload.
* **Open-source licences** — all Python dependencies are permissive (MIT/BSD/Apache/HPND). AGPL libraries
  (PyMuPDF, Ghostscript) were deliberately avoided so you can run this as a public service without
  publishing your changes. ffmpeg is called as a separate program (GPL/LGPL binary — keep its licence notice
  if you redistribute the Docker image). Bundled fonts are under the SIL Open Font License (see
  `FONT-LICENSES.txt`).
* **AI output** — tell users that AI-written content can be wrong; the invoice plugin is not tax advice.

## 8. Reality check (read this)

* **“No third-party apps” has a hard limit.** You cannot post to someone’s Instagram or send from their Gmail
  without that platform’s permission. InEra keeps it to the minimum: a token or SMTP app password the user
  pastes once, used only by InEra’s own built-in publisher. No connector platforms, no extra accounts.
* **Video overviews are narrated slide videos** (branded slides + voice + subtitles), not generative footage.
* **Offline voices are robotic** (espeak). Use Piper for natural speech.
* **PDF→Word** rebuilds headings, paragraphs, lists, ruled tables and images; complex magazine layouts and
  tables without grid lines come out simplified.
* **PDF output of Indic scripts**: use the Word version for Hindi/Kannada/etc. (basic PDF engines don’t shape
  conjuncts correctly).
* **“Trending” topics need live data.** Research uses Wikipedia and links you supply; it does not read news
  feeds or social media.

## 9. Project layout (flat by design)

```
main.py          web server + REST API          planner.py    problem → plugin pipeline + schedule parser
engine.py        background runner, approvals,   automations.py schedule maths
                 scheduler, housekeeping         registry.py   plugin registry + run context
plg_content.py   research, notebook, writing     plg_learning.py quiz, flashcards, mind map, audio, video
plg_docs.py      PDF/Word/PPT/Excel/web/invoice/ plg_pdftools.py PDF & file tools, OCR, images, QR
                 data analysis/charts            plg_social.py posts, calendar, Instagram, e-mail, messengers, scheduler
plg_dev.py       code project builder            textkit.py    offline NLP + document model + file reading
llm.py           AI engine adapters              brand.py      logo, fonts, slides, speech, ffmpeg
security.py      hashing, vault, SSRF, limits    db.py, config.py, industries.py
index.html, app.js, app.css, logo*.svg/png, favicon.png, *.woff2   web interface
selftest.py, requirements.txt, Dockerfile, docker-compose.yml, .env.example, run.sh, run.bat
```
Runtime data (database, uploads, outputs) lives in `INERA_DATA_DIR` (default `~/inera_data`, `/data` in Docker),
so the code folder stays flat and clean.

## 10. Adding your own plugin

```python
from registry import plugin, PluginError

@plugin("my_tool", "My Tool", "documents", "render", "What it does, in one sentence.",
        keywords=["my keyword"], example="Use my tool on the attached file")
def my_tool(ctx):
    path = ctx.out_path("result.txt")
    path.write_text("hello " + ctx.business)
    ctx.add_output(path, "My result")
```
Import the module in `engine.py` and add a keyword rule in `planner.rule_plan`.
