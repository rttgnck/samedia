"""Read-side library queries and JSON shapes sent to the TV."""

from . import db
from .playback import channel_label

ITEM_COLS = ("i.id, i.kind, i.title, i.year, i.show_id, i.season, i.episode, i.episode_end, i.plot, "
             "i.rating, i.genres, i.poster, i.backdrop, i.thumb, i.duration, i.media, i.added_at, "
             "p.position, p.watched, p.play_count, p.updated_at AS progress_at, "
             "s.title AS show_title, s.poster AS show_poster, s.backdrop AS show_backdrop")
ITEM_FROM = "items i LEFT JOIN progress p ON p.item_id = i.id LEFT JOIN shows s ON s.id = i.show_id"


def _art(owner: str, ref: str | None, kind: str) -> str | None:
    return f"/api/v1/art/{owner}/{kind}" if ref else None


def badges(media: dict | None) -> list[str]:
    if not media:
        return []
    out = []
    v = media.get("video") or {}
    w = v.get("width") or 0
    out.append("4K" if w >= 3200 else "1080p" if w >= 1800 else "720p" if w >= 1200 else "SD" if w else None)
    hdr = v.get("hdr") or ""
    out.append("Dolby Vision" if hdr.startswith("dv") else {"hdr10": "HDR10", "hlg": "HLG"}.get(hdr))
    audio = media.get("audio") or []
    if audio:
        a = next((x for x in audio if x.get("default")), audio[0])
        if any(x.get("atmos") for x in audio):
            out.append("Atmos")
        out.append(channel_label(a.get("channels")) if (a.get("channels") or 0) > 2 else None)
    return [b for b in out if b]


def item_summary(r: dict) -> dict:
    is_ep = r["kind"] == "episode"
    out = {
        "id": r["id"], "kind": r["kind"], "title": r["title"], "year": r.get("year"),
        "duration": r.get("duration"), "rating": r.get("rating"), "plot": r.get("plot"),
        "genres": r.get("genres") or [],
        "poster": _art(r["id"], r.get("poster"), "poster") or (_art(r["show_id"], r.get("show_poster"), "poster") if is_ep else None),
        "backdrop": _art(r["id"], r.get("backdrop"), "backdrop") or (_art(r["show_id"], r.get("show_backdrop"), "backdrop") if is_ep else None),
        "thumb": _art(r["id"], r.get("thumb"), "thumb"),
        "position": r.get("position") or 0,
        "watched": bool(r.get("watched")),
        "badges": badges(r.get("media")),
        "added_at": r.get("added_at"),
    }
    if is_ep:
        out.update(show_id=r["show_id"], show_title=r.get("show_title"), season=r.get("season"),
                   episode=r.get("episode"), episode_end=r.get("episode_end"))
    return out


def show_summary(r: dict) -> dict:
    return {
        "id": r["id"], "kind": "show", "title": r["title"], "year": r.get("year"), "plot": r.get("plot"),
        "rating": r.get("rating"), "genres": r.get("genres") or [],
        "poster": _art(r["id"], r.get("poster"), "poster"),
        "backdrop": _art(r["id"], r.get("backdrop"), "backdrop"),
        "episode_count": r.get("episode_count"), "unwatched": r.get("unwatched"),
        "added_at": r.get("last_added") or r.get("added_at"),
    }


def get_item(item_id: str) -> dict | None:
    return db.one(f"SELECT {ITEM_COLS}, i.path, i.sidecar_subs FROM {ITEM_FROM} WHERE i.id=?", (item_id,))


SHOW_COLS = ("sh.*, COUNT(i.id) AS episode_count, "
             "SUM(CASE WHEN COALESCE(p.watched,0)=0 THEN 1 ELSE 0 END) AS unwatched, MAX(i.added_at) AS last_added")
SHOW_FROM = "shows sh JOIN items i ON i.show_id = sh.id LEFT JOIN progress p ON p.item_id = i.id"


MOVIE_SORTS = {"title": "i.sort_title ASC", "added": "i.added_at DESC", "year": "i.year DESC, i.sort_title",
               "rating": "i.rating DESC, i.sort_title"}
SHOW_SORTS = {"title": "sh.sort_title ASC", "added": "last_added DESC", "year": "sh.year DESC, sh.sort_title",
              "rating": "sh.rating DESC, sh.sort_title"}


def movies(sort: str = "title", genre: str | None = None, unwatched: bool = False,
           offset: int = 0, limit: int = 5000) -> list[dict]:
    where, params = ["i.kind='movie'"], []
    if genre:
        where.append("i.genres LIKE ?")
        params.append(f'%"{genre}"%')
    if unwatched:
        where.append("COALESCE(p.watched,0)=0")
    rows = db.query(f"SELECT {ITEM_COLS} FROM {ITEM_FROM} WHERE {' AND '.join(where)} "
                    f"ORDER BY {MOVIE_SORTS.get(sort, MOVIE_SORTS['title'])} LIMIT ? OFFSET ?",
                    (*params, limit, offset))
    return [item_summary(r) for r in rows]


def shows(sort: str = "title", genre: str | None = None, offset: int = 0, limit: int = 5000) -> list[dict]:
    where, params = "", []
    if genre:
        where, params = "WHERE sh.genres LIKE ?", [f'%"{genre}"%']
    rows = db.query(f"SELECT {SHOW_COLS} FROM {SHOW_FROM} {where} GROUP BY sh.id "
                    f"ORDER BY {SHOW_SORTS.get(sort, SHOW_SORTS['title'])} LIMIT ? OFFSET ?",
                    (*params, limit, offset))
    return [show_summary(r) for r in rows]


def show_detail(show_id: str) -> dict | None:
    row = db.one(f"SELECT {SHOW_COLS} FROM {SHOW_FROM} WHERE sh.id=? GROUP BY sh.id", (show_id,))
    if not row:
        return None
    eps = [item_summary(r) for r in db.query(
        f"SELECT {ITEM_COLS} FROM {ITEM_FROM} WHERE i.show_id=? ORDER BY i.season, i.episode", (show_id,))]
    seasons: dict[int, dict] = {}
    for e in eps:
        s = seasons.setdefault(e["season"], {"season": e["season"], "episode_count": 0, "unwatched": 0})
        s["episode_count"] += 1
        s["unwatched"] += 0 if e["watched"] else 1
    out = show_summary(row)
    out["seasons"] = sorted(seasons.values(), key=lambda s: (s["season"] == 0, s["season"]))
    out["episodes"] = eps
    out["next_up"] = _next_for_show(eps)
    return out


def _next_for_show(eps: list[dict]) -> dict | None:
    """Resume the in-progress episode, else the first unwatched after the last watched one."""
    regular = [e for e in eps if e["season"] != 0]
    for e in regular:
        if e["position"] > 60 and not e["watched"]:
            return e
    last_watched = max((i for i, e in enumerate(regular) if e["watched"]), default=-1)
    for e in regular[last_watched + 1:]:
        if not e["watched"]:
            return e
    return None


def next_episode(item: dict) -> dict | None:
    if item["kind"] != "episode":
        return None
    row = db.one(f"SELECT {ITEM_COLS} FROM {ITEM_FROM} WHERE i.show_id=? AND "
                 "(i.season > ? OR (i.season = ? AND i.episode > ?)) AND i.season != 0 "
                 "ORDER BY i.season, i.episode LIMIT 1",
                 (item["show_id"], item["season"], item["season"], item["episode"]))
    return item_summary(row) if row else None


def continue_watching(limit: int = 20) -> list[dict]:
    rows = db.query(f"SELECT {ITEM_COLS} FROM {ITEM_FROM} WHERE p.position > 60 AND p.watched = 0 "
                    "ORDER BY p.updated_at DESC LIMIT ?", (limit,))
    return [item_summary(r) for r in rows]


def next_up(limit: int = 20) -> list[dict]:
    active = db.query("SELECT i.show_id, MAX(p.updated_at) AS last FROM progress p JOIN items i ON i.id = p.item_id "
                      "WHERE i.kind='episode' AND p.watched = 1 GROUP BY i.show_id ORDER BY last DESC LIMIT ?",
                      (limit * 2,))
    out = []
    in_progress = {c["id"] for c in continue_watching(100)}
    for a in active:
        eps = [item_summary(r) for r in db.query(
            f"SELECT {ITEM_COLS} FROM {ITEM_FROM} WHERE i.show_id=? ORDER BY i.season, i.episode", (a["show_id"],))]
        nxt = _next_for_show(eps)
        if nxt and nxt["id"] not in in_progress:
            out.append(nxt)
        if len(out) >= limit:
            break
    return out


def recent_movies(limit: int = 24) -> list[dict]:
    return movies(sort="added", limit=limit)


def recent_shows(limit: int = 24) -> list[dict]:
    return shows(sort="added", limit=limit)


def genres(kind: str) -> list[str]:
    table = "items" if kind == "movie" else "shows"
    extra = "WHERE kind='movie'" if kind == "movie" else ""
    found: dict[str, int] = {}
    for r in db.query(f"SELECT genres FROM {table} {extra}"):
        for g in r["genres"] or []:
            found[g] = found.get(g, 0) + 1
    return [g for g, _ in sorted(found.items(), key=lambda kv: -kv[1])]


def home() -> dict:
    rows = []
    if cw := continue_watching():
        rows.append({"id": "continue", "title": "Continue Watching", "style": "landscape", "items": cw})
    if nu := next_up():
        rows.append({"id": "nextup", "title": "Next Up", "style": "landscape", "items": nu})
    if rm := recent_movies():
        rows.append({"id": "recent-movies", "title": "Recently Added Movies", "style": "poster", "items": rm})
    if rs := recent_shows():
        rows.append({"id": "recent-shows", "title": "Recently Added TV", "style": "poster", "items": rs})
    for g in genres("movie")[:4]:
        items = movies(sort="rating", genre=g, limit=24)
        if len(items) >= 4:
            rows.append({"id": f"genre-{g}", "title": f"{g} Movies", "style": "poster", "items": items})

    hero = [x for x in (cw[:2] if cw else []) + (rm or [])[:6] + (rs or [])[:4] if x.get("backdrop")][:6]
    return {"hero": hero, "rows": rows}


def search(q: str, limit: int = 40) -> dict:
    like = f"%{q}%"
    movies_ = [item_summary(r) for r in db.query(
        f"SELECT {ITEM_COLS} FROM {ITEM_FROM} WHERE i.kind='movie' AND i.title LIKE ? ORDER BY i.sort_title LIMIT ?",
        (like, limit))]
    shows_ = [show_summary(r) for r in db.query(
        f"SELECT {SHOW_COLS} FROM {SHOW_FROM} WHERE sh.title LIKE ? GROUP BY sh.id ORDER BY sh.sort_title LIMIT ?",
        (like, limit))]
    eps = [item_summary(r) for r in db.query(
        f"SELECT {ITEM_COLS} FROM {ITEM_FROM} WHERE i.kind='episode' AND i.title LIKE ? LIMIT ?", (like, limit))]
    return {"movies": movies_, "shows": shows_, "episodes": eps}


def stats() -> dict:
    return {
        "movies": db.one("SELECT COUNT(*) AS n FROM items WHERE kind='movie'")["n"],
        "shows": db.one("SELECT COUNT(*) AS n FROM shows")["n"],
        "episodes": db.one("SELECT COUNT(*) AS n FROM items WHERE kind='episode'")["n"],
    }
