"""Μοντάζ «ΣΑΝ ΣΗΜΕΡΑ» για τα Παναθηναϊκά Νέα: κάθετο 1080x1920.

  ┌──────────────────────────┐
  │   λογότυπο ΠΑΝΑΘΗΝΑΪΚΑ ΝΕΑ│
  │      [ ΣΑΝ ΣΗΜΕΡΑ ]       │  πράσινο χάπι
  │     17 ΝΟΕΜΒΡΙΟΥ          │  μεγάλη ημερομηνία
  │         1993              │  χρονιά σε πράσινο
  ├──────────────────────────┤
  │        ΒΙΝΤΕΟ             │  ολόκληρο σε πλάτος, θολό φόντο
  ├──────────────────────────┤
  │  ΠΑΝΑΘΗΝΑΪΚΟΣ – ΑΕΚ       │
  │        3-1                │  τεράστιο σκορ
  │  Πρωτάθλημα · Λεωφόρος    │
  │      ☘ panathinaikanea.gr │
  └──────────────────────────┘
Στο τέλος 2,5'' κάρτα με το στρογγυλό σήμα.
"""
import subprocess
import sys
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
W, H = 1080, 1920
GREEN = (0, 166, 81)
DARK = (8, 20, 13)
VID_TOP, VID_BOT = 600, 1330      # περιοχή βίντεο


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def caps(text):
    out = unicodedata.normalize("NFD", text.upper())
    out = "".join(ch for ch in out if ch not in ("́", "̀", "͂"))
    return unicodedata.normalize("NFC", out)


def font(size, black=True):
    name = "FiraSansExtraCondensed-Black.ttf" if black else "NotoSans-Black.ttf"
    return ImageFont.truetype(str(ASSETS / "fonts" / name), size)


def fit(draw, text, max_w, start, minimum=40, black=True):
    for s in range(start, minimum - 1, -2):
        f = font(s, black)
        if draw.textlength(text, font=f) <= max_w:
            return f
    return font(minimum, black)


def center(draw, y, text, f, fill):
    x = (W - draw.textlength(text, font=f)) / 2
    draw.text((x, y), text, font=f, fill=fill)


def build_overlay(info, out_png):
    """info: date_text ('17 ΝΟΕΜΒΡΙΟΥ'), year ('1993'), home, away, score, sub (διοργάνωση · γήπεδο), label."""
    c = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(c)
    # πάνω μέρος
    d.rectangle((0, 0, W, VID_TOP), fill=DARK + (255,))
    logo = Image.open(ASSETS / "logo_wide.png").convert("RGBA")
    c.alpha_composite(logo, ((W - logo.width) // 2, 60))
    pill = caps(info.get("label", "ΣΑΝ ΣΗΜΕΡΑ"))
    pf = font(58)
    pw = d.textlength(pill, font=pf) + 90
    d.rounded_rectangle(((W - pw) / 2, 190, (W + pw) / 2, 278), radius=44, fill=GREEN + (255,))
    center(d, 196, pill, pf, "white")
    center(d, 300, caps(info["date_text"]), fit(d, caps(info["date_text"]), W - 120, 130), "white")
    center(d, 440, info["year"], font(140), GREEN + (255,))
    d.rectangle((0, VID_TOP - 8, W, VID_TOP), fill=GREEN + (255,))
    # κάτω μέρος
    d.rectangle((0, VID_BOT, W, H), fill=DARK + (255,))
    d.rectangle((0, VID_BOT, W, VID_BOT + 8), fill=GREEN + (255,))
    teams = f"{caps(info['home'])} – {caps(info['away'])}"
    tf = fit(d, teams, W - 100, 86, 46)
    center(d, VID_BOT + 50, teams, tf, "white")
    center(d, VID_BOT + 150, info["score"], font(190), GREEN + (255,))
    if info.get("sub"):
        sub = caps(info["sub"])
        center(d, VID_BOT + 380, sub, fit(d, sub, W - 120, 46, 30, black=False), (200, 220, 205, 255))
    site = "panathinaikanea.gr"
    sf = font(44)
    sw = d.textlength(site, font=sf)
    icon = Image.open(ASSETS / "logo_round.png").convert("RGBA").resize((70, 70), Image.LANCZOS)
    x0 = (W - sw - 86) / 2
    c.alpha_composite(icon, (int(x0), H - 120))
    d.text((x0 + 86, H - 116), site, font=sf, fill="white")
    c.save(out_png)


def build_endcard(out_png):
    c = Image.new("RGB", (W, H), DARK)
    logo = Image.open(ASSETS / "logo_round.png").convert("RGBA")
    c.paste(logo, ((W - logo.width) // 2, 560), logo)
    d = ImageDraw.Draw(c)
    center(d, 1150, "ΑΚΟΛΟΥΘΗΣΕ ΜΑΣ", font(84), "white")
    center(d, 1260, "panathinaikanea.gr", font(64), GREEN)
    c.save(out_png)


def probe_duration(path):
    r = subprocess.run([ffmpeg_exe(), "-i", str(path)], capture_output=True, text=True)
    import re
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


def has_audio(path):
    r = subprocess.run([ffmpeg_exe(), "-i", str(path)], capture_output=True, text=True)
    return "Audio:" in r.stderr


def detect_crop(path, dur):
    """Βρίσκει μαύρες μπάρες (π.χ. παλιό 4:3 μέσα σε 16:9) για να κοπούν."""
    import re
    from collections import Counter
    r = subprocess.run(
        [ffmpeg_exe(), "-ss", str(min(2, dur / 4)), "-t", "20", "-i", str(path),
         "-vf", "fps=2,cropdetect=limit=24:round=2:reset=1", "-f", "null", "-"],
        capture_output=True, text=True)
    found = re.findall(r"crop=(\d+:\d+:\d+:\d+)", r.stderr)
    return Counter(found).most_common(1)[0][0] if found else None


def render(video_path, info, out_path, max_seconds=170):
    dur = min(probe_duration(video_path), max_seconds)
    crop = detect_crop(video_path, dur)
    crop_f = f"crop={crop}," if crop else ""
    work = Path(out_path).with_suffix("")
    ov, end = f"{work}_ov.png", f"{work}_end.png"
    build_overlay(info, ov)
    build_endcard(end)
    vh = VID_BOT - VID_TOP
    fc = (
        f"[0:v]{crop_f}fps=30,split[a][b];"
        f"[a]scale={W}:{vh}:force_original_aspect_ratio=increase,crop={W}:{vh},boxblur=25:2,eq=brightness=-0.15[bg];"
        f"[b]scale={W}:{vh}:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
        f"color={'0x08140d'}:s={W}x{H}:r=30:d={dur:.3f}[base];"
        f"[base][bg]overlay=0:{VID_TOP}:shortest=1[c1];"
        f"[c1][fg]overlay=(W-w)/2:{VID_TOP}+({vh}-h)/2:shortest=1[c2];"
        f"[c2][1:v]overlay=0:0:shortest=1,setsar=1,format=yuv420p[main];"
        + (f"[0:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{dur:.3f}[ma];" if has_audio(video_path)
           else f"anullsrc=r=48000:cl=stereo,atrim=0:{dur:.3f}[ma];") +
        f"[2:v]fps=30,setsar=1,format=yuv420p,fade=t=in:st=0:d=0.4[ev];"
        f"anullsrc=r=48000:cl=stereo,atrim=0:2.5[ea];"
        f"[main][ma][ev][ea]concat=n=2:v=1:a=1[v][aout]"
    )
    cmd = [ffmpeg_exe(), "-v", "error", "-y", "-t", f"{dur:.3f}", "-i", str(video_path),
           "-loop", "1", "-framerate", "30", "-t", f"{dur:.3f}", "-i", ov,
           "-loop", "1", "-framerate", "30", "-t", "2.5", "-i", end,
           "-filter_complex", fc, "-map", "[v]", "-map", "[aout]",
           "-c:v", "libx264", "-preset", "faster", "-crf", "21", "-maxrate", "2500k", "-bufsize", "5M",
           "-profile:v", "high", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out_path)]
    subprocess.run(cmd, check=True)
    return out_path


if __name__ == "__main__":
    build_overlay({"date_text": "17 Νοεμβρίου", "year": "1993", "home": "ΠΑΝΑΘΗΝΑΪΚΟΣ", "away": "ΑΕΚ",
                   "score": "3-1", "sub": "Πρωτάθλημα Α' Εθνικής · Λεωφόρος Αλεξάνδρας"}, sys.argv[1])
