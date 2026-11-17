"""«ΣΑΝ ΣΗΜΕΡΑ» για τα Παναθηναϊκά Νέα: ματς του Παναθηναϊκού που έγιναν την ίδια μέρα στο παρελθόν.

Πηγή: τα βίντεο του @microneuro (football_dates.json στο Mac: ημερομηνία, διοργάνωση, γήπεδο, σκόρερ
από την περιγραφή κάθε βίντεο — όχι AI). Ποτέ το ίδιο βίντεο με το Τριφυλλάκια (διαβάζει τι έχει
ανέβει ή περιμένει εκεί). Νίκες πρώτα (Ευρώπη/ντέρμπι), μετά ισοπαλίες. Αν η μέρα δεν έχει αρκετά,
παίρνει από ±1..3 μέρες με ετικέτα «ΣΑΝ ΑΥΤΗ ΤΗΝ ΕΒΔΟΜΑΔΑ».
"""
import json
import random
import re
import shutil
import sys
import unicodedata
from datetime import date, timedelta
from pathlib import Path

import requests
import yt_dlp

MONTHS = ["Ιανουαρίου", "Φεβρουαρίου", "Μαρτίου", "Απριλίου", "Μαΐου", "Ιουνίου", "Ιουλίου", "Αυγούστου",
          "Σεπτεμβρίου", "Οκτωβρίου", "Νοεμβρίου", "Δεκεμβρίου"]
DERBY = ("ΟΛΥΜΠΙΑΚΟΣ", "ΑΕΚ", "ΠΑΟΚ", "ΑΡΗΣ")
PAO = "ΠΑΝΑΘΗΝΑΙΚΟΣ"


def _norm(s):
    s = unicodedata.normalize("NFD", (s or "").upper())
    return unicodedata.normalize("NFC", "".join(c for c in s if not unicodedata.combining(c)))


def trifillakia_ids(cfg):
    """Ό,τι έχει ανέβει ή περιμένει στην ουρά του Τριφυλλάκια (για να μη διπλοανεβαίνει)."""
    raw = "https://raw.githubusercontent.com/" + cfg["source"]["exclude_repo"]
    ids = set()
    try:
        ids |= set(requests.get(f"{raw}/main/state/posted.json", timeout=30).json()["posted_ids"])
        ids |= set(requests.get(f"{raw}/queue/manifest.json", timeout=30).json())
    except Exception as e:
        raise RuntimeError(f"Δεν διαβάστηκε το Τριφυλλάκια ({e}) — δεν ρισκάρω διπλό βίντεο")
    return ids


def _rank(c):
    t = _norm(c["title"])
    derby = any(d in t for d in DERBY)
    if c["outcome"] == "W":
        return 0 if c.get("european") or derby else 1
    if c["outcome"] == "D":
        return 2 if c.get("european") or derby else 3
    return 9   # ήττες: όχι


def pick_for_day(cfg, day, n, used_ids, data_dir):
    """n ματς για τη μέρα day (date). Επιστρέφει [(match, label)] με τη σειρά των slots."""
    cat = json.loads((Path(data_dir) / "football_dates.json").read_text())
    src = cfg["source"]
    today = date.today()
    current = today.year if today.month >= 7 else today.year - 1
    pool = [c for c in cat.values()
            if c["id"] not in used_ids and c.get("duration") and c["duration"] <= src["max_seconds"]
            and c.get("season_start") and c["season_start"] <= current - src.get("exclude_recent_seasons", 1)
            and not c.get("friendly") and _rank(c) < 9]
    picked = []
    for delta in [0, 1, -1, 2, -2, 3, -3]:
        d = day + timedelta(days=delta)
        same = [c for c in pool if c["date"][5:] == d.strftime("%m-%d") and c not in [p for p, _ in picked]]
        rnd = random.Random(f"{day}{delta}")
        rnd.shuffle(same)
        same.sort(key=_rank)
        # απλώνουμε σε διαφορετικές δεκαετίες μέσα στην ίδια μέρα
        decades = set()
        for c in same:
            if len(picked) >= n:
                break
            dec = c["date"][:3]
            if dec in decades and any(x["date"][:3] not in decades for x in same if x not in [p for p, _ in picked]):
                continue
            decades.add(dec)
            picked.append((c, "ΣΑΝ ΣΗΜΕΡΑ" if delta == 0 else "ΣΑΝ ΑΥΤΗ ΤΗΝ ΕΒΔΟΜΑΔΑ"))
        if len(picked) >= n:
            break
    # τα πιο παλιά πρώτα μέσα στη μέρα (χρονολογική σειρά δίνει «ιστορία»)
    picked.sort(key=lambda x: x[0]["date"])
    return picked


def _opts():
    o = {"quiet": True, "no_warnings": True, "noprogress": True, "sleep_interval_requests": 1}
    deno = shutil.which("deno") or str(Path(sys.executable).with_name("deno"))
    if Path(deno).exists():
        o["js_runtimes"] = {"deno": {"path": deno}}
    return o


def download(video_id, workdir):
    from imageio_ffmpeg import get_ffmpeg_exe
    workdir = Path(workdir)
    opts = {**_opts(), "format": "bv*[height<=1080]+ba/b[height<=1080]", "merge_output_format": "mp4",
            "ffmpeg_location": get_ffmpeg_exe(), "outtmpl": str(workdir / "%(id)s.%(ext)s")}
    with yt_dlp.YoutubeDL(opts) as y:
        y.download([f"https://www.youtube.com/watch?v={video_id}"])
    return workdir / f"{video_id}.mp4"


def _teams(title):
    t = re.sub(r"\s+\d{4}/\d{2}.*$", "", title).strip()
    parts = re.split(r"\s+[-–]\s+", t, maxsplit=1)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (t, "")


def _comp(raw):
    """Διοργάνωση χωρίς τη φάση/αγωνιστική, με κεφαλαία (όπως η πηγή, χωρίς τόνους = σωστά)."""
    c = (raw or "").replace("’", "'").replace("΄", "'")
    c = " ".join(w.translate(str.maketrans("AB", "ΑΒ")) if re.search("[Α-Ω]", w) or re.fullmatch(r"[AB]'", w) else w
                 for w in c.split())
    c = re.sub(r"\s+(\d+\s*Η\s+ΑΓΩΝΙΣΤΙΚΗ|ΦΑΣΗ\b|[ΑΒΓ]'\s*ΑΓΩΝΑΣ|[ΑΒΓ]'\s*ΓΥΡΟΣ|[ΑΒΓ]'\s*ΣΥΜΠΛΗΡΩΜΑΤΙΚΟΣ|"
               r"\d+\s*Η?\s*ΑΓΩΝΙΣΤΙΚΗ|ΟΜΙΛΟΣ|[ΑΒΓ]'\s*ΦΑΣΗ|ΠΡΟΚΡΙΜΑΤΙΚ|ΦΑΣΗ ΤΩΝ).*$", "", c).strip(" -·")
    c = re.sub(r"([Α-Ω])(SUPER|CHAMPIONS|EUROPA)", r"\1 \2", c)
    return re.sub(r"\s+[ΑΒΓ]'$", "", c)


CLOSING = ["Θυμάσαι αυτό το ματς; Γράψ' το στα σχόλια! 💚", "Πού ήσουν εκείνη τη μέρα; Γράψ' το στα σχόλια! ☘️",
           "Μια μέρα σαν σήμερα, στην ιστορία του Παναθηναϊκού! 💚"]


def texts(c, label, cfg):
    y, m, d = map(int, c["date"].split("-"))
    home, away = _teams(c["title"])
    comp, stadium = _comp(c.get("competition")), (c.get("stadium") or "").strip()
    rnd = random.Random(c["id"])
    head = (f"📅 Σαν σήμερα, {d} {MONTHS[m - 1]} {y}" if label == "ΣΑΝ ΣΗΜΕΡΑ"
            else f"📅 Σαν αυτή την εβδομάδα, {d} {MONTHS[m - 1]} {y}")
    lines = [head, "", f"⚽ {home} – {away} {c['result']}"]
    if comp:
        lines.append(f"🏆 {comp}")
    if stadium:
        lines.append(f"🏟️ {stadium}")
    if c.get("scorers") and c["scorers"] not in ("-", "–"):
        lines.append(f"⚽ Σκόρερ: {c['scorers']}")
    lines += ["", rnd.choice(CLOSING if label == "ΣΑΝ ΣΗΜΕΡΑ" else CLOSING[:2])]
    caption = "\n".join(lines) + f"\n\n{cfg['source']['credit']}\n\n{cfg['hashtags']}"
    title = f"{'ΣΑΝ ΣΗΜΕΡΑ' if label == 'ΣΑΝ ΣΗΜΕΡΑ' else 'ΣΑΝ ΑΥΤΗ ΤΗΝ ΕΒΔΟΜΑΔΑ'} {y}: {home} – {away} {c['result']} ☘️"
    overlay = {"label": label, "date_text": f"{d} {MONTHS[m - 1]}", "year": str(y), "home": home, "away": away,
               "score": c["result"], "sub": " · ".join(x for x in (comp, stadium) if x)}
    return {"youtube_title": f"{title} #shorts", "full_description": caption, "overlay": overlay}
