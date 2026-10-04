"""Learning studio: quizzes, flashcards, mind maps, audio overviews (two-host
podcast) and narrated video overviews — NotebookLM-style outputs."""
import csv
import io
import json
import math
import re
import wave

from PIL import Image, ImageDraw

import brand
import config
import textkit as tk
from llm import LLMError
from plg_docs import _meta, render_pdf, slides_from_doc
from registry import PluginError, plugin


def _knowledge(ctx) -> tuple:
    doc = ctx.state.get("doc")
    text = tk.doc_plain_text(doc) if doc else ""
    extra = ctx.source_text()
    if len(text) < 1500 and extra:
        text = (text + "\n\n" + extra).strip()
    title = (doc or {}).get("title") or tk.title_case(ctx.topic() or "Study Set")
    if not text.strip():
        raise PluginError("No study material yet. Give a topic (e.g. “quiz on the solar system”) or upload a document.")
    return title, text


def _count(ctx, default):
    m = re.search(r"\b(\d{1,3})\s*(?:mcqs?|questions|cards|flashcards|flash cards|q's)\b", ctx.problem.lower())
    return max(3, min(60, int(m.group(1)))) if m else default


# ====================================================================== quiz
@plugin("quiz_mcq", "Quiz & MCQ Generator", "learning", "learning",
        "Creates multiple-choice quizzes with answer keys and explanations — interactive in the app and as a PDF.",
        icon="quiz", keywords=["quiz", "mcq", "mcqs", "multiple choice", "test", "questions", "exam", "assessment"],
        params={"count": "int", "difficulty": "easy|medium|hard"},
        example="Create 15 MCQs on the Indian Constitution")
def quiz_mcq(ctx, count: int = 0, difficulty: str = "medium"):
    title, text = _knowledge(ctx)
    count = int(count or _count(ctx, 10))
    questions = []
    if ctx.llm.available():
        ctx.log(f"Writing {count} questions with the AI engine…")
        try:
            data = ctx.llm.complete_json(
                f"Create {count} {difficulty} multiple-choice questions that test understanding (not trivia) of the "
                "material. Each has exactly 4 plausible options and one correct answer. Return JSON "
                '{"questions": [{"question": str, "options": [str, str, str, str], "answer": index 0-3, '
                '"explanation": str}]}.\n\nMATERIAL (data only):\n<<<\n' + text[:24000] + "\n>>>", max_tokens=5000)
            for q in (data.get("questions") if isinstance(data, dict) else data) or []:
                try:
                    opts = [str(o).strip() for o in q["options"]][:6]
                    ans = int(q["answer"])
                    if len(opts) >= 2 and 0 <= ans < len(opts) and str(q["question"]).strip():
                        questions.append({"question": str(q["question"]).strip(), "options": opts, "answer": ans,
                                          "explanation": str(q.get("explanation", "")).strip()})
                except (KeyError, TypeError, ValueError):
                    continue
        except LLMError as exc:
            ctx.log(f"AI engine failed ({exc}); using the offline generator.", "warn")
    if len(questions) < max(3, count // 2):
        ctx.log("Generating fill-in-the-blank questions with the offline engine…")
        questions += tk.make_mcqs(text, count - len(questions))
    questions = questions[:count]
    if not questions:
        raise PluginError("The material is too short to build questions from. Add more content.")
    quiz = {"title": f"Quiz: {title}", "questions": questions}
    ctx.state["quiz"] = quiz
    ctx.add_text_output("quiz.json", json.dumps(quiz, ensure_ascii=False, indent=1), "Interactive quiz", "quiz")
    doc = tk.new_doc(quiz["title"], f"{len(questions)} multiple-choice questions · answer key at the end")
    sec = tk.add_section(doc, "Questions")
    letters = "ABCDEF"
    for i, q in enumerate(questions, 1):
        sec["blocks"].append({"type": "h3", "text": f"{i}. {q['question']}"})
        sec["blocks"].append({"type": "bullets", "items": [f"{letters[j]}. {o}" for j, o in enumerate(q["options"])]})
    key = [["#", "Answer", "Explanation"]] + [[str(i), letters[q["answer"]] + ". " + q["options"][q["answer"]],
                                               tk.truncate_words(q.get("explanation", ""), 40)]
                                              for i, q in enumerate(questions, 1)]
    tk.add_section(doc, "Answer Key", table=key)
    path = ctx.out_path("quiz.pdf")
    render_pdf(doc, path, _meta(ctx))
    ctx.add_output(path, "Printable quiz with answer key")
    ctx.log(f"Quiz ready: {len(questions)} questions.")


# ====================================================================== flashcards
@plugin("flashcards", "Flashcards", "learning", "learning",
        "Makes flip-style flashcards (interactive), an Anki-ready CSV and a printable PDF.",
        icon="cards", keywords=["flashcard", "flashcards", "flash cards", "revision cards", "anki", "memorize"],
        params={"count": "int"}, example="Make 20 flashcards from the attached chapter")
def flashcards(ctx, count: int = 0):
    title, text = _knowledge(ctx)
    count = int(count or _count(ctx, 20))
    cards = []
    if ctx.llm.available():
        try:
            data = ctx.llm.complete_json(
                f"Create {count} high-quality flashcards (front: a term or short question; back: a concise answer "
                'under 40 words). Return JSON {"cards": [{"front": str, "back": str}]}.\n\nMATERIAL:\n<<<\n'
                + text[:24000] + "\n>>>", max_tokens=4000)
            for c in (data.get("cards") if isinstance(data, dict) else data) or []:
                if isinstance(c, dict) and str(c.get("front", "")).strip() and str(c.get("back", "")).strip():
                    cards.append({"front": str(c["front"]).strip(), "back": str(c["back"]).strip()})
        except LLMError as exc:
            ctx.log(f"AI engine failed ({exc}); using the offline generator.", "warn")
    if len(cards) < count // 2:
        cards += tk.make_flashcards(text, count - len(cards))
    cards = cards[:count]
    if not cards:
        raise PluginError("Could not find definitions or key terms in the material.")
    deck = {"title": f"Flashcards: {title}", "cards": cards}
    ctx.state["flashcards"] = deck
    ctx.add_text_output("flashcards.json", json.dumps(deck, ensure_ascii=False, indent=1), "Interactive flashcards",
                        "flashcards")
    buf = io.StringIO()
    w = csv.writer(buf)
    for c in cards:
        w.writerow([c["front"], c["back"]])
    ctx.add_text_output("flashcards-anki.csv", buf.getvalue(), "Anki import (CSV)", "sheet")
    doc = tk.new_doc(deck["title"], f"{len(cards)} cards")
    tk.add_section(doc, "Cards", table=[["Front", "Back"]] + [[c["front"], c["back"]] for c in cards])
    path = ctx.out_path("flashcards.pdf")
    render_pdf(doc, path, _meta(ctx))
    ctx.add_output(path, "Printable flashcards")
    ctx.log(f"{len(cards)} flashcards ready.")


# ====================================================================== mind map
def _tree(ctx):
    doc = ctx.state.get("doc")
    if doc and doc.get("sections"):
        root = doc["title"]
        branches = []
        for s in doc["sections"]:
            if not s.get("heading") or s["heading"].lower() in ("sources", "glossary", "frequently asked questions"):
                continue
            leaves = []
            for b in s["blocks"]:
                if b["type"] in ("bullets", "numbered"):
                    for item in b["items"]:
                        head = tk.strip_md(item).split(" — ")[0]
                        leaves.append(tk.truncate_words(head, 6))
                elif b["type"] == "p" and len(leaves) < 3:
                    leaves += [tk.title_case(k) for k in tk.keywords(b["text"], 3)]
            branches.append((tk.strip_md(s["heading"]), list(dict.fromkeys(leaves))[:3]))
        return root, branches[:8]
    title, text = _knowledge(ctx)
    sections = tk.split_plain_sections(text, 8)
    return title, [(h, [tk.title_case(k) for k in tk.keywords(body, 3)]) for h, body, _ in sections[:8]]


def _bezier(p0, p1, p2, steps=24):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]) for t in (i / steps for i in range(steps + 1))]


def render_mind_map(root: str, branches: list, path):
    W, H = 2400, 1500
    img = brand.gradient((W, H), (28, 40, 70), (12, 17, 31)).convert("RGBA")
    d = ImageDraw.Draw(img)
    cx, cy = W // 2, H // 2
    colors = [(201, 165, 92), (91, 140, 133), (184, 92, 92), (107, 127, 215), (217, 164, 65), (138, 106, 50),
              (122, 160, 110), (180, 120, 170)]

    def node(x, y, text, fnt, maxw, fill, outline, txt_color, pad=16, radius=18):
        lines = brand.wrap(d, text, fnt, maxw)[:3]
        lh = brand.text_height(d, "Ag", fnt) + 6
        tw = max(brand.text_width(d, ln, fnt) for ln in lines)
        bw, bh = tw + pad * 2, lh * len(lines) + pad * 2 - 6
        x0 = min(max(10, x - bw // 2), W - bw - 10)
        y0 = min(max(10, y - bh // 2), H - bh - 10)
        d.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), radius=radius, fill=fill, outline=outline, width=3)
        ty = y0 + pad - 4
        for ln in lines:
            d.text((x0 + (bw - brand.text_width(d, ln, fnt)) // 2, ty), ln, font=fnt, fill=txt_color)
            ty += lh
        return x0, y0, bw, bh

    n = max(1, len(branches))
    rx1, ry1 = W * 0.27, H * 0.30
    rx2, ry2 = W * 0.42, H * 0.42
    positions = []
    for i, (label, leaves) in enumerate(branches):
        ang = -math.pi / 2 + i * 2 * math.pi / n
        bx, by = cx + rx1 * math.cos(ang), cy + ry1 * math.sin(ang)
        col = colors[i % len(colors)]
        ctrl = (cx + rx1 * 0.45 * math.cos(ang + 0.25), cy + ry1 * 0.45 * math.sin(ang + 0.25))
        d.line(_bezier((cx, cy), ctrl, (bx, by)), fill=col + (255,), width=7, joint="curve")
        span = (2 * math.pi / n) * 0.62
        for j, leaf in enumerate(leaves):
            la = ang + (j - (len(leaves) - 1) / 2) * (span / max(1, len(leaves) - 1 if len(leaves) > 1 else 1))
            lx, ly = cx + rx2 * math.cos(la), cy + ry2 * math.sin(la)
            mid = ((bx + lx) / 2 + 20 * math.cos(la), (by + ly) / 2 + 20 * math.sin(la))
            d.line(_bezier((bx, by), mid, (lx, ly)), fill=col + (170,), width=3, joint="curve")
            positions.append(("leaf", lx, ly, leaf, col))
        positions.append(("branch", bx, by, label, col))
    for kind, x, y, text, col in positions:
        if kind == "leaf":
            node(int(x), int(y), text, brand.font(22), 230, (26, 37, 64, 255), col + (200,), (235, 228, 214),
                 pad=12, radius=14)
    for kind, x, y, text, col in positions:
        if kind == "branch":
            node(int(x), int(y), text, brand.font(27, True), 280, (20, 29, 49, 255), col + (255,), (245, 239, 226))
    node(cx, cy, root, brand.font(40, True, "serif"), 420, (201, 165, 92, 255), (234, 215, 161, 255), (15, 22, 38),
         pad=26, radius=30)
    brand.paste_logo(img, 70, (W - 110, H - 80), mark=True, opacity=0.85)
    img.convert("RGB").save(str(path), "PNG", optimize=True)


@plugin("mind_map", "Mind Map", "learning", "learning",
        "Draws a radial mind map of the topic's structure (PNG) plus an outline you can paste anywhere.",
        icon="mindmap", keywords=["mind map", "mindmap", "concept map", "diagram of", "map of ideas", "visual summary"],
        example="Create a mind map of machine learning")
def mind_map(ctx):
    root, branches = _tree(ctx)
    if not branches:
        raise PluginError("Not enough structure in the material to draw a mind map.")
    path = ctx.out_path(f"mind-map-{tk.slugify(root)}.png")
    render_mind_map(root, branches, path)
    ctx.add_output(path, "Mind map")
    outline = [f"# {root}"] + [ln for label, leaves in branches for ln in [f"- **{label}**"] + [f"  - {x}" for x in leaves]]
    ctx.add_text_output("mind-map-outline.md", "\n".join(outline) + "\n", "Mind-map outline", "markdown")
    ctx.log(f"Mind map drawn with {len(branches)} branches.")


# ====================================================================== audio
def _offline_dialogue(doc: dict, business: str) -> list:
    title = doc.get("title", "today's topic")
    lines = [("A", f"Welcome to the deep dive. Today we're unpacking {tk.strip_md(title)}."),
             ("B", "Great topic. Let's start with the big picture — what's the short version?")]
    sections = [s for s in doc.get("sections", []) if s.get("heading")]
    overview = next((s for s in sections if s["heading"].lower() in ("overview", "tl;dr", "introduction")), None)
    if overview:
        text = " ".join(tk.strip_md(b["text"]) for b in overview["blocks"] if b["type"] == "p")
        lines.append(("A", " ".join(tk.summarize(text, 3)) or text[:600]))
    for s in sections:
        if s is overview or s["heading"].lower() in ("glossary", "sources", "frequently asked questions", "timeline"):
            continue
        texts = []
        for b in s["blocks"]:
            if b["type"] == "p":
                texts.append(tk.strip_md(b["text"]))
            elif b["type"] in ("bullets", "numbered"):
                texts += [tk.strip_md(i) for i in b["items"]]
        if not texts:
            continue
        joined = " ".join(texts)
        key = tk.summarize(joined, 3) or texts[:2]
        lines.append(("B", f"Okay, so what should people understand about {tk.strip_md(s['heading']).lower()}?"))
        lines.append(("A", " ".join(key[:2])))
        if len(key) > 2:
            lines.append(("B", "And here's a detail I found interesting: " + key[2]))
        if len(lines) > 34:
            break
    lines += [("B", "That's a lot of ground. What's the one thing listeners should remember?"),
              ("A", "Understand the fundamentals first — the details make much more sense after that. Thanks for "
                    f"listening, and see you next time on the deep dive by {business}.")]
    return lines


def _dialogue(ctx, doc) -> list:
    if ctx.llm.available():
        try:
            data = ctx.llm.complete_json(
                "Write an engaging two-host podcast script ('deep dive' style, like NotebookLM audio overviews) "
                "explaining the material to a curious listener: natural back-and-forth, analogies, no filler, "
                "about 600-900 words. Host A explains, host B asks sharp questions. Return JSON "
                '{"lines": [{"speaker": "A"|"B", "text": str}]}.\n\nMATERIAL:\n<<<\n' +
                tk.doc_plain_text(doc)[:20000] + "\n>>>", max_tokens=4000, temperature=0.7)
            out = [(("B" if str(l.get("speaker", "A")).upper().startswith("B") else "A"), str(l.get("text", "")).strip())
                   for l in (data.get("lines") if isinstance(data, dict) else data) or [] if isinstance(l, dict)]
            out = [(s, t) for s, t in out if t]
            if len(out) >= 4:
                return out
        except LLMError as exc:
            ctx.log(f"AI script failed ({exc}); using the offline script writer.", "warn")
    return _offline_dialogue(doc, ctx.business)


def _join_wavs(paths, out_path, gap=0.28):
    params = None
    with wave.open(str(out_path), "wb") as out:
        for p in paths:
            with wave.open(str(p), "rb") as w:
                if params is None:
                    params = w.getparams()
                    out.setnchannels(params.nchannels)
                    out.setsampwidth(params.sampwidth)
                    out.setframerate(params.framerate)
                elif (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (params.nchannels, params.sampwidth,
                                                                              params.framerate):
                    continue
                out.writeframes(w.readframes(w.getnframes()))
                out.writeframes(b"\x00" * int(params.framerate * gap) * params.sampwidth * params.nchannels)


def encode_audio(wav_path, stem_path):
    """WAV -> MP3 (fallback M4A, then WAV)."""
    for ext, codec in ((".mp3", ["-c:a", "libmp3lame", "-b:a", "112k"]), (".m4a", ["-c:a", "aac", "-b:a", "128k"])):
        target = stem_path.with_suffix(ext)
        try:
            brand.run_ffmpeg(["-i", str(wav_path)] + codec + [str(target)])
            return target
        except RuntimeError:
            continue
    return wav_path


@plugin("audio_overview", "Audio Overview (Podcast)", "learning", "media",
        "Turns the material into a two-host ‘deep dive’ podcast with a transcript — like NotebookLM audio overviews.",
        icon="mic", keywords=["audio", "podcast", "audio overview", "listen", "narrate", "voice", "mp3", "speech"],
        example="Turn this PDF into a podcast I can listen to")
def audio_overview(ctx):
    doc = ctx.state.get("doc")
    if not doc:
        title, text = _knowledge(ctx)
        doc = tk.markdown_to_doc(text, title)
    lines = _dialogue(ctx, doc)
    transcript = "\n\n".join(f"**Host {'A' if s == 'A' else 'B'}:** {t}" for s, t in lines)
    ctx.add_text_output("podcast-transcript.md", f"# Audio overview: {doc['title']}\n\n{transcript}\n",
                        "Podcast transcript", "markdown")
    if brand.tts_engine() == "none":
        raise PluginError("No speech engine on this server. Install espeak-ng (Linux), or use macOS/Windows "
                          "built-in voices; the transcript was still created.")
    ctx.log(f"Recording {len(lines)} lines with the {brand.tts_engine()} voice engine…")
    segs = []
    for i, (spk, text) in enumerate(lines):
        ctx.check_cancel()
        seg = ctx.job_dir / f"_seg_{i:03d}.wav"
        if brand.synthesize(text, seg, "a" if spk == "A" else "b"):
            segs.append(seg)
    if not segs:
        raise PluginError("Speech synthesis failed on this server.")
    full = ctx.job_dir / "_podcast.wav"
    _join_wavs(segs, full)
    for s in segs:
        s.unlink(missing_ok=True)
    final = encode_audio(full, ctx.out_path("audio-overview.mp3"))
    if final != full:
        full.unlink(missing_ok=True)
    dur = brand.wav_duration(full) if final == full else None
    ctx.add_output(final, "Audio overview (two hosts)")
    ctx.state["audio_path"] = str(final)
    ctx.log("Audio overview ready" + (f" ({dur / 60:.1f} min)." if dur else "."))


# ====================================================================== video
def _narrations(ctx, slides, doc) -> list:
    if ctx.llm.available():
        try:
            outline = [{"slide": i, "title": s.get("title"), "points": s.get("bullets", [])} for i, s in enumerate(slides)]
            data = ctx.llm.complete_json(
                "Write voice-over narration for each slide of an explainer video (2-4 sentences each, warm, clear, no "
                'reading bullet symbols). Return JSON {"narration": [str, ...]} with exactly one entry per slide.\n'
                f"Slides: {json.dumps(outline, ensure_ascii=False)[:12000]}\nBackground:\n{tk.doc_plain_text(doc)[:8000]}",
                max_tokens=4000)
            nar = data.get("narration") if isinstance(data, dict) else data
            if isinstance(nar, list) and len(nar) == len(slides):
                return [str(x) for x in nar]
        except LLMError as exc:
            ctx.log(f"AI narration failed ({exc}); using slide text.", "warn")
    out = []
    for s in slides:
        if s["kind"] == "title":
            out.append(f"Welcome. This video overview covers {tk.strip_md(s['title'])}.")
        elif s["kind"] == "end":
            out.append(f"Thanks for watching. This overview was prepared by {ctx.business}.")
        elif s["kind"] == "table":
            out.append(f"Here is a quick reference table for {s['title']}.")
        else:
            pts = [tk.truncate_words(b, 18).rstrip(".…") + "." for b in s.get("bullets", [])[:3]]
            out.append(f"{s['title']}. " + " ".join(pts))
    return out


def _srt_time(t):
    h, rem = divmod(int(t * 1000), 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


@plugin("video_overview", "Video Overview", "learning", "media",
        "Produces a narrated explainer video (MP4) with branded slides, voice-over and subtitles.",
        icon="video", keywords=["video", "mp4", "explainer", "video overview", "animation", "youtube video", "reel"],
        params={"slides": "int"}, example="Make a video explaining blockchain for beginners")
def video_overview(ctx, slides: int = 0):
    doc = ctx.state.get("doc")
    if not doc:
        title, text = _knowledge(ctx)
        doc = tk.markdown_to_doc(text, title)
    plan = slides_from_doc(doc, int(slides or 10))
    plan = [s if s["kind"] != "table" else {"kind": "content", "title": s["title"],
                                             "bullets": [" — ".join(r[:2]) for r in s["table"][1:6]]} for s in plan]
    narration = _narrations(ctx, plan, doc)
    tts = brand.tts_engine()
    if tts == "none":
        ctx.log("No speech engine available — producing a silent video with on-screen text.", "warn")
    W, H = config.VIDEO_WIDTH, config.VIDEO_HEIGHT
    segments, srt, clock = [], [], 0.0
    total = len(plan)
    for i, (slide, text) in enumerate(zip(plan, narration)):
        ctx.check_cancel()
        ctx.log(f"Rendering scene {i + 1}/{total}")
        img = brand.render_slide(slide["title"], slide.get("bullets"), slide["kind"], i, total - 2,
                                 subtitle=slide.get("subtitle", ""), size=(W, H),
                                 signature=_meta(ctx)["signature"])
        png = ctx.job_dir / f"_scene_{i:02d}.png"
        img.save(png)
        wav = ctx.job_dir / f"_scene_{i:02d}.wav"
        has_audio = tts != "none" and brand.synthesize(text, wav, "a")
        dur = (brand.wav_duration(wav) + 0.9) if has_audio else max(4.0, min(9.0, len(text.split()) / 2.6))
        if not has_audio:
            brand.silent_wav(wav, dur)
        dur = round(max(3.0, dur), 2)
        seg = ctx.job_dir / f"_scene_{i:02d}.mp4"
        fade_out = max(0.1, dur - 0.45)
        brand.run_ffmpeg(["-loop", "1", "-framerate", "25", "-t", str(dur), "-i", str(png), "-i", str(wav),
                          "-filter_complex",
                          f"[0:v]fade=t=in:st=0:d=0.45,fade=t=out:st={fade_out}:d=0.45,format=yuv420p[v];"
                          f"[1:a]apad,atrim=0:{dur},aresample=44100[a]",
                          "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
                          "-crf", "23", "-r", "25", "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-t", str(dur), str(seg)])
        segments.append(seg)
        srt.append(f"{i + 1}\n{_srt_time(clock)} --> {_srt_time(clock + dur - 0.2)}\n{text}\n")
        clock += dur
        png.unlink(missing_ok=True)
        wav.unlink(missing_ok=True)
    listing = ctx.job_dir / "_concat.txt"
    listing.write_text("".join(f"file '{s.name}'\n" for s in segments), encoding="utf-8")
    out = ctx.out_path(f"video-{tk.slugify(doc['title'])}.mp4")
    brand.run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", "-movflags", "+faststart",
                      str(out)])
    for s in segments:
        s.unlink(missing_ok=True)
    listing.unlink(missing_ok=True)
    ctx.add_output(out, f"Video overview · {clock / 60:.1f} min")
    ctx.add_text_output("video-subtitles.srt", "\n".join(srt), "Subtitles (SRT)", "text")
    ctx.state["video_path"] = str(out)
    ctx.log(f"Video ready: {total} scenes, {clock:.0f} seconds.")
