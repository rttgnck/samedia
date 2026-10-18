"""Library scanner: walks the media roots, probes new/changed files and fills the database."""

import hashlib
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import db, metadata, naming, probe, subtitles
from .config import config

log = logging.getLogger("samedia.scanner")


def make_id(prefix: str, path: str) -> str:
    return prefix + hashlib.sha1(path.encode()).hexdigest()[:15]


class Scanner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self.status = {"running": False, "phase": "idle", "found": 0, "processed": 0,
                       "current": None, "last_finished": None, "last_error": None}

    # ── public ──────────────────────────────────────────────────────

    def request_scan(self) -> bool:
        if self.status["running"]:
            return False
        self._wake.set()
        return True

    def start_background(self) -> None:
        threading.Thread(target=self._loop, name="scanner", daemon=True).start()

    # ── internals ───────────────────────────────────────────────────

    def _loop(self) -> None:
        self._wake.set()  # scan once at startup
        while True:
            self._wake.wait(timeout=max(config.scan_interval_hours, 0.25) * 3600)
            self._wake.clear()
            try:
                self.scan()
            except Exception as exc:  # keep the loop alive no matter what
                log.exception("scan failed")
                self.status["last_error"] = str(exc)

    def scan(self) -> None:
        if not self._lock.acquire(blocking=False):
            return
        try:
            self.status.update(running=True, phase="walking", found=0, processed=0, current=None, last_error=None)
            roots = [Path(r) for r in config.media_roots]
            files: list[tuple[Path, Path]] = []
            reachable: list[Path] = []
            for root in roots:
                if not root.is_dir():
                    log.warning("media root not reachable: %s", root)
                    continue
                reachable.append(root)
                files.extend((root, f) for f in self._walk(root))
            self.status["found"] = len(files)

            known = {r["path"]: r for r in db.query("SELECT id, path, size, mtime FROM items")}
            todo = []
            for root, f in files:
                try:
                    st = f.stat()
                except OSError:
                    continue
                row = known.get(str(f))
                if row and row["size"] == st.st_size and abs(row["mtime"] - st.st_mtime) < 1:
                    self.status["processed"] += 1
                    continue
                todo.append((root, f, st))

            self.status["phase"] = "probing"
            with ThreadPoolExecutor(max_workers=max(1, config.probe_workers)) as pool:
                for _ in pool.map(lambda t: self._process(*t), todo):
                    self.status["processed"] += 1

            self.status["phase"] = "cleanup"
            self._remove_missing({str(f) for _, f in files}, reachable)
            self._refresh_sidecars(files)
            self._refresh_show_art()
        finally:
            self.status.update(running=False, phase="idle", current=None, last_finished=time.time())
            self._lock.release()

    def _walk(self, root: Path):
        for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
            dirnames[:] = [d for d in dirnames
                           if d.lower() not in naming.IGNORED_DIRS and not d.startswith(".")]
            for name in filenames:
                p = Path(dirpath) / name
                if p.suffix.lower() in naming.VIDEO_EXTS and not naming.is_ignored(p, root):
                    yield p

    def _process(self, root: Path, path: Path, st: os.stat_result) -> None:
        self.status["current"] = str(path)
        try:
            self._index_file(root, path, st)
        except Exception:
            log.exception("failed to index %s", path)

    def _index_file(self, root: Path, path: Path, st: os.stat_result) -> None:
        parsed = naming.parse(path, root)
        media = probe.probe(path) if path.suffix.lower() != ".iso" else None
        item_id = make_id("m" if parsed.kind == "movie" else "e", str(path))
        existing = db.one("SELECT added_at FROM items WHERE id=?", (item_id,))
        values = {
            "id": item_id, "kind": parsed.kind, "path": str(path), "root": str(root),
            "size": st.st_size, "mtime": st.st_mtime,
            "duration": (media or {}).get("duration"), "media": media,
            "sidecar_subs": subtitles.find_sidecars(path),
            "added_at": existing["added_at"] if existing else time.time(),
        }

        if parsed.kind == "movie":
            meta = {"title": parsed.title, "year": parsed.year}
            siblings = sum(1 for p in path.parent.iterdir() if p.suffix.lower() in naming.VIDEO_EXTS) \
                if path.parent != root else 99
            art = metadata.movie_art(path, folder_is_exclusive=siblings <= 2)
            nfo = metadata.movie_nfo(path)
            meta.update(nfo)
            if not (art["poster"] and art["backdrop"] and nfo.get("plot")):
                remote = metadata.tmdb.movie(meta["title"], meta.get("year"), nfo.get("tmdb_id"))
                for k, v in remote.items():
                    if k in ("poster", "backdrop"):
                        art[k] = art[k] or v
                    elif k not in nfo:
                        meta[k] = v
            values.update(meta, **art)
        else:
            show_id = self._ensure_show(parsed)
            show = db.one("SELECT tmdb_id FROM shows WHERE id=?", (show_id,))
            meta = {"title": parsed.title, "show_id": show_id, "season": parsed.season,
                    "episode": parsed.episode, "episode_end": parsed.episode_end}
            nfo = metadata.episode_nfo(path)
            meta.update({k: v for k, v in nfo.items() if k != "year"})
            art = metadata.episode_art(path)
            if show and show["tmdb_id"] and not (nfo.get("plot") and art["thumb"]):
                remote = metadata.tmdb.episode(show["tmdb_id"], parsed.season, parsed.episode)
                if remote.get("thumb") and not art["thumb"]:
                    art["thumb"] = remote.pop("thumb")
                remote.pop("thumb", None)
                for k, v in remote.items():
                    if k not in nfo:  # TMDB episode titles beat filename-derived ones
                        meta[k] = v
            values.update(meta, **art)

        values["sort_title"] = naming.sort_title(values["title"])
        db.upsert("items", values)

        if config.preextract_subs and media and media["subtitles"]:
            subtitles.extract_all(item_id, path, media)

    _show_lock = threading.Lock()

    def _ensure_show(self, parsed: naming.Parsed) -> str:
        show_path = str(parsed.show_dir)
        show_id = make_id("s", show_path)
        with self._show_lock:
            if db.one("SELECT id FROM shows WHERE id=?", (show_id,)):
                return show_id
            show_dir = Path(show_path)
            meta = {"title": parsed.show_title, "year": parsed.year}
            nfo = metadata.show_nfo(show_dir) if show_dir.exists() else {}
            meta.update(nfo)
            art = metadata.show_art(show_dir)
            if not (art["poster"] and art["backdrop"] and nfo.get("plot") and nfo.get("tmdb_id")):
                remote = metadata.tmdb.show(meta["title"], meta.get("year"), nfo.get("tmdb_id"))
                for k, v in remote.items():
                    if k in ("poster", "backdrop"):
                        art[k] = art[k] or v
                    elif k not in nfo:
                        meta[k] = v
            db.upsert("shows", {
                "id": show_id, "path": show_path, "sort_title": naming.sort_title(meta["title"]),
                "added_at": time.time(), **meta, **art,
            })
            return show_id

    def _remove_missing(self, present: set[str], reachable: list[Path]) -> None:
        reachable_roots = {str(r) for r in reachable}
        for row in db.query("SELECT id, path, root FROM items"):
            # Never purge items of an unplugged disk / unmounted share.
            if row["root"] in reachable_roots and row["path"] not in present:
                log.info("removing missing file %s", row["path"])
                db.execute("DELETE FROM items WHERE id=?", (row["id"],))
        db.execute("DELETE FROM shows WHERE id NOT IN (SELECT DISTINCT show_id FROM items WHERE show_id IS NOT NULL)")

    def _refresh_show_art(self) -> None:
        """Local poster/fanart dropped into a show folder after the first scan wins over older art."""
        for show in db.query("SELECT id, path, poster, backdrop FROM shows"):
            art = metadata.show_art(Path(show["path"]))
            for kind in ("poster", "backdrop"):
                if art[kind] and art[kind] != show[kind]:
                    db.execute(f"UPDATE shows SET {kind}=? WHERE id=?", (art[kind], show["id"]))
        for movie in db.query("SELECT id, path, root, poster, backdrop FROM items WHERE kind='movie'"):
            path = Path(movie["path"])
            if not path.parent.is_dir():
                continue
            siblings = sum(1 for p in path.parent.iterdir() if p.suffix.lower() in naming.VIDEO_EXTS) \
                if str(path.parent) != movie["root"] else 99
            art = metadata.movie_art(path, folder_is_exclusive=siblings <= 2)
            for kind in ("poster", "backdrop"):
                if art[kind] and art[kind] != movie[kind]:
                    db.execute(f"UPDATE items SET {kind}=? WHERE id=?", (art[kind], movie["id"]))

    def _refresh_sidecars(self, files: list[tuple[Path, Path]]) -> None:
        """Pick up subtitle files added next to already-indexed videos."""
        for _, f in files:
            subs = subtitles.find_sidecars(f)
            db.execute("UPDATE items SET sidecar_subs=? WHERE path=? AND sidecar_subs != ?",
                       (db.json.dumps(subs), str(f), db.json.dumps(subs)))


scanner = Scanner()
