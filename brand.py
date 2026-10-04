"""Brand system and media toolchain: InEra colours, logo, fonts, image
helpers, text-to-speech engines and the ffmpeg binary."""
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import wave
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import config

# Refuse decompression bombs: Pillow raises an error above twice this many pixels.
Image.MAX_IMAGE_PIXELS = 50_000_000

LOGO = config.APP_DIR / "logo.png"
LOGO_MARK = config.APP_DIR / "logo_mark.png"

INK = (15, 22, 38)
INK_2 = (26, 37, 64)
GOLD = (201, 165, 92)
GOLD_LIGHT = (234, 215, 161)
GOLD_DARK = (138, 106, 50)
CREAM = (245, 239, 226)
MUTED = (163, 154, 136)
HEX_GOLD = "#C9A55C"
HEX_INK = "#0F1626"

# --------------------------------------------------------------- fonts
_FONT_CANDIDATES = {
    ("sans", False): ["DejaVuSans.ttf", "Inter-Regular.otf", "Poppins-Regular.ttf", "LiberationSans-Regular.ttf",
                      "FreeSans.ttf", "arial.ttf", "Arial.ttf", "Helvetica.ttc", "segoeui.ttf"],
    ("sans", True): ["DejaVuSans-Bold.ttf", "Inter-Bold.otf", "Poppins-Bold.ttf", "LiberationSans-Bold.ttf",
                     "FreeSansBold.ttf", "arialbd.ttf", "Arial Bold.ttf", "segoeuib.ttf"],
    ("serif", False): ["DejaVuSerif.ttf", "LiberationSerif-Regular.ttf", "FreeSerif.ttf", "georgia.ttf",
                       "Georgia.ttf", "times.ttf", "Times New Roman.ttf"],
    ("serif", True): ["DejaVuSerif-Bold.ttf", "LiberationSerif-Bold.ttf", "FreeSerifBold.ttf", "georgiab.ttf",
                      "Georgia Bold.ttf", "timesbd.ttf"],
}
_FONT_DIRS = ["/usr/share/fonts", "/usr/local/share/fonts", str(Path.home() / ".fonts"),
              "/Library/Fonts", "/System/Library/Fonts", "/System/Library/Fonts/Supplemental",
              os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")]


@lru_cache(maxsize=None)
def _font_index() -> dict:
    index = {}
    for d in _FONT_DIRS:
        if not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for f in files:
                if f.lower().endswith((".ttf", ".otf", ".ttc")):
                    index.setdefault(f.lower(), os.path.join(root, f))
    return index


@lru_cache(maxsize=None)
def font_path(family: str = "sans", bold: bool = False):
    idx = _font_index()
    for name in _FONT_CANDIDATES[(family, bold)]:
        if name.lower() in idx:
            return idx[name.lower()]
    if family == "serif":
        return font_path("sans", bold)
    return None


@lru_cache(maxsize=256)
def font(size: int, bold: bool = False, family: str = "sans"):
    path = font_path(family, bold)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def text_width(draw, text, fnt) -> int:
    l, t, r, b = draw.textbbox((0, 0), text, font=fnt)
    return r - l


def text_height(draw, text, fnt) -> int:
    l, t, r, b = draw.textbbox((0, 0), text or "Ag", font=fnt)
    return b - t


def wrap(draw, text: str, fnt, max_width: int) -> list:
    lines = []
    for para in (text or "").split("\n"):
        line = ""
        for word in para.split():
            trial = (line + " " + word).strip()
            if text_width(draw, trial, fnt) <= max_width or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def fit_text(draw, text, max_width, max_height, start=72, minimum=22, bold=True, family="sans", spacing=1.2):
    size = start
    while size >= minimum:
        fnt = font(size, bold, family)
        lines = wrap(draw, text, fnt, max_width)
        h = len(lines) * int(size * spacing)
        if h <= max_height:
            return fnt, lines, size
        size -= 2
    fnt = font(minimum, bold, family)
    lines = wrap(draw, text, fnt, max_width)
    max_lines = max(1, int(max_height // (minimum * spacing)))
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".,;: ") + "…"
    return fnt, lines, minimum


def hex_to_rgb(value: str, default=GOLD):
    try:
        v = (value or "").lstrip("#")
        if len(v) == 3:
            v = "".join(c * 2 for c in v)
        return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return default


def luminance(rgb) -> float:
    return (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255


def gradient(size, top, bottom, diagonal=False) -> Image.Image:
    w, h = size
    base = Image.new("RGB", (1, 256))
    for y in range(256):
        t = y / 255
        base.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    img = base.resize((w, h), Image.BICUBIC)
    if diagonal:
        big = base.resize((int((w + h) * 1.0), int((w + h) * 1.0)), Image.BICUBIC).rotate(35, resample=Image.BICUBIC)
        left = (big.width - w) // 2
        top_ = (big.height - h) // 2
        img = big.crop((left, top_, left + w, top_ + h))
    return img


def gold_rule(draw, xy, width=3):
    x0, y0, x1, y1 = xy
    draw.rectangle((x0, y0, x1, y0 + width), fill=GOLD)


def paste_logo(canvas: Image.Image, box_width: int, xy, mark: bool = False, opacity: float = 1.0):
    src = LOGO_MARK if mark else LOGO
    if not src.exists():
        return
    logo = Image.open(src).convert("RGBA")
    ratio = box_width / logo.width
    logo = logo.resize((box_width, max(1, int(logo.height * ratio))), Image.LANCZOS)
    if opacity < 1:
        alpha = logo.getchannel("A").point(lambda a: int(a * opacity))
        logo.putalpha(alpha)
    if canvas.mode != "RGBA":
        canvas.paste(logo, xy, logo)
    else:
        canvas.alpha_composite(logo, xy)


def vignette(img: Image.Image, strength: float = 0.45) -> Image.Image:
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse((-w * 0.2, -h * 0.25, w * 1.2, h * 1.25), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(min(w, h) // 5))
    dark = Image.new("RGB", (w, h), (0, 0, 0))
    return Image.composite(img, Image.blend(img, dark, strength), mask)


# --------------------------------------------------------------- slides
def render_slide(title: str, bullets=None, kind: str = "content", index: int = 0, total: int = 0,
                 subtitle: str = "", size=None, signature: bool = True) -> Image.Image:
    """Branded 16:9 slide image used by the video plugin."""
    W, H = size or (config.VIDEO_WIDTH, config.VIDEO_HEIGHT)
    s = W / 1280
    img = gradient((W, H), (30, 43, 74), (12, 17, 31))
    img = vignette(img, 0.35).convert("RGBA")
    deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(deco).ellipse((int(W * 0.66), int(-H * 0.45), int(W * 1.40), int(H * 0.62)),
                                 outline=(201, 165, 92, 34), width=max(1, int(2 * s)))
    img.alpha_composite(deco)
    d = ImageDraw.Draw(img)
    margin = int(80 * s)
    if kind == "title":
        paste_logo(img, int(170 * s), (margin, int(70 * s)))
        fnt, lines, fsize = fit_text(d, title, W - 2 * margin, int(260 * s), start=int(70 * s), minimum=int(30 * s), family="serif")
        y = int(H * 0.50) - len(lines) * int(fsize * 1.2) // 2
        for ln in lines:
            d.text((margin, y), ln, font=fnt, fill=CREAM)
            y += int(fsize * 1.2)
        d.rectangle((margin, y + int(14 * s), margin + int(120 * s), y + int(18 * s)), fill=GOLD)
        if subtitle:
            sf = font(int(28 * s))
            for ln in wrap(d, subtitle, sf, W - 2 * margin)[:2]:
                y += int(44 * s)
                d.text((margin, y), ln, font=sf, fill=GOLD_LIGHT)
    elif kind == "end":
        paste_logo(img, int(260 * s), ((W - int(260 * s)) // 2, int(H * 0.16)))
        f = font(int(40 * s), True, "serif")
        tw = text_width(d, title, f)
        d.text(((W - tw) // 2, int(H * 0.70)), title, font=f, fill=CREAM)
        if subtitle:
            sf = font(int(24 * s))
            tw = text_width(d, subtitle, sf)
            d.text(((W - tw) // 2, int(H * 0.70) + int(60 * s)), subtitle, font=sf, fill=MUTED)
    else:
        fnt, lines, fsize = fit_text(d, title, W - 2 * margin - int(120 * s), int(120 * s), start=int(50 * s), minimum=int(28 * s), family="serif")
        y = int(70 * s)
        for ln in lines:
            d.text((margin, y), ln, font=fnt, fill=CREAM)
            y += int(fsize * 1.18)
        d.rectangle((margin, y + int(10 * s), margin + int(90 * s), y + int(13 * s)), fill=GOLD)
        y += int(46 * s)
        items = [b for b in (bullets or []) if b][:6]
        if items:
            avail = H - y - int(90 * s)
            per = max(1, avail // len(items))
            bf, _, bsize = fit_text(d, max(items, key=len), W - 2 * margin - int(50 * s), per - int(8 * s),
                                    start=int(32 * s), minimum=int(20 * s), bold=False)
            for item in items:
                lines = wrap(d, item, bf, W - 2 * margin - int(50 * s))
                max_lines = max(1, (per - int(6 * s)) // int(bsize * 1.25))
                if len(lines) > max_lines:
                    lines = lines[:max_lines]
                    lines[-1] = lines[-1].rstrip(".,; ") + "…"
                r = int(7 * s)
                cy = y + int(bsize * 0.62)
                d.ellipse((margin, cy - r, margin + 2 * r, cy + r), fill=GOLD)
                for ln in lines:
                    d.text((margin + int(40 * s), y), ln, font=bf, fill=(232, 226, 212))
                    y += int(bsize * 1.25)
                y += int(14 * s)
    if signature and kind != "end":
        paste_logo(img, int(46 * s), (W - margin - int(46 * s), H - int(64 * s)), mark=True, opacity=0.9)
    if total and kind == "content":
        pf = font(int(18 * s))
        d.text((margin, H - int(52 * s)), f"{index:02d} / {total:02d}", font=pf, fill=MUTED)
    return img.convert("RGB")


# --------------------------------------------------------------- ffmpeg
@lru_cache(maxsize=1)
def ffmpeg_bin():
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def run_ffmpeg(args, timeout=900):
    exe = ffmpeg_bin()
    if not exe:
        raise RuntimeError("ffmpeg is not available. Install ffmpeg or `pip install imageio-ffmpeg`.")
    proc = subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y"] + list(args),
                          capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + proc.stderr.decode("utf-8", "replace")[-600:])


# --------------------------------------------------------------- TTS
_tts_lock = threading.Lock()


@lru_cache(maxsize=1)
def tts_engine() -> str:
    if config.PIPER_MODEL and Path(config.PIPER_MODEL).exists() and shutil.which("piper"):
        return "piper"
    if shutil.which("espeak-ng"):
        return "espeak-ng"
    if shutil.which("espeak"):
        return "espeak"
    if platform.system() == "Darwin" and shutil.which("say"):
        return "say"
    if platform.system() == "Windows" and shutil.which("powershell"):
        return "sapi"
    return "none"


def wav_duration(path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except (wave.Error, EOFError, FileNotFoundError):
        return 0.0


def synthesize(text: str, out_wav, voice: str = "a") -> bool:
    """Speak `text` into a 16-bit WAV file. `voice` is 'a' or 'b' (two hosts)."""
    engine = tts_engine()
    out_wav = str(out_wav)
    text = (text or "").strip()
    if not text or engine == "none":
        return False
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8",
                                     dir=str(config.TMP_DIR)) as tf:
        tf.write(text)
        txt_path = tf.name
    try:
        if engine == "piper":
            with open(txt_path, "rb") as fin:
                subprocess.run(["piper", "--model", config.PIPER_MODEL, "--output_file", out_wav],
                               stdin=fin, capture_output=True, timeout=300, check=True)
        elif engine in ("espeak-ng", "espeak"):
            v = config.TTS_VOICE + ("+m3" if voice == "a" else "+f3")
            subprocess.run([engine, "-v", v, "-s", "160", "-p", "45" if voice == "a" else "55",
                            "-f", txt_path, "-w", out_wav], capture_output=True, timeout=300, check=True)
        elif engine == "say":
            aiff = out_wav + ".aiff"
            subprocess.run(["say", "-f", txt_path, "-o", aiff], capture_output=True, timeout=300, check=True)
            run_ffmpeg(["-i", aiff, "-ar", "22050", "-ac", "1", out_wav])
            os.remove(aiff)
        elif engine == "sapi":
            script = ("Add-Type -AssemblyName System.Speech;"
                      "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                      "$s.SetOutputToWaveFile($env:INERA_WAV);"
                      "$s.Speak([IO.File]::ReadAllText($env:INERA_TXT));$s.Dispose()")
            env = dict(os.environ, INERA_WAV=out_wav, INERA_TXT=txt_path)
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                           env=env, capture_output=True, timeout=300, check=True)
        return wav_duration(out_wav) > 0.2
    except (subprocess.SubprocessError, OSError, RuntimeError):
        return False
    finally:
        try:
            os.remove(txt_path)
        except OSError:
            pass


def silent_wav(path, seconds: float, rate: int = 22050):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))


# --------------------------------------------------------------- reportlab fonts
_rl_lock = threading.Lock()
_rl_fonts = None


def reportlab_fonts():
    """Register a Unicode TTF (₹, accents) with reportlab; fall back to Helvetica."""
    global _rl_fonts
    with _rl_lock:
        if _rl_fonts:
            return _rl_fonts
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.lib.fonts import addMapping
        regular, bold = font_path("sans", False), font_path("sans", True)
        sreg, sbold = font_path("serif", False), font_path("serif", True)
        try:
            if regular and bold and regular.lower().endswith(".ttf") and bold.lower().endswith(".ttf"):
                pdfmetrics.registerFont(TTFont("InEraSans", regular))
                pdfmetrics.registerFont(TTFont("InEraSans-Bold", bold))
                addMapping("InEraSans", 0, 0, "InEraSans")
                addMapping("InEraSans", 1, 0, "InEraSans-Bold")
                addMapping("InEraSans", 0, 1, "InEraSans")
                addMapping("InEraSans", 1, 1, "InEraSans-Bold")
                serif = ("InEraSans", "InEraSans-Bold")
                if sreg and sbold and sreg.lower().endswith(".ttf") and sbold.lower().endswith(".ttf"):
                    pdfmetrics.registerFont(TTFont("InEraSerif", sreg))
                    pdfmetrics.registerFont(TTFont("InEraSerif-Bold", sbold))
                    serif = ("InEraSerif", "InEraSerif-Bold")
                _rl_fonts = {"regular": "InEraSans", "bold": "InEraSans-Bold",
                             "serif": serif[0], "serif_bold": serif[1], "unicode": True}
                return _rl_fonts
        except Exception:
            pass
        _rl_fonts = {"regular": "Helvetica", "bold": "Helvetica-Bold", "serif": "Times-Roman",
                     "serif_bold": "Times-Bold", "unicode": False}
        return _rl_fonts


def pdf_safe(text: str) -> str:
    """Make text safe for non-Unicode PDF fonts."""
    if reportlab_fonts()["unicode"]:
        return text
    return (text or "").replace("₹", "Rs. ").replace("€", "EUR ").replace("•", "-")
