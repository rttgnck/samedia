"""Library scanner: walks the media roots, probes new/changed files and fills the database."""

import hashlib
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import db, metadata, music, naming, probe, subtitles
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
                if config.kind_of(root) != "music":
                    files.extend((root, f) for f in self._walk(root))
            self.status["found"] = len(files)

            known = {r["path"]: r for r in db.query("SELECT id, kind, path, size, mtime FROM items")}
            todo = []
            for root, f in files:
                try:
                    st = f.stat()
                except OSError:
                    continue
                row = known.get(str(f))
                if row and row["size"] == st.st_size and abs(row["mtime"] - st.st_mtime) < 1 \
                        and naming.parse(f, root, prefer=config.kind_of(root)).kind == row["kind"]:
                    self.status["processed"] += 1
                    continue
                todo.append((root, f, st))

            self.status["phase"] = "probing"
            with ThreadPoolExecutor(max_workers=max(1, config.probe_workers)) as pool:
                for _ in pool.map(lambda t: self._process(*t), todo):
                    self.status["processed"] += 1

            self.status["phase"] = "music"
            music.scan([(r, config.kind_of(r)) for r in roots], self.status)

            self.status["phase"] = "cleanup"
            self._remove_missing({str(f) for _, f in files}, reachable)
            self._refresh_sidecars(files)
            self._refresh_show_art()
            self._enrich_pending()
            self.status["phase"] = "title cards"
            self._title_cards()
            self.status["phase"] = "music artwork"
            music.enrich()
            self.status["phase"] = "collections"
            self._refresh_collections()
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

    @staticmethod
    def _video_siblings(path: Path, root: Path) -> int:
        if path.parent == root:
            return 99
        return sum(1 for p in path.parent.iterdir()
                   if p.suffix.lower() in naming.VIDEO_EXTS and not p.name.startswith("."))

    def _index_file(self, root: Path, path: Path, st: os.stat_result) -> None:
        parsed = naming.parse(path, root, folder_exclusive=self._video_siblings(path, root) == 1,
                              prefer=config.kind_of(root))
        item_id = make_id("m" if parsed.kind == "movie" else "e", str(path))
        previous = db.one("SELECT id, media, size, mtime, added_at FROM items WHERE path=?", (str(path),))
        if previous and previous["id"] != item_id:
            # Same file, now read as a different kind (e.g. a movie that is really an episode):
            # keep its probe result, drop the old entry (ids depend on the kind).
            db.execute("DELETE FROM items WHERE id=?", (previous["id"],))
        unchanged = previous and previous["size"] == st.st_size and abs(previous["mtime"] - st.st_mtime) < 1
        if unchanged and previous["media"]:
            media = previous["media"]
        else:
            media = probe.probe(path) if path.suffix.lower() != ".iso" else None
        existing = db.one("SELECT added_at FROM items WHERE id=?", (item_id,))
        values = {
            "id": item_id, "kind": parsed.kind, "path": str(path), "root": str(root),
            "size": st.st_size, "mtime": st.st_mtime,
            "duration": (media or {}).get("duration"), "media": media,
            "sidecar_subs": subtitles.find_sidecars(path),
            "added_at": existing["added_at"] if existing else (previous["added_at"] if previous else time.time()),
        }

        if parsed.kind == "movie":
            values.update(self._movie_metadata(path, root, parsed))
        else:
            show_id = self._ensure_show(parsed)
            show = db.one("SELECT tmdb_id FROM shows WHERE id=?", (show_id,))
            meta = {"title": parsed.title, "show_id": show_id, "season": parsed.season,
                    "episode": parsed.episode, "episode_end": parsed.episode_end}
            nfo = metadata.episode_nfo(path)
            meta.update({k: v for k, v in nfo.items() if k != "year"})
            art = metadata.episode_art(path)
            if metadata.tmdb.enabled:
                meta["meta_at"] = time.time()
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

    # Columns filled from .nfo / local art / TMDB (refreshed when metadata is re-fetched)
    MOVIE_META_COLS = ("title", "sort_title", "year", "plot", "tagline", "rating", "genres", "poster", "backdrop",
                       "certification", "cast_members", "director", "collection_hint", "tmdb_id", "meta_at")
    SHOW_META_COLS = ("title", "sort_title", "year", "plot", "rating", "genres", "poster", "backdrop",
                      "certification", "cast_members", "tmdb_id", "meta_at")

    def _movie_metadata(self, path: Path, root: Path, parsed: naming.Parsed) -> dict:
        """.nfo beats TMDB for text; local artwork beats TMDB artwork."""
        meta: dict = {"title": parsed.title, "year": parsed.year}
        art = metadata.movie_art(path, folder_is_exclusive=self._video_siblings(path, root) <= 2)
        nfo = metadata.movie_nfo(path)
        meta.update(nfo)
        if metadata.tmdb.enabled:
            remote = metadata.tmdb.movie(meta["title"], meta.get("year"), nfo.get("tmdb_id"))
            for k, v in remote.items():
                if k in ("poster", "backdrop"):
                    art[k] = art[k] or v
                elif k == "collection_hint":
                    meta[k] = {**v, **(nfo.get(k) or {})}
                elif k not in nfo:
                    meta[k] = v
            meta["meta_at"] = time.time()
        meta["sort_title"] = naming.sort_title(meta["title"])
        return {**meta, **art}

    def _show_metadata(self, show_dir: Path, title: str, year: int | None) -> dict:
        meta: dict = {"title": title, "year": year}
        nfo = metadata.show_nfo(show_dir) if show_dir.exists() else {}
        meta.update(nfo)
        art = metadata.show_art(show_dir)
        if metadata.tmdb.enabled:
            remote = metadata.tmdb.show(meta["title"], meta.get("year"), nfo.get("tmdb_id"))
            for k, v in remote.items():
                if k in ("poster", "backdrop"):
                    art[k] = art[k] or v
                elif k not in nfo:
                    meta[k] = v
            meta["meta_at"] = time.time()
        meta["sort_title"] = naming.sort_title(meta["title"])
        return {**meta, **art}

    @staticmethod
    def _update(table: str, row_id: str, values: dict, cols: tuple[str, ...]) -> None:
        values = db._encode({k: v for k, v in values.items() if k in cols})
        if values:
            db.execute(f"UPDATE {table} SET {', '.join(f'{k}=?' for k in values)} WHERE id=?",
                       (*values.values(), row_id))

    def _enrich_pending(self) -> None:
        """Fetch TMDB metadata for titles indexed before a TMDB key was set (or reset for a refresh)."""
        if not metadata.tmdb.enabled:
            return
        movies = db.query("SELECT id, path, root FROM items WHERE kind='movie' AND meta_at IS NULL")
        shows = db.query("SELECT id, path, title, year FROM shows WHERE meta_at IS NULL")
        if not movies and not shows:
            return
        self.status.update(phase="metadata", found=len(movies) + len(shows), processed=0)

        def movie(row):
            path, root = Path(row["path"]), Path(row["root"])
            if path.exists():
                parsed = naming.parse(path, root, folder_exclusive=self._video_siblings(path, root) == 1)
                self._update("items", row["id"], self._movie_metadata(path, root, parsed), self.MOVIE_META_COLS)

        def show(row):
            self._update("shows", row["id"], self._show_metadata(Path(row["path"]), row["title"], row["year"]),
                         self.SHOW_META_COLS)
            sh = db.one("SELECT tmdb_id FROM shows WHERE id=?", (row["id"],))
            for ep in db.query("SELECT id, season, episode FROM items WHERE show_id=? AND meta_at IS NULL",
                               (row["id"],)):
                remote = metadata.tmdb.episode(sh["tmdb_id"], ep["season"], ep["episode"]) if sh["tmdb_id"] else {}
                values = {"meta_at": time.time(), **{k: v for k, v in remote.items() if k in ("title", "plot", "rating")}}
                if remote.get("thumb"):
                    db.execute("UPDATE items SET thumb=COALESCE(thumb, ?) WHERE id=?", (remote["thumb"], ep["id"]))
                self._update("items", ep["id"], values, ("title", "plot", "rating", "meta_at"))

        def run(task):
            fn, row = task
            try:
                fn(row)
            except Exception:
                log.exception("metadata refresh failed for %s", row.get("path"))
            self.status["processed"] += 1

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(run, [(movie, m) for m in movies] + [(show, s) for s in shows]))

    # ── collections ─────────────────────────────────────────────────

    GENERIC_DIRS = {"movies", "movie", "films", "film", "4k", "uhd", "hd", "1080p", "720p", "2160p", "media",
                    "videos", "video", "kids", "children", "family", "new", "misc", "other", "downloads",
                    "complete", "completed", "collections", "library"}
    FOLDER_COLLECTION_MAX = 12   # a folder with more movies than this is a library folder, not a franchise

    def _refresh_collections(self) -> None:
        """Group movies: a franchise folder > a .nfo <set> > a TMDB collection (when 2+ are in the library)."""
        movies = db.query("SELECT id, path, root, collection_hint FROM items WHERE kind='movie'")
        under: dict[Path, int] = {}
        chains: dict[str, list[Path]] = {}
        for m in movies:
            path, root = Path(m["path"]), Path(m["root"])
            chain = [d for d in path.parents if d != root and root in d.parents]
            chains[m["id"]] = chain
            for d in chain:
                under[d] = under.get(d, 0) + 1

        groups: dict[str, dict] = {}

        def add(key: str, info: dict, movie_id: str) -> None:
            g = groups.setdefault(key, {**info, "members": []})
            g["members"].append(movie_id)

        for m in movies:
            chain = chains[m["id"]]
            if chain and under[chain[0]] == 1:
                chain = chain[1:]          # the movie's own folder isn't a collection
            folder = next((d for d in chain if 2 <= under[d] <= self.FOLDER_COLLECTION_MAX
                           and d.name.lower() not in self.GENERIC_DIRS), None)
            hint = m.get("collection_hint") or {}
            if folder:
                add(f"folder:{folder}", {"name": naming.clean(folder.name) or folder.name, "source": "folder",
                                         "folder": folder}, m["id"])
            elif hint.get("nfo"):
                add(f"nfo:{hint['nfo'].strip().lower()}", {"name": hint["nfo"].strip(), "source": "nfo"}, m["id"])
            elif hint.get("tmdb"):
                t = hint["tmdb"]
                add(f"tmdb:{t['id']}", {"name": t.get("name") or "Collection", "source": "tmdb", "tmdb": t}, m["id"])

        hints = {m["id"]: m.get("collection_hint") or {} for m in movies}
        assigned: dict[str, str] = {}
        keep: set[str] = set()
        for key, g in groups.items():
            if len(g["members"]) < 2:
                continue                    # a "collection" of one is just a movie
            cid = make_id("c", key)
            keep.add(cid)
            poster = backdrop = None
            if g["source"] == "folder":
                art = metadata.show_art(g["folder"])   # poster.jpg / folder.jpg / fanart.jpg in the folder
                poster, backdrop = art["poster"], art["backdrop"]
            # Any member's TMDB collection art fills the gaps
            tmdb_hint = next((hints[mid]["tmdb"] for mid in g["members"] if hints[mid].get("tmdb")), None)
            if tmdb_hint:
                poster, backdrop = poster or tmdb_hint.get("poster"), backdrop or tmdb_hint.get("backdrop")
            db.upsert("collections", {
                "id": cid, "name": g["name"], "sort_title": naming.sort_title(g["name"]), "source": g["source"],
                "poster": poster, "backdrop": backdrop, "tmdb_id": (tmdb_hint or {}).get("id"),
            })
            for mid in g["members"]:
                assigned[mid] = cid

        for m in movies:
            db.execute("UPDATE items SET collection_id=? WHERE id=? AND COALESCE(collection_id,'') != COALESCE(?, '')",
                       (assigned.get(m["id"]), m["id"], assigned.get(m["id"])))
        if keep:
            marks = ",".join("?" for _ in keep)
            db.execute(f"DELETE FROM collections WHERE id NOT IN ({marks})", tuple(keep))
        else:
            db.execute("DELETE FROM collections")

    def _ensure_show(self, parsed: naming.Parsed) -> str:
        show_path = str(parsed.show_dir)
        show_id = make_id("s", show_path)
        with self._show_lock:
            if db.one("SELECT id FROM shows WHERE id=?", (show_id,)):
                return show_id
            values = self._show_metadata(Path(show_path), parsed.show_title, parsed.year)
            db.upsert("shows", {"id": show_id, "path": show_path, "added_at": time.time(), **values})
            return show_id

    def _title_cards(self, limit: int = 400) -> None:
        """Logos and text-free scenes for titles TMDB knows (checked again after a month)."""
        if not metadata.tmdb.enabled:
            return
        old = time.time() - 30 * 86400
        for table, kind, cond in (("items", "movie", "kind='movie'"), ("shows", "show", "1=1")):
            rows = db.query(f"SELECT id, tmdb_id, backdrop FROM {table} WHERE {cond} AND tmdb_id IS NOT NULL "
                            "AND (cards_at IS NULL OR cards_at < ?) LIMIT ?", (old, limit))
            for r in rows:
                cards = metadata.tmdb.cards(kind, r["tmdb_id"], r["backdrop"])
                db.execute(f"UPDATE {table} SET logo=?, scene=?, cards_at=? WHERE id=?",
                           (cards.get("logo"), cards.get("scene"), time.time(), r["id"]))

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
