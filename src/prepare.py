"""Τρέχει στο Mac: γεμίζει την ουρά με έτοιμα βίντεο (μοντάζ + κείμενα) για τις επόμενες μέρες
και τα ανεβάζει στο GitHub (branch "queue"). Από εκεί το GitHub κάνει τις αναρτήσεις.

  python src/prepare.py            # γεμίζει την ουρά (το τρέχει μόνο του το Mac κάθε μέρα)
  python src/prepare.py --one      # φτιάχνει μόνο ένα βίντεο (για δοκιμή)

Το κατέβασμα από το YouTube γίνεται ανώνυμα (χωρίς λογαριασμό/cookies), ένα-ένα με παύσεις.
"""
import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("PANATHINAIKANEA_DATA", Path.home() / "Library/Application Support/PanathinaikaneaAuto"))
os.environ["PANATHINAIKANEA_DATA"] = str(DATA)

import render  # noqa: E402
import sansimera  # noqa: E402


def git(*args, cwd=ROOT, check=True):
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True).stdout.strip()


def notify(msg):
    subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "Παναθηναϊκά Νέα"'], check=False)


class Queue:
    """Η ουρά ζει ΜΟΝΟ στο GitHub (branch "queue"). Κάθε φορά κάνουμε ένα ελαφρύ αντίγραφο
    χωρίς τα βίντεο (μόνο τα .json), προσθέτουμε τα καινούρια και τα ανεβάζουμε.
    Στο Mac δεν μένει κανένα βίντεο."""

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="pn-queue-"))
        remote = git("remote", "get-url", "origin")
        if git("ls-remote", "--heads", remote, "queue"):
            git("clone", "-q", "--filter=blob:none", "--no-checkout", "--single-branch", "-b", "queue",
                remote, str(self.dir))
            git("sparse-checkout", "set", "--no-cone", "/*.json", cwd=self.dir)
            git("checkout", "-q", "queue", cwd=self.dir)
        else:
            git("init", "-q", "-b", "queue", str(self.dir))
            git("remote", "add", "origin", remote, cwd=self.dir)
            git("sparse-checkout", "set", "--no-cone", "/*.json", cwd=self.dir)
        m = self.dir / "manifest.json"
        self.manifest = json.loads(m.read_text()) if m.exists() else []
        # Καθαρισμός: ό,τι δεν είναι έγκυρο έτοιμο βίντεο (π.χ. δοκιμαστικά αρχεία) φεύγει
        valid = []
        for item_id in self.manifest:
            meta = self.dir / f"{item_id}.json"
            if meta.exists() and "youtube_title" in json.loads(meta.read_text() or "{}"):
                valid.append(item_id)
        self.manifest = valid
        for meta in self.dir.glob("*.json"):
            if meta.name != "manifest.json" and meta.stem not in valid:
                self.manifest.append(meta.stem)
                self.remove(meta.stem)

    def remove(self, item_id):
        for ext in (".mp4", ".json", "_story.mp4"):
            git("rm", "-q", "--cached", "--sparse", "--ignore-unmatch", "--", f"{item_id}{ext}", cwd=self.dir)
            (self.dir / f"{item_id}{ext}").unlink(missing_ok=True)
        self.manifest.remove(item_id)

    def add(self, staged_mp4, meta):
        item_id = staged_mp4.stem
        shutil.move(str(staged_mp4), self.dir / staged_mp4.name)
        (self.dir / f"{item_id}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
        git("add", "--sparse", "--", staged_mp4.name, f"{item_id}.json", cwd=self.dir)
        (self.dir / staged_mp4.name).unlink()  # το βίντεο είναι πλέον μέσα στο git, σβήνουμε το αρχείο
        story = staged_mp4.with_name(f"{item_id}_story.mp4")
        if story.exists():   # έκδοση ≤59'' για το Instagram Story
            shutil.move(str(story), self.dir / story.name)
            git("add", "--sparse", "--", story.name, cwd=self.dir)
            (self.dir / story.name).unlink()
        self.manifest.append(item_id)

    def push(self):
        (self.dir / "manifest.json").write_text(json.dumps(self.manifest, indent=1))
        git("add", "--sparse", "manifest.json", cwd=self.dir)
        # μόνο ό,τι είναι staged: τα .mp4 που σβήσαμε από τον δίσκο φαίνονται «deleted» στο status
        if git("diff", "--cached", "--name-only", cwd=self.dir):
            git("-c", "user.name=panathinaikanea-mac", "-c", "user.email=mac@users.noreply.github.com",
                "commit", "-q", "-m", f"Ουρά: {len(self.manifest)} βίντεο", cwd=self.dir)
            env = {**os.environ, "GIT_NO_LAZY_FETCH": "1"}
            subprocess.run(["git", "push", "-q", "origin", "queue"], cwd=self.dir, check=True, env=env)
        # καθαρίζουμε τα αντικείμενα που ανέβηκαν ώστε να μη μένουν στον δίσκο
        git("gc", "-q", "--prune=now", cwd=self.dir, check=False)

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def make_story(out):
    """Instagram Story δέχεται βίντεο έως 60''. Φτιάχνει {id}_story.mp4 (τα πρώτα 59'' με σβήσιμο)."""
    from imageio_ffmpeg import get_ffmpeg_exe
    story = out.with_name(f"{out.stem}_story.mp4")
    subprocess.run([get_ffmpeg_exe(), "-v", "error", "-y", "-i", str(out), "-t", "59",
                    "-vf", "fade=t=out:st=58:d=1", "-af", "afade=t=out:st=57:d=2",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-c:a", "aac", "-b:a", "128k",
                    "-movflags", "+faststart", str(story)], check=True)
    return story


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--one", action="store_true")
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    lock = open(DATA / "prepare.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit("Τρέχει ήδη.")

    before = git("rev-parse", "HEAD")
    git("pull", "-q", "--rebase", "--autostash")  # φρέσκο ιστορικό αναρτήσεων + ρυθμίσεις
    if git("rev-parse", "HEAD") != before:  # ήρθε νέος κώδικας: ξεκινάμε ξανά με αυτόν
        lock.close()
        os.execv(sys.executable, [sys.executable, *sys.argv])
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    posted = set(json.loads((ROOT / "state/posted.json").read_text())["posted_ids"])

    q = Queue()
    try:
        for item in [i for i in q.manifest if i in posted]:  # βγάζουμε ό,τι έχει αναρτηθεί
            q.remove(item)
        from datetime import date, timedelta
        today = date.today()
        metas = {i: json.loads((q.dir / f"{i}.json").read_text()) for i in q.manifest}
        for i, m in list(metas.items()):          # ό,τι έμεινε από περασμένες μέρες φεύγει
            if m.get("air_date", "") < today.isoformat():
                q.remove(i)
                metas.pop(i)
        have = {(m["air_date"], m["slot_index"]) for m in metas.values()}
        n_slots = len(cfg["schedule"]["slots"])
        days = 1 if args.one else cfg["queue"]["days_ahead"]
        excluded = posted | set(q.manifest) | sansimera.trifillakia_ids(cfg)
        jobs = []
        for k in range(days):
            day = today + timedelta(days=k)
            missing = [s for s in range(n_slots) if (day.isoformat(), s) not in have]
            if not missing:
                continue
            picks = sansimera.pick_for_day(cfg, day, n_slots, excluded, DATA)
            # τα slots που ήδη υπάρχουν κρατάνε τα ματς τους· γεμίζουμε μόνο τα κενά
            picks = [p for p in picks if p[0]["id"] not in excluded]
            for s, (c, label) in zip(missing, picks):
                jobs.append((day, s, c, label))
                excluded.add(c["id"])
        if args.one:
            jobs = jobs[:1]
        print(f"Στην ουρά: {len(q.manifest)} | φτιάχνω: {len(jobs)}")
        made = 0
        for day, slot_i, c, label in jobs:
            work = Path(tempfile.mkdtemp(prefix="pn-work-"))
            try:
                video = sansimera.download(c["id"], work)
                text = sansimera.texts(c, label, cfg)
                out = work / "out" / f"{c['id']}.mp4"
                out.parent.mkdir()
                render.render(video, text["overlay"], out, max_seconds=cfg["source"]["max_seconds"])
                make_story(out)
                q.add(out, {"source_title": c["title"], "youtube_title": text["youtube_title"],
                            "full_description": text["full_description"], "air_date": day.isoformat(),
                            "slot_index": slot_i, "match_date": c["date"], "label": label})
                made += 1
                print(f"✓ {day} #{slot_i + 1}: {c['date']} {c['title']} {c['result']}")
                if made % 3 == 0:
                    q.push()
            except Exception as e:
                print(f"✗ σφάλμα: {e}")
                if "not a bot" in str(e):
                    notify("Το YouTube ζήτησε παύση — συνεχίζω στην επόμενη εκτέλεση.")
                    break
            finally:
                shutil.rmtree(work, ignore_errors=True)
        q.push()
        if made:
            notify(f"Έτοιμα {made} νέα βίντεο. Στην ουρά: {len(q.manifest)}.")
    finally:
        q.close()


if __name__ == "__main__":
    main()
