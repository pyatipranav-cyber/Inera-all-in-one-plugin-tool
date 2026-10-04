"""Agentic planner: turns a plain-language problem into an ordered pipeline of
built-in plugins, a schedule (if recurring) and a human-readable summary.

Rule-based intent detection always runs (fast, deterministic, works offline).
When an AI engine is configured it proposes a plan too; the rules then act as
guard-rails: side-effect plugins (posting, e-mailing, messaging) are only kept
if the user's own words asked for them, and schedules are parsed
deterministically."""
import datetime as dt
import re
from pathlib import Path

import automations
import config
import db
import textkit as tk
from llm import LLMError, engine as llm
from registry import PLUGINS, STAGES

LANG_WORDS = ("hindi|kannada|tamil|telugu|malayalam|marathi|gujarati|bengali|punjabi|urdu|odia|french|german|spanish|"
              "portuguese|italian|arabic|chinese|japanese|korean|russian|dutch|turkish|indonesian|thai|vietnamese|"
              "persian|nepali|sinhala|english")
DAYS = {"monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2, "thursday": 3, "thu": 3,
        "thur": 3, "thurs": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6}
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL_RE = re.compile(r"https?://\S+")

ORDER = ["web_research", "ocr_extract", "extract_text", "data_analyst", "notebook_builder", "summarizer", "ask_ai",
         "content_writer", "content_calendar", "social_post_designer", "rewriter", "translator", "invoice_generator",
         "unlock_pdf", "office_to_pdf", "images_to_pdf", "merge_pdf", "split_pdf", "rotate_pdf", "page_numbers",
         "watermark_pdf", "compress_pdf", "pdf_to_word", "pdf_to_images", "protect_pdf", "image_tools", "qr_generator",
         "pdf_creator", "word_creator", "slide_deck", "excel_creator", "chart_maker", "website_builder",
         "code_project_builder", "quiz_mcq", "flashcards", "mind_map", "audio_overview", "video_overview", "zip_files",
         "instagram_publisher", "email_sender", "messenger", "automation_scheduler"]


# ======================================================================= schedule
def _hour24(h: int, mer: str, context: str) -> int:
    mer = (mer or "").replace(".", "").strip()
    if mer.startswith("p") and h < 12:
        return h + 12
    if mer.startswith("a") and h == 12:
        return 0
    if not mer.startswith(("a", "p")):
        if re.search(r"\b(evening|night|tonight|afternoon)\b", context) and h < 12:
            return h + 12
    return h


def find_times(text: str) -> tuple:
    low = text.lower()
    times, assumed = [], False
    pats = [
        r"\b(\d{1,2})[:.](\d{2})\s*(a\.?m\.?|p\.?m\.?)?",
        r"\b(\d{1,2})()\s*(a\.?m\.?|p\.?m\.?)(?![a-z])",
        r"\b(\d{1,2})()\s*o['’]?\s?clock(?:\s*(?:in the)?\s*(morning|evening|night|afternoon|am|pm))?",
        r"\bat\s+(\d{1,2})()(?!\s*(?:%|days?|questions?|slides?|cards?|x\b|mcqs?|pages?|posts?|items?|\d|[:.]\d))(\s*(?:in the)?\s*(?:morning|evening|night|afternoon))?",
    ]
    taken = []
    for pat in pats:
        for m in re.finditer(pat, low):
            if any(a <= m.start(1) < b for a, b in taken):
                continue
            h = int(m.group(1))
            mins = int(m.group(2)) if m.group(2) else 0
            mer = (m.group(3) or "").strip()
            if h > 23 or mins > 59:
                continue
            ctx_win = low[m.start(): m.end() + 25]
            if not mer and not re.search(r"evening|night|afternoon|morning", ctx_win) and 1 <= h <= 11 and \
                    not re.search(r"\d[:.]\d", m.group(0)):
                assumed = True
                if 1 <= h <= 5:
                    h += 12  # "at 3" most likely means 3 pm for business tasks
            elif mer in ("morning",):
                pass
            h = _hour24(h, "pm" if mer in ("evening", "night", "afternoon") else mer, ctx_win)
            times.append(f"{h:02d}:{mins:02d}")
            taken.append((m.start(1), m.end()))
    if re.search(r"\bnoon\b|\bmidday\b", low):
        times.append("12:00")
    if re.search(r"\bmidnight\b", low):
        times.append("00:00")
    return sorted(set(times)), assumed


def parse_schedule(text: str, tz_name: str = "UTC", has_delivery: bool = False):
    low = " " + text.lower() + " "
    times, assumed = find_times(text)
    weak_ok = bool(times) or has_delivery or bool(re.search(r"\b(remind|send|post|publish|upload|notify|deliver)\b", low))
    sched = None
    m = re.search(r"\bevery\s+(\d+)\s*(minutes?|mins?|hours?|hrs?)\b", low)
    if m:
        n = int(m.group(1)) * (60 if m.group(2).startswith("h") else 1)
        sched = {"type": "interval", "minutes": max(config.MIN_INTERVAL_MINUTES, n)}
    elif re.search(r"\b(hourly|every hour)\b", low):
        sched = {"type": "interval", "minutes": 60}
    elif re.search(r"\bevery half[- ]an? hour|every half hour\b", low):
        sched = {"type": "interval", "minutes": max(30, config.MIN_INTERVAL_MINUTES)}
    if sched is None:
        found_days = []
        for name, idx in DAYS.items():
            if re.search(r"\b(?:every|each|on)\s+(?:\w+\s+(?:and|&|,)\s+)*" + name + r"s?\b", low) or \
                    re.search(r"\b" + name + r"s\b", low):
                found_days.append(idx)
        if found_days:
            more = [DAYS[d] for d in re.findall(r"\b(" + "|".join(DAYS) + r")s?\b", low)]
            sched = {"type": "weekly", "days": sorted(set(found_days + more))}
        elif re.search(r"\b(every )?weekdays?\b", low) and re.search(r"\b(every|on|weekdays)\b", low):
            sched = {"type": "weekly", "days": [0, 1, 2, 3, 4]}
        elif re.search(r"\bevery weekend|\bon weekends\b", low):
            sched = {"type": "weekly", "days": [5, 6]}
        elif re.search(r"\b(every week|once a week|each week)\b", low) or (re.search(r"\bweekly\b", low) and weak_ok):
            sched = {"type": "weekly", "days": [0]}
        elif re.search(r"\b(every month|each month|once a month)\b", low) or (re.search(r"\bmonthly\b", low) and weak_ok):
            dm = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)\b", low)
            sched = {"type": "monthly", "day": int(dm.group(1)) if dm and 1 <= int(dm.group(1)) <= 31 else 1}
        elif re.search(r"\b(twice a day|two times a day)\b", low):
            sched = {"type": "daily"}
            if len(times) < 2:
                times = ["09:00", "18:00"]
        elif re.search(r"\b(every day|each day|every single day|daily|once a day|per day|every morning|every evening|"
                       r"every night|regularly|day by day)\b", low) or (re.search(r"\beveryday\b", low) and times):
            strong = re.search(r"\b(every day|each day|every single day|every morning|every evening|every night|"
                               r"regularly|once a day)\b", low)
            if strong or times or has_delivery:
                sched = {"type": "daily"}
                if not times:
                    if "morning" in low:
                        times = ["09:00"]
                    elif "evening" in low:
                        times = ["18:00"]
                    elif "night" in low:
                        times = ["21:00"]
    if sched is None:
        tz = automations.tzinfo(tz_name)
        now = dt.datetime.now(tz)
        m = re.search(r"\bin\s+(\d{1,3})\s*(minutes?|mins?|hours?|hrs?)\b", low)
        if m and re.search(r"\b(remind|send|post|publish|email|run|do|at)\b", low):
            delta = dt.timedelta(minutes=int(m.group(1)) * (60 if m.group(2).startswith("h") else 1))
            return {"type": "once", "at": (now + delta).replace(second=0, microsecond=0, tzinfo=None).isoformat()}
        day = None
        if re.search(r"\btomorrow\b", low):
            day = now.date() + dt.timedelta(days=1)
        elif re.search(r"\b(today|tonight)\b", low) and times:
            day = now.date()
        else:
            dm = re.search(r"\bon\s+(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(MONTHS) + r")[a-z]*\b", low) or \
                re.search(r"\bon\s+(" + "|".join(MONTHS) + r")[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?\b", low)
            if dm:
                a, b = dm.group(1), dm.group(2)
                dd, mon = (int(a), MONTHS[b[:3]]) if a.isdigit() else (int(b), MONTHS[a[:3]])
                year = now.year if (mon, dd) >= (now.month, now.day) else now.year + 1
                try:
                    day = dt.date(year, mon, dd)
                except ValueError:
                    day = None
        if day and (times or re.search(r"\b(remind|send|post|publish|schedule)\b", low)):
            t = (times or ["09:00"])[0]
            return {"type": "once", "at": f"{day.isoformat()}T{t}"}
        return None
    if sched["type"] in ("daily", "weekly", "monthly"):
        sched["times"] = times or ["09:00"]
        if assumed:
            sched["assumption"] = True
    return sched


# ======================================================================= topic
def extract_topic(problem: str) -> str:
    p = URL_RE.sub(" ", EMAIL_RE.sub(" ", problem))
    p = re.sub(r"\s+", " ", p).strip()
    stop = (r"(?=\s+(?:with|and then|then|and also|also|including|plus|in\s+(?:a\s+)?(?:pdf|word|ppt|"
            + LANG_WORDS + r")|as\s+(?:a|an)\b|into|for (?:my|me|our|the|kids|students|beginners|class|children)|"
            r"every|daily|weekly|at\s+\d|and\s+(?:make|create|give|send|turn|convert|generate|post|email)|"
            r"and\s+(?:a|an|the)?\s*(?:quiz|mcq|pdf|ppt|video|flash|mind|podcast|audio|slides?|presentation|summary))\b"
            r"|[,.;!?\n]|$)")
    for prep in (r"(?:on|about|regarding|covering|explaining|explain|topic[:\s]|titled|called|announcing|"
                 r"introducing|promoting|related to|the topic of|learn|teach me|understand)",):
        for m in re.finditer(r"\b" + prep + r"\s+(?:the\s+(?:topic\s+(?:of\s+)?)?)?(.+?)" + stop, p, re.I):
            topic = m.group(1).strip(" -:\"'“”")
            topic = re.sub(r"^(?:a|an|the|my|our)\s+", "", topic, flags=re.I)
            if re.fullmatch(r"(it|this|that|them|these|telegram|instagram|insta|ig|discord|slack|whatsapp|facebook|"
                            r"linkedin|twitter|x|youtube|my account|e-?mail|mail|pdf|word|excel|monday|tuesday|"
                            r"wednesday|thursday|friday|saturday|sunday|weekdays|weekends)", topic, re.I):
                continue
            if 1 <= len(topic.split()) <= 14:
                return topic[:120], True
    filler = (r"\b(please|can you|could you|i want(?: you)? to|i need(?: you)? to|i would like to|help me|make|create|"
              r"generate|build|give me|write|draft|prepare|produce|design|research|find|show me|tell me|a|an|the|me|"
              r"some|study|notebook|notes|pdf|ppt|pptx|presentation|slides?|deck|video|quiz|mcqs?|questions|"
              r"flash ?cards?|mind ?map|podcast|audio|summary|report|document|doc|word|file|of|for|with|and|"
              r"email|e-mail|send|post|upload|me|at|to|my|our|your|this|these|that|into|on|i|can|it|turn|convert|"
              r"attached|uploaded|tell|trends?|analy[sz]e|\d+)\b")
    p = re.sub(r"\b(every|each)\s+(day|morning|evening|night|week|month|monday|tuesday|wednesday|thursday|friday|"
               r"saturday|sunday|weekday)s?\b|\b(daily|weekly|monthly|regularly|tomorrow|today)\b|"
               r"\bat\s+\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.|o'?clock)?|\b\d{1,2}\s*(?:am|pm)\b", " ", p,
               flags=re.I)
    p = re.sub(r"^\s*(what|how|why|who|when|where|which)\s+(is|are|was|were|do|does|did|can|should|to)\s+(i\s+|we\s+)?",
               "", p, flags=re.I)
    p = re.sub(r"\b(summary|overview|guide|tips|news|report|introduction)\s+(of|on|to|about|for)\s+", " ", p, flags=re.I)
    rest = re.sub(filler, " ", p, flags=re.I)
    rest = re.sub(r"\s+", " ", rest).strip(" ,.-:")
    words = rest.split()
    return " ".join(words[:10])[:120], False


# ======================================================================= rules
def _has(low, pat):
    return re.search(pat, low) is not None


def _file_kinds(files: list) -> dict:
    exts = [Path(f["name"]).suffix.lower() for f in files]
    return {"pdf": sum(e == ".pdf" for e in exts),
            "image": sum(e in tk.IMAGE_EXT for e in exts),
            "office": sum(e in (".docx", ".doc", ".odt", ".rtf", ".pptx", ".ppt", ".odp", ".xls", ".ods", ".txt",
                                ".md", ".html", ".htm") for e in exts),
            "table": sum(e in (".csv", ".tsv", ".xlsx", ".xlsm") for e in exts),
            "any": len(exts)}


def rule_plan(problem: str, files: list, profile: dict) -> dict:
    # quoted text (e.g. a watermark label) must not trigger intents
    low = " " + re.sub(r"[\"“”][^\"“”]{0,200}[\"“”]", " ", problem.lower()) + " "
    fk = _file_kinds(files)
    want = []

    def add(pid, **params):
        if pid in PLUGINS and pid not in [w[0] for w in want]:
            want.append((pid, params))

    # ---------------------------------------------------------- file tools
    if _has(low, r"pdf\s*(?:file\s*)?(?:to|into|->|2)\s*(?:a\s+)?(?:word|docx?|editable)") or \
            (fk["pdf"] and _has(low, r"\bconvert\b") and _has(low, r"\b(word|docx|editable)\b")):
        add("pdf_to_word")
    if _has(low, r"\b(word|docx?|ppt|pptx|powerpoint|excel|xlsx?|txt|text|html|odt)\s*(?:file|document|doc)?\s*(?:to|into|->|2)\s*(?:a\s+)?pdf") or \
            (fk["office"] and _has(low, r"\b(convert|export|save|turn)\b.*\bpdf\b")):
        add("office_to_pdf")
    if _has(low, r"\b(merge|combine|join)\b") and (fk["pdf"] + fk["image"] >= 2 or _has(low, r"\bpdfs?\b")):
        add("merge_pdf")
    if _has(low, r"\bsplit\b|\bextract (?:the )?pages?\b|\bseparate (?:the |all )?pages\b"):
        add("split_pdf")
    if _has(low, r"\b(compress|reduce (?:the |its )?(?:file )?size|shrink|make (?:it|this|the pdf) smaller|optimi[sz]e)\b") \
            and (fk["pdf"] or _has(low, r"\bpdf\b")) and not fk["image"]:
        add("compress_pdf")
    if _has(low, r"\brotate\b") and (fk["pdf"] or _has(low, r"\bpdf\b")):
        add("rotate_pdf")
    if _has(low, r"\bwatermark\b"):
        add("watermark_pdf")
    if _has(low, r"page numbers?|number (?:the|all|each) pages?|paginat"):
        add("page_numbers")
    if _has(low, r"\bunlock\b|\bdecrypt\b|remove (?:the )?password"):
        add("unlock_pdf")
    elif _has(low, r"password[- ]protect|\b(protect|encrypt|lock)\b.{0,40}\b(pdf|password|file)\b"):
        add("protect_pdf")
    if _has(low, r"pdf\s*(?:file\s*)?(?:to|into|->|2)\s*(?:jpe?g|png|images?|pictures?|photos?)") or \
            (fk["pdf"] and not fk["image"] and _has(low, r"\b(convert|turn|export|save|render)\b.{0,40}\b(?:to|into|as)\s+"
                                                         r"(?:jpe?g|png|images?|pictures?)\b")):
        add("pdf_to_images")
    if _has(low, r"(jpe?gs?|pngs?|images?|photos?|pictures?|scans?|screenshots?)\s*(?:to|into|->|2)\s*(?:a\s+|one\s+|single\s+)?pdf") or \
            (fk["image"] and not fk["pdf"] and _has(low, r"\b(make|create|convert|turn|combine)\b.*\bpdf\b")
             and not _has(low, r"\b(ocr|text)\b")):
        add("images_to_pdf")
    if _has(low, r"\bocr\b|scanned|searchable|text (?:from|in|out of) (?:this |the |my |these )?(?:image|photo|picture|"
                 r"screenshot|scan)|read (?:the )?text|image to text|handwrit"):
        add("ocr_extract")
    elif _has(low, r"extract (?:all |the )?text|plain text|to txt|get (?:the |all )?text"):
        add("extract_text")
    if fk["image"] and _has(low, r"\b(resize|crop|convert|compress|reduce|webp|jpe?g|png|thumbnail|metadata|exif|"
                                  r"dimensions?|story size|instagram size|smaller)\b") and \
            not _has(low, r"\bpdf\b") and "images_to_pdf" not in [w[0] for w in want]:
        add("image_tools")
    if _has(low, r"\bqr\b"):
        add("qr_generator")
    if _has(low, r"\bzip\b(?!\s*code)|\bmake an archive\b"):
        add("zip_files")

    # ---------------------------------------------------------- business / data
    if _has(low, r"\binvoice|\bbill (?:for|to)\b|\bestimate for\b|\bquotation\b"):
        add("invoice_generator")
    if fk["table"] and (_has(low, r"analy[sz]|insight|trend|statistic|dashboard|report|summar|understand|what does") or
                        not want):
        add("data_analyst")
    if _has(low, r"\b(chart|graph|plot)\b") and "data_analyst" not in [w[0] for w in want]:
        add("chart_maker")
    low_nc = low.replace("qr code", "qr")
    is_code = _has(low_nc, r"\b(react|python|javascript|node(?:\.?js)?|express|fastapi|flask|django|chrome extension|"
                        r"browser extension|api|backend|frontend|script|program|source code|code)\b") and \
        _has(low_nc, r"\b(build|create|make|write|generate|develop|code|scaffold)\b")
    if _has(low, r"\b(website|landing page|web ?page|one[- ]page site|portfolio site|homepage)\b") and not is_code:
        add("website_builder")
    elif is_code:
        add("code_project_builder")

    # ---------------------------------------------------------- social & delivery
    social = _has(low, r"\b(instagram|insta|ig|facebook|fb|linkedin|social media|socials)\b")
    if _has(low, r"content (?:calendar|plan)|posting (?:schedule|plan|calendar)|\d+\s*days? of (?:\w+\s+){0,2}(?:content|posts)|"
                 r"social media plan|month(?:'s)? of (?:content|posts)"):
        add("content_calendar")
    elif social and _has(low, r"\b(post|posts|upload|image|images|picture|photo|creative|content|story|caption|publish|"
                              r"share|reel)\b") and not ("image_tools" in [w[0] for w in want] and
                                                         not _has(low, r"\b(post|publish|upload|caption)\b")):
        add("social_post_designer")
    elif _has(low, r"\b(poster|banner|flyer|social post)\b"):
        add("social_post_designer")
    publish_verb = r"\b(upload|publish|share|put|schedule)\b|\bauto[- ]?post|\bpost(?:ing|ed)?\s+(?:it|this|them|these|that|" \
                   r"on|to|in|daily|every|at|regularly|automatically|for me|each)\b|\bsend the post\b|" \
                   r"\bpost\b.{0,80}\b(?:on|to|in)\s+(?:my\s+|our\s+)?(?:instagram|insta|ig)\b"
    if _has(low, r"\b(instagram|insta|ig)\b") and _has(low, publish_verb) and \
            "content_calendar" not in [w[0] for w in want]:
        add("social_post_designer")
        add("instagram_publisher")
    emails = [e for e in EMAIL_RE.findall(problem)]
    if emails and _has(low, r"\b(send|email|e-mail|mail|deliver|share)\b"):
        add("email_sender", to=emails)
    if _has(low, r"\b(telegram|discord|slack|webhook)\b"):
        add("messenger")

    # ---------------------------------------------------------- learning outputs
    if _has(low, r"\b(quiz|quizzes|mcqs?|multiple[- ]choice|test questions|question paper|exam questions|practice questions)\b"):
        add("quiz_mcq")
    if _has(low, r"flash ?cards?|revision cards|\banki\b"):
        add("flashcards")
    if _has(low, r"mind ?map|concept map"):
        add("mind_map")
    if _has(low, r"\b(podcast|audio overview|audio version|audio|mp3|listen to|narrat(?:e|ion))\b"):
        add("audio_overview")
    if _has(low, r"\b(videos?|mp4|explainer|video overview|animated)\b") and not _has(low, r"\bvideo (?:to|into)\b"):
        add("video_overview")

    # ---------------------------------------------------------- renderers
    conversion = any(w[0] in ("pdf_to_word", "office_to_pdf", "images_to_pdf", "merge_pdf", "split_pdf", "compress_pdf",
                              "rotate_pdf", "watermark_pdf", "page_numbers", "protect_pdf", "unlock_pdf",
                              "pdf_to_images", "ocr_extract", "extract_text") for w in want)
    m_slides = re.search(r"\b(\d{1,2})[- ]?slides?\b", low)
    if _has(low, r"\b(ppt|pptx|powerpoint|slides?|slide deck|presentation|deck)\b") and not conversion:
        add("slide_deck", **({"slides": int(m_slides.group(1))} if m_slides else {}))
    if _has(low, r"\b(word (?:file|doc|document|format|version)|docx|ms word|in word\b|as (?:a )?word\b|editable document)\b") \
            and not conversion:
        add("word_creator")
    if _has(low, r"\b(excel|xlsx|spreadsheet|google sheet|tracker)\b") and "content_calendar" not in [w[0] for w in want]:
        add("excel_creator")
    low_out = re.sub(r"\b(this|the|attached|uploaded|my|these|that|those|your)\s+(\w+\s+)?pdfs?\b", " ", low)
    if _has(low_out, r"\bpdfs?\b|\bebook\b|\bhandout\b|\bbrochure\b|\bprintable\b") and not conversion and \
            "invoice_generator" not in [w[0] for w in want]:
        add("pdf_creator")

    # ---------------------------------------------------------- writing & knowledge
    if _has(low, r"translat|\b(?:in|into)\s+(?:" + LANG_WORDS + r")\b"):
        lang = re.search(r"\b(?:in|into|to)\s+(" + LANG_WORDS + r")\b", low)
        if not (lang and lang.group(1) == "english" and not _has(low, r"translat")):
            add("translator", **({"language": lang.group(1)} if lang else {}))
    if _has(low, r"proofread|grammar|rephrase|paraphrase|\brewrite\b|\bpolish\b|make (?:it|this) (?:more |sound )?"
                 r"(formal|professional|friendly|casual|shorter|simpler|persuasive)"):
        add("rewriter")
    if _has(low, r"summar|\btl;?dr\b|key points|\bgist\b|\bdigest\b|brief me"):
        add("summarizer")
    notebook_words = _has(low, r"\bnotebook|\bresearch\b|study (?:guide|material|notes|pack)|notes (?:on|about|for)|\blearn\b|"
                               r"teach me|\bexplain|\blesson|\bchapter\b|\bcourse\b|\bsyllabus|tutorial|briefing|"
                               r"deep dive|understand|revision")
    writing_kind = _has(low, r"\b(write|draft|compose)\b|\b(blog|article|essay|letter|cover letter|proposal|press release|"
                             r"resume|cv|speech|story|script|newsletter|business plan|sop|policy|caption|"
                             r"product description|ad copy|linkedin post|tweet)\b|\bemail\b(?!\s+(?:it|this|them|to\s+\S+@))")
    producers = {"notebook_builder", "summarizer", "content_writer", "data_analyst", "content_calendar", "ask_ai",
                 "social_post_designer"}
    if notebook_words and not writing_kind:
        add("notebook_builder")
    elif writing_kind:
        explicit_write = _has(low, r"\b(write|draft|compose)\b")
        post_only = "social_post_designer" in [w[0] for w in want] and \
            not _has(low, r"\b(blog|article|email|letter|newsletter)\b")
        file_only = bool(want) and all(PLUGINS[w[0]].category in ("pdf", "media") for w in want)
        transform = any(w[0] in ("rewriter", "translator", "summarizer") for w in want)
        if transform and not explicit_write:
            file_only = True
        if (explicit_write or not any(w[0] in producers for w in want)) and not post_only and \
                not (file_only and not explicit_write):
            add("content_writer")

    ids = [w[0] for w in want]
    learning = {"quiz_mcq", "flashcards", "mind_map", "audio_overview", "video_overview"}
    renderers = {"pdf_creator", "word_creator", "slide_deck"}
    needs_content = any(i in learning | renderers for i in ids) or "translator" in ids or "email_sender" in ids \
        or "messenger" in ids
    has_producer = any(i in producers for i in ids)
    text_inputs = fk["pdf"] + fk["office"] + fk["table"] > 0
    if needs_content and not has_producer:
        if text_inputs and "translator" in ids:
            pass
        elif text_inputs and any(i in ("mind_map", "audio_overview", "video_overview", "slide_deck") for i in ids):
            add("notebook_builder")
        elif text_inputs:
            pass
        elif "email_sender" in ids and not (learning | renderers) & set(ids):
            add("content_writer", kind="email")
        elif "messenger" in ids and not (learning | renderers) & set(ids):
            add("social_post_designer" if (social or _has(low, r"\b(image|picture|poster|quote|post|graphic)\b"))
                else "ask_ai")
        else:
            add("notebook_builder")
    ids = [w[0] for w in want]
    # research when the content must come from knowledge and no documents were given
    from plg_content import detect_kind
    writer_kind = next((w[1].get("kind") for w in want if w[0] == "content_writer" and w[1].get("kind")), None) \
        or detect_kind(problem)
    long_form = _has(low, r"\b(blog|article|essay|report|guide|ebook|research|business plan|proposal)\b") and \
        writer_kind not in ("email", "caption", "letter", "cover letter", "speech", "story")
    knowledge_steps = {"notebook_builder", "ask_ai"} | ({"content_writer"} if long_form else set())
    url_needed = URL_RE.search(problem) and (not ids or any(i in knowledge_steps | {"summarizer", "content_writer"}
                                                             | learning | renderers for i in ids))
    if url_needed and not any(i in knowledge_steps | {"summarizer", "content_writer"} for i in ids):
        add("summarizer")
        ids = [w[0] for w in want]
    if url_needed or (any(i in knowledge_steps for i in ids) and not text_inputs) or \
            ("summarizer" in ids and not text_inputs):
        add("web_research")
    ids = [w[0] for w in want]
    if "translator" in ids and text_inputs and not renderers & set(ids):
        add("word_creator")
    if any(i in ("notebook_builder", "summarizer") for i in ids) and not (renderers | {"translator"}) & set(ids):
        add("pdf_creator")
    fallback = not want
    if not want:
        if text_inputs:
            add("summarizer")
            add("pdf_creator")
        elif fk["image"]:
            add("ocr_extract")
        else:
            add("ask_ai")
            add("web_research")
    return {"steps": [{"plugin": pid, "params": params} for pid, params in want], "fallback": fallback}


# ======================================================================= LLM plan
def llm_plan(problem: str, files: list, profile: dict):
    lines = [f"- {p.id}: {p.description}" + (f" Params: {p.params}" if p.params else "")
             for p in PLUGINS.values()]
    file_list = ", ".join(f["name"] for f in files) or "none"
    prompt = (
        "You are the planner of an automation platform with these built-in plugins:\n" + "\n".join(lines) +
        f"\n\nUser problem: {problem}\nUploaded files: {file_list}\n"
        f"User business: {profile.get('business_name', '')} ({profile.get('industry', '')})\n\n"
        "Choose the minimal ordered list of plugins that fully solves the problem. Content producers "
        "(web_research, notebook_builder, content_writer, summarizer) come before renderers (pdf_creator, word_creator, "
        "slide_deck) and learning outputs (quiz_mcq, flashcards, mind_map, audio_overview, video_overview). Add "
        "automation_scheduler last if the user wants it repeated or at a time. Only include instagram_publisher, "
        "email_sender or messenger if the user explicitly asks to post/send. Return JSON "
        '{"title": str (max 8 words), "topic": str, "steps": [{"plugin": str, "params": object}]}.')
    data = llm.complete_json(prompt, max_tokens=1200, temperature=0.1)
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
        return None
    steps = []
    for s in data["steps"]:
        if isinstance(s, dict) and s.get("plugin") in PLUGINS:
            params = s.get("params") if isinstance(s.get("params"), dict) else {}
            params = {k: v for k, v in params.items() if k in PLUGINS[s["plugin"]].params and k != "password"}
            steps.append({"plugin": s["plugin"], "params": params})
    return {"steps": steps, "title": str(data.get("title") or "")[:80], "topic": str(data.get("topic") or "")[:120]}


# ======================================================================= secrets
SECRET_RE = re.compile(r"\b(password|passcode|passwd|pwd)\b(\s*(?:is|=|:|-|of|as)?\s*)[\"'“]?([^\s\"'”,;]{3,64})", re.I)


def split_secrets(problem: str) -> tuple:
    secrets = {}
    m = SECRET_RE.search(problem)
    if m and m.group(3).lower() not in ("protect", "protected", "protection", "and", "for", "to", "the"):
        secrets["password"] = m.group(3)
        problem = problem[:m.start(3)] + "••••••" + problem[m.end(3):]
    return problem, secrets


# ======================================================================= main
STAGE_RANK = {s: i for i, s in enumerate(STAGES)}
SIDE_GUARDS = {
    "instagram_publisher": r"\b(instagram|insta|ig)\b",
    "email_sender": r"@",
    "messenger": r"\b(telegram|discord|slack|webhook)\b",
}


def _ordered(steps: list) -> list:
    rank = {pid: i for i, pid in enumerate(ORDER)}
    seen, out = set(), []
    for s in sorted(steps, key=lambda s: (STAGE_RANK.get(PLUGINS[s["plugin"]].stage, 50), rank.get(s["plugin"], 99))):
        if s["plugin"] not in seen:
            seen.add(s["plugin"])
            out.append(s)
    return out


def summarize_plan(plan: dict) -> str:
    names = [PLUGINS[s["plugin"]].name for s in plan["steps"] if s["plugin"] != "automation_scheduler"]
    if not names:
        return "Nothing to do."
    text = "I'll run " + (", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0])
    if plan.get("schedule"):
        text += f", then repeat it automatically: {automations.describe(plan['schedule']).lower()}"
    return text + "."


def readiness(plan: dict, user_id: str, files: list) -> list:
    notes = []
    configured = {r["kind"] for r in db.query("SELECT kind FROM secrets WHERE user_id=?", (user_id,))}
    fk = _file_kinds(files)
    for s in plan["steps"]:
        p = PLUGINS[s["plugin"]]
        for need in p.needs:
            if need.startswith("vault:") and need[6:] not in configured:
                label = {"instagram": "Instagram", "smtp": "E-mail (SMTP)", "messenger": "a messenger"}[need[6:]]
                notes.append(f"Connect {label} in Connections so “{p.name}” can run.")
            if need == "public_url" and not config.PUBLIC_BASE_URL.startswith("https://"):
                notes.append("Instagram needs this server on a public HTTPS address (PUBLIC_BASE_URL).")
            if need == "files:pdf" and not fk["pdf"]:
                notes.append(f"“{p.name}” needs a PDF — attach one.")
            if need == "files:image" and not fk["image"]:
                notes.append(f"“{p.name}” needs images — attach them.")
            if need == "files:csv,xlsx" and not fk["table"]:
                notes.append(f"“{p.name}” needs a CSV or Excel file.")
        if s["plugin"] == "translator" and not llm.available():
            notes.append("Translation needs an AI engine (Ollama or an API key).")
    sched = plan.get("schedule")
    if sched and sched.get("assumption"):
        notes.append(f"I read the time as {', '.join(sched.get('times', []))} (24-hour). Say “am” or “pm” to change it.")
    return list(dict.fromkeys(notes))


def make_plan(problem: str, files: list, user: dict) -> dict:
    profile = user.get("profile") or {}
    clean_problem, secrets = split_secrets(problem)
    base = rule_plan(clean_problem, files, profile)
    plan = {"steps": base["steps"], "engine": "rules"}
    # The deterministic rules are the primary planner. The AI engine is consulted only when the
    # rules could not recognise the request, so a weak model can never derail a clear request.
    if base.get("fallback") and llm.available():
        try:
            ai = llm_plan(clean_problem, files, profile)
            if ai and ai["steps"]:
                low = clean_problem.lower()
                steps = [s for s in ai["steps"] if s["plugin"] not in SIDE_GUARDS or
                         re.search(SIDE_GUARDS[s["plugin"]], low)]
                rule_params = {s["plugin"]: s["params"] for s in base["steps"]}
                for s in steps:
                    s["params"] = {**s["params"], **rule_params.get(s["plugin"], {})}
                # keep deterministic file tools and side effects the rules found
                ai_ids = {s["plugin"] for s in steps}
                for s in base["steps"]:
                    p = PLUGINS[s["plugin"]]
                    if s["plugin"] not in ai_ids and (p.side_effect or p.category == "pdf" or p.stage == "schedule"):
                        steps.append(s)
                plan = {"steps": steps, "engine": "ai", "title": ai.get("title"), "topic": ai.get("topic")}
        except LLMError:
            pass
    tz = profile.get("timezone") or "UTC"
    has_delivery = any(PLUGINS[s["plugin"]].side_effect for s in plan["steps"])
    schedule = parse_schedule(clean_problem, tz, has_delivery)
    steps = [s for s in plan["steps"] if s["plugin"] != "automation_scheduler"]
    if schedule:
        steps.append({"plugin": "automation_scheduler", "params": {}})
    if any(s["plugin"] == "instagram_publisher" for s in steps) and \
            not any(s["plugin"] in ("social_post_designer", "content_calendar") for s in steps):
        steps.append({"plugin": "social_post_designer", "params": {}})
    plan["steps"] = _ordered(steps)
    plan["schedule"] = schedule
    topic, confident = extract_topic(clean_problem)
    if not confident and files:
        docs = [f for f in files if Path(f["name"]).suffix.lower() not in tk.IMAGE_EXT] or files
        topic = re.sub(r"[_\-]+", " ", Path(docs[0]["name"]).stem).strip() or topic
        confident = True
    plan["topic"] = (plan.get("topic") or topic).strip()
    if not plan.get("title"):
        visible = [PLUGINS[s["plugin"]].name for s in plan["steps"] if s["plugin"] != "automation_scheduler"]
        knowledge = any(s["plugin"] in ("web_research", "notebook_builder", "ask_ai", "content_writer", "summarizer",
                                        "quiz_mcq", "video_overview") for s in plan["steps"])
        if plan["topic"] and (confident or (knowledge and len(plan["topic"].split()) >= 2)):
            plan["title"] = tk.title_case(tk.truncate_words(plan["topic"], 8)).strip("…")
        else:
            nouns = {"instagram_publisher": "Instagram post", "social_post_designer": "Social media post",
                     "email_sender": "E-mail", "messenger": "Message", "content_calendar": "Content calendar",
                     "invoice_generator": "Invoice", "website_builder": "Website", "data_analyst": "Data analysis",
                     "code_project_builder": "Code project", "excel_creator": "Spreadsheet", "chart_maker": "Chart"}
            ids = [s["plugin"] for s in plan["steps"]]
            noun = next((nouns[i] for i in ("instagram_publisher", "email_sender", "messenger", "social_post_designer",
                                            "content_calendar", "invoice_generator", "website_builder", "data_analyst",
                                            "code_project_builder", "excel_creator", "chart_maker") if i in ids), None)
            if noun and schedule:
                freq = {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly"}.get(schedule.get("type"), "Recurring")
                plan["title"] = f"{freq} {noun[:1].lower() + noun[1:] if noun[:2] != 'In' else noun}"
            elif noun:
                plan["title"] = noun
            else:
                plan["title"] = " + ".join(visible[:3]) or "Task"
    plan["summary"] = summarize_plan(plan)
    plan["notes"] = readiness(plan, user["id"], files)
    plan["_secrets"] = secrets
    plan["clean_problem"] = clean_problem
    return plan
