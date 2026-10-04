"""Social media, delivery and automation plugins: post designer, content
calendar, Instagram publishing, e-mail, messengers and the scheduler."""
import datetime as dt
import html
import json
import mimetypes
import re
import smtplib
import time
from email.message import EmailMessage
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageOps

import automations
import brand
import config
import db
import industries
import security
import textkit as tk
from llm import LLMError
from registry import PluginError, plugin


def _industry(ctx):
    p = ctx.profile
    return industries.detect(" ".join([p.get("industry", ""), p.get("description", ""), ctx.problem]))


def _auto_state(ctx) -> dict:
    return ctx.state.setdefault("auto_state", {})


def _hashtags(ctx, ind, extra=()):
    tags = list(dict.fromkeys(list(extra) + ind["hashtags"]))
    city = (ctx.profile.get("city") or "").strip()
    if city:
        tags.append("#" + re.sub(r"\W", "", city.title()))
    biz = re.sub(r"\W", "", ctx.business.title())
    if biz:
        tags.append("#" + biz)
    return " ".join(tags[:12])


def _cta(ctx) -> str:
    p = ctx.profile
    bits = []
    if p.get("phone"):
        bits.append(f"📞 {p['phone']}")
    if p.get("city"):
        bits.append(f"📍 {p['city']}")
    if p.get("website"):
        bits.append(f"🌐 {p['website']}")
    return " · ".join(bits) or "Follow us for more and share this with a friend who needs it."


# ====================================================================== post image
def _font_fit(draw, text, maxw, maxh, start, minimum, family="serif"):
    return brand.fit_text(draw, text, maxw, maxh, start=start, minimum=minimum, family=family, spacing=1.12)


def design_post(headline: str, subtext: str, business: str, handle: str, accent_hex: str, variant: int,
                photo=None, size=(1080, 1350)) -> Image.Image:
    W, H = size
    accent = brand.hex_to_rgb(accent_hex, brand.GOLD)
    if photo is not None:
        img = ImageOps.fit(ImageOps.exif_transpose(photo).convert("RGB"), (W, H), Image.LANCZOS, centering=(0.5, 0.4))
        shade = Image.new("L", (W, H), 0)
        sd = ImageDraw.Draw(shade)
        for y in range(H):
            t = max(0.0, (y - H * 0.42) / (H * 0.58))
            sd.line([(0, y), (W, y)], fill=int(235 * t ** 1.3))
        img = Image.composite(Image.new("RGB", (W, H), (8, 8, 7)), img, shade)
        d = ImageDraw.Draw(img)
        fnt, lines, size_ = _font_fit(d, headline, W - 140, 330, 84, 40)
        y = H - 170 - len(lines) * int(size_ * 1.12)
        d.rectangle((70, y - 34, 170, y - 28), fill=accent)
        for ln in lines:
            d.text((70, y), ln, font=fnt, fill=(250, 246, 236))
            y += int(size_ * 1.12)
        bf = brand.font(30, True)
        d.text((70, H - 110), business.upper(), font=bf, fill=accent)
        if handle:
            d.text((70, H - 68), handle, font=brand.font(26), fill=(220, 214, 200))
        return img
    v = variant % 3
    if v == 0:  # dark luxury
        bg = brand.gradient((W, H), tuple(int(c * 0.22) for c in accent), (10, 10, 9))
        fg, sub_c, line_c = (247, 242, 230), (214, 205, 186), accent
    elif v == 1:  # light editorial
        bg = brand.gradient((W, H), (250, 247, 240), (236, 228, 212))
        fg, sub_c = (22, 20, 17), (80, 74, 64)
        line_c = tuple(int(c * 0.62) for c in accent) if brand.luminance(accent) > 0.45 else accent
    else:  # bold colour block
        bg = brand.gradient((W, H), accent, tuple(int(c * 0.55) for c in accent))
        dark_text = brand.luminance(accent) > 0.6
        fg = (18, 17, 15) if dark_text else (255, 252, 245)
        sub_c = (40, 36, 30) if dark_text else (240, 234, 220)
        line_c = fg
    img = bg.convert("RGBA")
    deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(deco)
    dd.ellipse((W * 0.45, -H * 0.18, W * 1.35, H * 0.55), outline=(*line_c, 70), width=3)
    dd.ellipse((W * 0.58, -H * 0.06, W * 1.22, H * 0.43), outline=(*line_c, 40), width=2)
    for i in range(14):
        for j in range(4):
            dd.ellipse((70 + i * 22, H - 300 + j * 22, 74 + i * 22, H - 296 + j * 22), fill=(*line_c, 60))
    img.alpha_composite(deco)
    d = ImageDraw.Draw(img)
    d.text((80, 90), business.upper(), font=brand.font(30, True), fill=line_c)
    fnt, lines, size_ = _font_fit(d, headline, W - 170, 520, 104, 48)
    y = 260
    for ln in lines:
        d.text((80, y), ln, font=fnt, fill=fg)
        y += int(size_ * 1.12)
    d.rectangle((80, y + 24, 200, y + 31), fill=line_c)
    y += 70
    if subtext:
        sf, slines, ss = _font_fit(d, subtext, W - 170, H - y - 330, 40, 26, family="sans")
        for ln in slines:
            d.text((80, y), ln, font=sf, fill=sub_c)
            y += int(ss * 1.3)
    pill = "Save this post ✦" if brand.font_path("sans") else "Save this post"
    pf = brand.font(28, True)
    pw = brand.text_width(d, pill, pf) + 56
    d.rounded_rectangle((80, H - 170, 80 + pw, H - 104), radius=33, outline=line_c, width=3)
    d.text((108, H - 157), pill, font=pf, fill=fg)
    if handle:
        hf = brand.font(28)
        d.text((W - 80 - brand.text_width(d, handle, hf), H - 152), handle, font=hf, fill=sub_c)
    return img.convert("RGB")


@plugin("social_post_designer", "Social Post Designer", "social", "content",
        "Creates ready-to-post social media posts: a designed 4:5 image (or your own photo, branded) plus caption and "
        "hashtags tailored to your business. Rotates fresh ideas on every scheduled run.",
        icon="spark", keywords=["instagram", "post", "social media", "caption", "facebook post", "insta", "reel cover",
                                "creative", "poster", "banner"],
        params={"headline": "string", "count": "int"},
        example="Create an Instagram post for my automobile business about monsoon car care")
def social_post_designer(ctx, headline: str = "", count: int = 1):
    key, ind = _industry(ctx)
    st = _auto_state(ctx)
    idx = int(st.get("post_index", 0))
    recent = st.get("recent", [])[-20:]
    handle = ctx.profile.get("instagram", "").strip()
    handle = ("@" + handle.lstrip("@")) if handle else ""
    accent = ctx.profile.get("brand_color") or ind["color"]
    topic = ctx.topic()
    post = None
    if ctx.llm.available():
        try:
            data = ctx.llm.complete_json(
                f"Create one Instagram post for this business. Context: {ctx.business}; industry {ind['label']}; "
                f"profile {ctx.profile.get('description', '')}; voice {ctx.profile.get('brand_voice', 'friendly expert')}. "
                f"User request: {ctx.problem}\nAvoid repeating these recent headlines: {recent}. "
                'Return JSON {"headline": str (max 8 words), "subtext": str (max 20 words), '
                '"caption": str (70-140 words, helpful, ends with a call to action, max 3 emojis), '
                '"hashtags": [str] (8-12, each starting with #)}. No false claims, prices or guarantees.',
                max_tokens=900, temperature=0.8)
            if isinstance(data, dict) and data.get("headline") and data.get("caption"):
                tags = " ".join(t if t.startswith("#") else "#" + t for t in (data.get("hashtags") or [])[:12])
                post = {"headline": str(data["headline"])[:80], "subtext": str(data.get("subtext", ""))[:160],
                        "caption": str(data["caption"]).strip(), "hashtags": tags or _hashtags(ctx, ind)}
        except LLMError as exc:
            ctx.log(f"AI caption failed ({exc}); using the content bank.", "warn")
    if post is None:
        ideas = ind["ideas"]
        if re.search(r"\bquotes?\b|motivat|inspir", ctx.problem.lower()) and not headline:
            q, author = industries.QUOTES[idx % len(industries.QUOTES)]
            post = {"headline": q, "subtext": f"— {author}",
                    "caption": f"“{q}” — {author}\n\nWhat does this mean to you? Tell us in the comments.\n\n{_cta(ctx)}",
                    "hashtags": _hashtags(ctx, ind, ["#Motivation", "#QuoteOfTheDay", "#Inspiration"])}
            h = body = None
        elif headline:
            h, body = headline, ctx.state.get("caption") or (tk.summary_paragraph(ctx.source_text(), 2) or
                                                              ideas[idx % len(ideas)][1])
        elif topic and not ctx.automation and ctx.source_text().strip():
            h, body = tk.title_case(topic), tk.summary_paragraph(ctx.source_text(), 2)
        else:
            h, body = ideas[idx % len(ideas)]
        if post is None:
            post = {"headline": h, "subtext": tk.truncate_words(body, 18),
                    "caption": f"{h}\n\n{body}\n\n{_cta(ctx)}", "hashtags": _hashtags(ctx, ind)}
    library = [f for f in ctx.inputs if Path(f["name"]).suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
    photo = None
    if library:
        chosen = library[idx % len(library)]
        photo = Image.open(chosen["path"])
        ctx.log(f"Using your photo “{chosen['name']}” ({idx % len(library) + 1} of {len(library)} in rotation).")
    img = design_post(post["headline"], post["subtext"], ctx.business, handle, accent, idx, photo)
    if photo is not None:
        photo.close()
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    path = ctx.out_path(f"post-{stamp}.jpg")
    img.save(path, "JPEG", quality=92, optimize=True, progressive=True)
    rec = ctx.add_output(path, "Post image (1080×1350, Instagram-ready JPEG)")
    caption_full = f"{post['caption']}\n\n{post['hashtags']}".strip()
    ctx.add_text_output(f"caption-{stamp}.txt", caption_full, "Caption + hashtags", "text")
    ctx.state["post"] = {"image_file_id": rec.get("file_id"), "image_path": str(path), "caption": caption_full,
                         "headline": post["headline"]}
    st["post_index"] = idx + 1
    st["recent"] = (recent + [post["headline"]])[-30:]
    ctx.log(f"Post designed: “{post['headline']}”.")


# ====================================================================== calendar
@plugin("content_calendar", "Content Calendar", "social", "content",
        "Plans 7–90 days of social content (ideas, captions, hashtags, formats, posting times) as an Excel calendar.",
        icon="calendar", keywords=["content calendar", "content plan", "posting schedule", "social media plan",
                                   "30 days of posts", "month of content"],
        params={"days": "int"}, example="Plan 30 days of Instagram content for my car service centre")
def content_calendar(ctx, days: int = 0):
    from plg_docs import write_sheets
    m = re.search(r"(\d{1,2})\s*(?:-|\s)?days?", ctx.problem.lower())
    days = int(days or (m.group(1) if m else 30))
    days = max(7, min(90, days))
    key, ind = _industry(ctx)
    tz = automations.tzinfo(ctx.profile.get("timezone"))
    start = dt.datetime.now(tz).date() + dt.timedelta(days=1)
    pillars = ["Tip / How-to", "Behind the scenes", "Product / Service spotlight", "Customer question",
               "Myth vs fact", "Offer / Announcement", "Engagement (poll / question)"]
    formats = ["Carousel", "Reel", "Static post", "Carousel", "Reel", "Static post", "Story + poll"]
    rows = []
    ai_rows = []
    if ctx.llm.available():
        try:
            data = ctx.llm.complete_json(
                f"Plan {min(days, 31)} days of Instagram content for {ctx.business} ({ind['label']}). "
                f"Request: {ctx.problem}. Return JSON {{\"days\": [{{\"idea\": str, \"caption\": str (40-80 words), "
                '"format": str}}]}}. Practical, varied, no fake claims.', max_tokens=6000, temperature=0.8)
            ai_rows = [d for d in (data.get("days") if isinstance(data, dict) else []) or [] if isinstance(d, dict)]
        except LLMError as exc:
            ctx.log(f"AI planning failed ({exc}); using the content bank.", "warn")
    for i in range(days):
        day = start + dt.timedelta(days=i)
        pillar = pillars[i % len(pillars)]
        if i < len(ai_rows):
            idea, caption, fmt = ai_rows[i].get("idea", ""), ai_rows[i].get("caption", ""), ai_rows[i].get("format", "")
        else:
            h, body = ind["ideas"][i % len(ind["ideas"])]
            idea, caption, fmt = h, body, formats[i % len(formats)]
        best = "19:00" if day.weekday() < 5 else "11:00"
        rows.append([day.strftime("%d-%m-%Y"), day.strftime("%A"), pillar, idea, caption, fmt or formats[i % 7],
                     _hashtags(ctx, ind), best, "Planned"])
    header = ["Date", "Day", "Content pillar", "Post idea", "Caption draft", "Format", "Hashtags", "Best time", "Status"]
    path = ctx.out_path(f"content-calendar-{days}-days.xlsx")
    write_sheets(path, [{"name": "Calendar", "header": header, "rows": rows}], ctx)
    ctx.add_output(path, f"{days}-day content calendar")
    doc = tk.new_doc(f"{days}-Day Content Calendar — {ctx.business}", f"Starting {start:%d %b %Y}")
    tk.add_section(doc, "Calendar", table=[["Date", "Pillar", "Idea", "Format"]] + [[r[0], r[2], r[3], r[5]] for r in rows])
    ctx.state["doc"] = doc
    ctx.add_text_output("content-calendar.md", tk.doc_to_markdown(doc), "Calendar preview", "markdown")
    ctx.log(f"Planned {days} days of content starting {start:%d %b}.")


# ====================================================================== Instagram
def _ig_error(r) -> str:
    try:
        err = r.json().get("error", {})
        return f"{err.get('message', r.text[:200])} (code {err.get('code', r.status_code)})"
    except ValueError:
        return f"HTTP {r.status_code}: {r.text[:200]}"


def instagram_publish(cfg: dict, image_url: str, caption: str, log=lambda *_: None) -> dict:
    host = config.IG_GRAPH_HOST
    base = f"https://{host}/{config.IG_GRAPH_VERSION}"
    uid, token = str(cfg.get("ig_user_id", "")).strip(), str(cfg.get("access_token", "")).strip()
    if not uid.isdigit() or not token:
        raise PluginError("Instagram connection is incomplete — add your Instagram user ID and access token in Connections.")
    with httpx.Client(timeout=60) as c:
        r = c.post(f"{base}/{uid}/media", data={"image_url": image_url, "caption": caption[:2200],
                                                "access_token": token})
        if r.status_code >= 400:
            raise PluginError("Instagram rejected the media: " + _ig_error(r))
        creation = r.json().get("id")
        for _ in range(24):
            s = c.get(f"{base}/{creation}", params={"fields": "status_code", "access_token": token})
            status = s.json().get("status_code") if s.status_code < 400 else "ERROR"
            if status == "FINISHED":
                break
            if status in ("ERROR", "EXPIRED"):
                raise PluginError(f"Instagram could not process the image (status {status}).")
            log("Waiting for Instagram to process the image…")
            time.sleep(5)
        r = c.post(f"{base}/{uid}/media_publish", data={"creation_id": creation, "access_token": token})
        if r.status_code >= 400:
            raise PluginError("Instagram publish failed: " + _ig_error(r))
        media_id = r.json().get("id")
        link = ""
        p = c.get(f"{base}/{media_id}", params={"fields": "permalink", "access_token": token})
        if p.status_code < 400:
            link = p.json().get("permalink", "")
    return {"media_id": media_id, "permalink": link}


@plugin("instagram_publisher", "Instagram Publisher", "delivery", "deliver",
        "Publishes the designed post to your Instagram Business/Creator account through Instagram's official "
        "publishing API (no passwords, no scraping).",
        icon="instagram", keywords=["instagram", "insta", "ig", "upload to instagram", "post on instagram",
                                    "publish on instagram"],
        needs=["vault:instagram", "public_url"], side_effect=True, ai_enhanced=False,
        example="Every day at 8 am post an automobile tip on my Instagram")
def instagram_publisher(ctx):
    cfg = ctx.secret("instagram")
    if not cfg:
        raise PluginError("Instagram is not connected. Open Connections → Instagram and add your account ID + access token.")
    base = config.PUBLIC_BASE_URL
    if not base.startswith("https://") or any(h in base for h in ("localhost", "127.0.0.1", "0.0.0.0")):
        raise PluginError("Instagram must download the image from a public HTTPS address. Set PUBLIC_BASE_URL "
                          "(e.g. https://plugins.yourdomain.com) and deploy the server publicly.")
    post = ctx.state.get("post") or {}
    fid = post.get("image_file_id")
    if not fid:
        imgs = [p for p in ctx.produced([".jpg", ".jpeg"]) if p.get("file_id")]
        if not imgs:
            raise PluginError("No JPEG image to publish — add the Social Post Designer step.")
        fid = imgs[-1]["file_id"]
    caption = post.get("caption") or ctx.state.get("caption") or ""
    token = security.new_token(24)
    db.execute("UPDATE files SET public_token=?, public_expires=? WHERE id=? AND user_id=?",
               (token, time.time() + 3600, fid, ctx.user["id"]))
    try:
        ctx.log("Sending the post to Instagram…")
        res = instagram_publish(cfg, f"{base}/p/{token}.jpg", caption, ctx.log)
    finally:
        db.execute("UPDATE files SET public_token=NULL, public_expires=NULL WHERE id=?", (fid,))
    ctx.state["instagram"] = res
    ctx.log("Published on Instagram ✓ " + (res.get("permalink") or f"(media id {res.get('media_id')})"))


# ====================================================================== E-mail
def send_email(cfg: dict, to: list, subject: str, text: str, attachments=(), reply_to: str = ""):
    host = str(cfg.get("host", "")).strip()
    port = int(cfg.get("port") or 587)
    mode = (cfg.get("security") or ("ssl" if port == 465 else "starttls")).lower()
    if not host or not cfg.get("username"):
        raise PluginError("E-mail (SMTP) is not configured. Open Connections → E-mail.")
    msg = EmailMessage()
    sender = cfg.get("from_email") or cfg["username"]
    msg["From"] = f"{cfg.get('from_name')} <{sender}>" if cfg.get("from_name") else sender
    if len(to) <= 3:
        msg["To"] = ", ".join(to)
    else:
        msg["To"] = sender
        msg["Bcc"] = ", ".join(to)  # keep recipients private from each other
    msg["Subject"] = subject[:200]
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(text)
    paras = "".join(f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>" for p in text.split("\n\n"))
    msg.add_alternative(f"<html><body style=\"font-family:Arial,sans-serif;line-height:1.6;color:#1a1814\">{paras}"
                        "</body></html>", subtype="html")
    total = 0
    for path in attachments:
        path = Path(path)
        size = path.stat().st_size
        if total + size > 20 * 1024 * 1024:
            continue
        total += size
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)
    try:
        server = security.smtp_connect(host, port, mode)
    except security.UnsafeURL as exc:
        raise PluginError(str(exc))
    except (OSError, smtplib.SMTPException) as exc:
        raise PluginError(f"Could not connect to {host}:{port} — {type(exc).__name__}: {exc}")
    try:
        server.login(cfg["username"], cfg.get("password", ""))
        server.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise PluginError("SMTP login failed. For Gmail/Outlook use an app password, not your normal password.")
    finally:
        try:
            server.quit()
        except Exception:
            pass


@plugin("email_sender", "E-mail Sender", "delivery", "deliver",
        "Sends e-mails with the generated files attached through your own mailbox (SMTP — Gmail, Outlook, Zoho, any "
        "provider).",
        icon="mail", keywords=["send email", "email it", "mail it", "send to", "email to", "@"],
        needs=["vault:smtp"], side_effect=True, params={"to": "list"}, ai_enhanced=False,
        example="Write a thank-you email and send it to client@example.com")
def email_sender(ctx, to=None):
    cfg = ctx.secret("smtp")
    if not cfg:
        raise PluginError("E-mail is not connected. Open Connections → E-mail and add your mailbox.")
    email = ctx.state.get("email") or {}
    recipients = [r for r in (to or email.get("to") or re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", ctx.problem))
                  if security.valid_email(r)]
    recipients = list(dict.fromkeys(r.lower() for r in recipients))[:20]
    if not recipients:
        raise PluginError("No recipient e-mail address found. Include it in your problem, e.g. “send to ravi@example.com”.")
    doc = ctx.state.get("doc") or {}
    subject = email.get("subject") or doc.get("title") or "Files from " + ctx.business
    body = email.get("body")
    if not body:
        summary = ""
        for s in doc.get("sections", []):
            for b in s.get("blocks", []):
                if b["type"] == "p":
                    summary = tk.strip_md(b["text"])
                    break
            if summary:
                break
        body = f"Hello,\n\n{summary or 'Please find the requested files attached.'}\n\nBest regards,\n" \
               f"{ctx.user.get('name', '')}\n{ctx.business}"
    attach = [p["path"] for p in ctx.produced() if Path(p["name"]).suffix.lower() in
              (".pdf", ".docx", ".pptx", ".xlsx", ".jpg", ".png", ".mp3", ".mp4", ".zip", ".csv", ".html")]
    if not attach:
        attach = [f["path"] for f in ctx.inputs]
    if len(recipients) > 1:
        body += f"\n\n—\nYou are receiving this because you are in contact with {ctx.business}. " \
                "Reply “unsubscribe” and we will not e-mail you again."
    ctx.log(f"Sending to {len(recipients)} recipient(s) with {len(attach)} attachment(s)…")
    send_email(cfg, recipients, subject, body, attach, reply_to=ctx.user.get("email", ""))
    ctx.log(f"E-mail sent ✓ to {', '.join(recipients[:5])}{'…' if len(recipients) > 5 else ''}")


# ====================================================================== Messengers
@plugin("messenger", "Telegram / Discord / Slack / Webhook", "delivery", "deliver",
        "Delivers results (text plus the main file) to your Telegram bot, Discord or Slack channel, or any webhook.",
        icon="send", keywords=["telegram", "discord", "slack", "webhook", "notify me", "send me", "alert"],
        needs=["vault:messenger"], side_effect=True, ai_enhanced=False,
        example="Every morning send me a motivational quote image on Telegram")
def messenger(ctx):
    cfg = ctx.secret("messenger")
    if not cfg:
        raise PluginError("No messenger connected. Open Connections → Messengers and add Telegram, Discord, Slack or a webhook.")
    low = ctx.problem.lower()
    wanted = [k for k in ("telegram", "discord", "slack", "webhook") if k in low] or ["telegram", "discord", "slack",
                                                                                      "webhook"]
    post = ctx.state.get("post") or {}
    doc = ctx.state.get("doc") or {}
    text = post.get("caption") or (ctx.state.get("email") or {}).get("body") or ""
    if not text and doc:
        first = next((tk.strip_md(b["text"]) for s in doc.get("sections", []) for b in s["blocks"] if b["type"] == "p"), "")
        text = f"{doc.get('title', '')}\n\n{first}"
    if not text:
        text = f"✅ InEra finished: {ctx.problem[:200]}"
    files = [p for p in ctx.produced() if Path(p["name"]).suffix.lower() in
             (".jpg", ".png", ".pdf", ".mp4", ".mp3", ".docx", ".pptx", ".xlsx")]
    main = Path(post["image_path"]) if post.get("image_path") else (Path(files[0]["path"]) if files else None)
    sent = []
    with httpx.Client(timeout=60) as c:
        if "telegram" in wanted and cfg.get("telegram_bot_token") and cfg.get("telegram_chat_id"):
            tok = cfg["telegram_bot_token"].strip()
            if not re.fullmatch(r"\d+:[\w-]{20,}", tok):
                raise PluginError("Telegram bot token looks invalid.")
            api = f"https://api.telegram.org/bot{tok}"
            chat = str(cfg["telegram_chat_id"]).strip()
            if main and main.suffix.lower() in (".jpg", ".png") and main.stat().st_size < 10e6:
                r = c.post(f"{api}/sendPhoto", data={"chat_id": chat, "caption": text[:1024]},
                           files={"photo": (main.name, main.read_bytes())})
            elif main and main.stat().st_size < 50e6:
                r = c.post(f"{api}/sendDocument", data={"chat_id": chat, "caption": text[:1024]},
                           files={"document": (main.name, main.read_bytes())})
            else:
                r = c.post(f"{api}/sendMessage", data={"chat_id": chat, "text": text[:4096]})
            if r.status_code >= 400:
                raise PluginError(f"Telegram error: {r.text[:200]}")
            sent.append("Telegram")
        if "discord" in wanted and cfg.get("discord_webhook"):
            url = cfg["discord_webhook"].strip()
            if not re.match(r"^https://(?:discord(?:app)?\.com)/api/webhooks/\d+/[\w-]+$", url):
                raise PluginError("Discord webhook URL looks invalid.")
            payload = {"content": text[:1900]}
            if main and main.stat().st_size < 9.5e6:
                r = c.post(url, data={"payload_json": json.dumps(payload)},
                           files={"file": (main.name, main.read_bytes())})
            else:
                r = c.post(url, json=payload)
            if r.status_code >= 400:
                raise PluginError(f"Discord error: {r.text[:200]}")
            sent.append("Discord")
        if "slack" in wanted and cfg.get("slack_webhook"):
            url = cfg["slack_webhook"].strip()
            if not url.startswith("https://hooks.slack.com/"):
                raise PluginError("Slack webhook URL must start with https://hooks.slack.com/")
            r = c.post(url, json={"text": text[:3500]})
            if r.status_code >= 400:
                raise PluginError(f"Slack error: {r.text[:200]}")
            sent.append("Slack")
    if "webhook" in wanted and cfg.get("webhook_url"):
        r = security.safe_request("POST", cfg["webhook_url"].strip(), json={
            "text": text, "problem": ctx.problem, "files": [p["name"] for p in files], "job_id": ctx.job_id})
        if r.status_code >= 400:
            raise PluginError(f"Webhook returned HTTP {r.status_code}")
        sent.append("Webhook")
    if not sent:
        raise PluginError("The requested messenger isn't configured in Connections.")
    ctx.log("Delivered ✓ via " + ", ".join(sent))


# ====================================================================== Scheduler
@plugin("automation_scheduler", "Automation Scheduler", "delivery", "schedule",
        "Turns the plan into a recurring automation (daily, weekly, monthly, every N hours or once) that runs in the "
        "background on its own.",
        icon="clock", keywords=["every day", "daily", "weekly", "every morning", "schedule", "regularly", "automate",
                                "every monday", "at 8", "o'clock", "every week", "monthly"],
        ai_enhanced=False, example="Every Monday at 9 am email me a summary of a trending tech topic")
def automation_scheduler(ctx):
    schedule = ctx.plan.get("schedule")
    if not schedule:
        raise PluginError("No schedule found. Say when, e.g. “every day at 8 am” or “every Monday at 6 pm”.")
    if ctx.automation:
        ctx.log("Running as part of an existing automation.")
        return
    steps = [s for s in ctx.plan.get("steps", []) if s["plugin"] != "automation_scheduler"]
    from registry import PLUGINS
    has_side = any(PLUGINS[s["plugin"]].side_effect for s in steps if s["plugin"] in PLUGINS)
    approved = (not has_side) or bool(ctx.profile.get("auto_approve"))
    input_ids = [f["id"] for f in ctx.inputs]
    try:
        auto = automations.create(ctx.user, ctx.problem, ctx.plan, schedule, input_ids, approved)
    except ValueError as exc:
        raise PluginError(str(exc))
    ctx.state["automation_id"] = auto["id"]
    tz = automations.tzinfo(auto["timezone"])
    nxt = dt.datetime.fromtimestamp(auto["next_run_at"], tz).strftime("%a %d %b %Y, %H:%M") if auto["next_run_at"] else "—"
    ctx.log(f"Automation created: {auto['schedule_text']} ({auto['timezone']}). Next run: {nxt}.")
    if not approved:
        ctx.log("It will publish/send on your behalf, so it waits for your one-time approval in Automations.", "warn")
