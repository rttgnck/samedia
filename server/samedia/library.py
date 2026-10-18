"""Read-side library queries and JSON shapes sent to the TV.

Every query runs for a viewer profile (`Viewer`): watch progress is per profile, titles
the profile hid are left out, and a kids profile only sees kid-safe age ratings.
"""

from dataclasses import dataclass

from . import db
from .metadata import KIDS_CERTIFICATIONS
from .playback import channel_label


@dataclass(frozen=True)
class Viewer:
    profile_id: str = db.DEFAULT_PROFILE
    kids: bool = False


ITEM_COLS = ("i.id, i.kind, i.title, i.year, i.show_id, i.season, i.episode, i.episode_end, i.plot, i.tagline, "
             "i.rating, i.genres, i.poster, i.backdrop, i.thumb, i.duration, i.media, i.added_at, "
             "i.certification, i.collection_id, i.director, i.cast_members, "
             "p.position, p.watched, p.play_count, p.updated_at AS progress_at, "
             "s.title AS show_title, s.poster AS show_poster, s.backdrop AS show_backdrop, "
             "s.certification AS show_certification")
ITEM_FROM = ("items i LEFT JOIN progress p ON p.item_id = i.id AND p.profile_id = :pid "
             "LEFT JOIN shows s ON s.id = i.show_id")

_HIDDEN = "(SELECT target_id FROM hidden WHERE profile_id = :pid)"
_KIDS_LIST = ", ".join(f"'{c}'" for c in KIDS_CERTIFICATIONS)   # constants, safe to inline


def _item_visible(v: Viewer) -> str:
    sql = (f"i.id NOT IN {_HIDDEN} AND COALESCE(i.show_id, '') NOT IN {_HIDDEN} "
           f"AND COALESCE(i.collection_id, '') NOT IN {_HIDDEN}")
    if v.kids:
        # Episodes are rated through their show
        sql += (f" AND COALESCE(CASE WHEN i.kind = 'episode' THEN s.certification ELSE i.certification END, '') "
                f"IN ({_KIDS_LIST})")
    return sql


def _show_visible(v: Viewer) -> str:
    sql = f"sh.id NOT IN {_HIDDEN}"
    if v.kids:
        sql += f" AND COALESCE(sh.certification, '') IN ({_KIDS_LIST})"
    return sql


def _p(v: Viewer, **extra) -> dict:
    return {"pid": v.profile_id, **extra}


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
        "certification": r.get("show_certification") if is_ep else r.get("certification"),
    }
    if r.get("collection_id"):
        out["collection_id"] = r["collection_id"]
    if is_ep:
        out.update(show_id=r["show_id"], show_title=r.get("show_title"), season=r.get("season"),
                   episode=r.get("episode"), episode_end=r.get("episode_end"))
    return out


def item_detail_extras(r: dict) -> dict:
    """Fields only the detail screen needs."""
    return {"tagline": r.get("tagline"), "director": r.get("director"), "cast": r.get("cast_members") or []}


def show_summary(r: dict) -> dict:
    return {
        "id": r["id"], "kind": "show", "title": r["title"], "year": r.get("year"), "plot": r.get("plot"),
        "rating": r.get("rating"), "genres": r.get("genres") or [],
        "poster": _art(r["id"], r.get("poster"), "poster"),
        "backdrop": _art(r["id"], r.get("backdrop"), "backdrop"),
        "episode_count": r.get("episode_count"), "unwatched": r.get("unwatched"),
        "added_at": r.get("last_added") or r.get("added_at"),
        "certification": r.get("certification"),
        "cast": r.get("cast_members") or [],
    }


def get_item(item_id: str, v: Viewer = Viewer()) -> dict | None:
    return db.one(f"SELECT {ITEM_COLS}, i.path, i.sidecar_subs FROM {ITEM_FROM} WHERE i.id = :id",
                  _p(v, id=item_id))


SHOW_COLS = ("sh.*, COUNT(i.id) AS episode_count, "
             "SUM(CASE WHEN COALESCE(p.watched,0)=0 THEN 1 ELSE 0 END) AS unwatched, MAX(i.added_at) AS last_added")
SHOW_FROM = ("shows sh JOIN items i ON i.show_id = sh.id "
             "LEFT JOIN progress p ON p.item_id = i.id AND p.profile_id = :pid")


MOVIE_SORTS = {"title": "i.sort_title ASC", "added": "i.added_at DESC", "year": "i.year DESC, i.sort_title",
               "rating": "i.rating DESC, i.sort_title"}
SHOW_SORTS = {"title": "sh.sort_title ASC", "added": "last_added DESC", "year": "sh.year DESC, sh.sort_title",
              "rating": "sh.rating DESC, sh.sort_title"}


def movies(v: Viewer, sort: str = "title", genre: str | None = None, unwatched: bool = False,
           offset: int = 0, limit: int = 5000, group: bool = False) -> list[dict]:
    where, params = ["i.kind='movie'", _item_visible(v)], _p(v, limit=limit, offset=offset)
    if genre:
        where.append("i.genres LIKE :genre")
        params["genre"] = f'%"{genre}"%'
    if unwatched:
        where.append("COALESCE(p.watched,0)=0")
    rows = db.query(f"SELECT {ITEM_COLS} FROM {ITEM_FROM} WHERE {' AND '.join(where)} "
                    f"ORDER BY {MOVIE_SORTS.get(sort, MOVIE_SORTS['title'])} LIMIT :limit OFFSET :offset", params)
    items = [item_summary(r) for r in rows]
    return _group_collections(items, sort) if group else items


def _group_collections(items: list[dict], sort: str) -> list[dict]:
    """Fold movies of the same collection into one collection card (2+ visible members)."""
    members: dict[str, list[dict]] = {}
    for it in items:
        if it.get("collection_id"):
            members.setdefault(it["collection_id"], []).append(it)
    multi = {cid for cid, m in members.items() if len(m) >= 2}
    if not multi:
        return items
    info = {r["id"]: r for r in db.query(
        f"SELECT * FROM collections WHERE id IN ({','.join('?' for _ in multi)})", tuple(multi))}
    out, placed = [], set()
    for it in items:
        cid = it.get("collection_id")
        if cid not in multi or cid not in info:
            out.append(it)
        elif cid not in placed:
            placed.add(cid)
            out.append(collection_summary(info[cid], members[cid]))
    if sort == "title":
        out.sort(key=lambda x: x.get("sort_title") or (x["title"] or "").lower())
    return out


def collection_summary(c: dict, movies_: list[dict]) -> dict:
    by_year = sorted(movies_, key=lambda m: (m.get("year") or 0, m["title"]))
    first = by_year[0] if by_year else {}
    years = [m["year"] for m in by_year if m.get("year")]
    return {
        "id": c["id"], "kind": "collection", "title": c["name"], "sort_title": c["sort_title"],
        "poster": _art(c["id"], c.get("poster"), "poster") or first.get("poster"),
        "backdrop": _art(c["id"], c.get("backdrop"), "backdrop") or first.get("backdrop"),
        "item_count": len(movies_),
        "year": years[-1] if years else None,
        "years": f"{years[0]}–{years[-1]}" if len(set(years)) > 1 else (str(years[0]) if years else None),
        "unwatched": sum(1 for m in movies_ if not m["watched"]),
        "plot": c.get("plot") or f"{len(movies_)} movies",
        "added_at": max((m.get("added_at") or 0) for m in movies_) if movies_ else None,
        "rating": max((m.get("rating") or 0) for m in movies_) or None if movies_ else None,
        "genres": [],
    }


def collection_detail(v: Viewer, collection_id: str) -> dict | None:
    c = db.one("SELECT * FROM collections WHERE id = ?", (collection_id,))
    if not c:
        return None
    rows = db.query(f"SELECT {ITEM_COLS} FROM {ITEM_FROM} WHERE i.collection_id = :cid AND {_item_visible(v)} "
                    "ORDER BY i.year, i.sort_title", _p(v, cid=collection_id))
    items = [item_summary(r) for r in rows]
    out = collection_summary(c, items)
    out["items"] = items
    return out


def shows(v: Viewer, sort: str = "title", genre: str | None = None, offset: int = 0, limit: int = 5000) -> list[dict]:
    where, params = [_show_visible(v)], _p(v, limit=limit, offset=offset)
    if genre:
        where.append("sh.genres LIKE :genre")
        params["genre"] = f'%"{genre}"%'
    rows = db.query(f"SELECT {SHOW_COLS} FROM {SHOW_FROM} WHERE {' AND '.join(where)} GROUP BY sh.id "
                    f"ORDER BY {SHOW_SORTS.get(sort, SHOW_SORTS['title'])} LIMIT :limit OFFSET :offset", params)
    return [show_summary(r) for r in rows]


def show_detail(v: Viewer, show_id: str) -> dict | None:
    row = db.one(f"SELECT {SHOW_COLS} FROM {SHOW_FROM} WHERE sh.id = :sid GROUP BY sh.id", _p(v, sid=show_id))
    if not row:
        return None
    eps = [item_summary(r) for r in db.query(
        f"SELECT {ITEM_COLS} FROM {ITEM_FROM} WHERE i.show_id = :sid ORDER BY i.season, i.episode",
        _p(v, sid=show_id))]
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


def next_episode(v: Viewer, item: dict) -> dict | None:
    if item["kind"] != "episode":
        return None
    row = db.one(f"SELECT {ITEM_COLS} FROM {ITEM_FROM} WHERE i.show_id = :sid AND "
                 "(i.season > :season OR (i.season = :season AND i.episode > :ep)) AND i.season != 0 "
                 "ORDER BY i.season, i.episode LIMIT 1",
                 _p(v, sid=item["show_id"], season=item["season"], ep=item["episode"]))
    return item_summary(row) if row else None


def continue_watching(v: Viewer, limit: int = 20) -> list[dict]:
    rows = db.query(f"SELECT {ITEM_COLS} FROM {ITEM_FROM} WHERE p.position > 60 AND p.watched = 0 "
                    f"AND {_item_visible(v)} ORDER BY p.updated_at DESC LIMIT :limit", _p(v, limit=limit))
    return [item_summary(r) for r in rows]


def next_up(v: Viewer, limit: int = 20) -> list[dict]:
    active = db.query("SELECT i.show_id, MAX(p.updated_at) AS last FROM progress p JOIN items i ON i.id = p.item_id "
                      "JOIN shows sh ON sh.id = i.show_id "
                      f"WHERE p.profile_id = :pid AND i.kind='episode' AND p.watched = 1 AND {_show_visible(v)} "
                      "GROUP BY i.show_id ORDER BY last DESC LIMIT :limit", _p(v, limit=limit * 2))
    out = []
    in_progress = {c["id"] for c in continue_watching(v, 100)}
    for a in active:
        eps = [item_summary(r) for r in db.query(
            f"SELECT {ITEM_COLS} FROM {ITEM_FROM} WHERE i.show_id = :sid ORDER BY i.season, i.episode",
            _p(v, sid=a["show_id"]))]
        nxt = _next_for_show(eps)
        if nxt and nxt["id"] not in in_progress:
            out.append(nxt)
        if len(out) >= limit:
            break
    return out


def genres(v: Viewer, kind: str) -> list[str]:
    source = movies(v) if kind == "movie" else shows(v)
    found: dict[str, int] = {}
    for r in source:
        for g in r["genres"] or []:
            found[g] = found.get(g, 0) + 1
    return [g for g, _ in sorted(found.items(), key=lambda kv: -kv[1])]


def collections(v: Viewer) -> list[dict]:
    return [x for x in movies(v, sort="title", group=True) if x["kind"] == "collection"]


def home(v: Viewer) -> dict:
    """Shelves for the home Cover Flow, most personal first."""
    shelves = []
    if cw := continue_watching(v):
        shelves.append({"id": "continue", "title": "Continue Watching", "items": cw})
    if nu := next_up(v):
        shelves.append({"id": "nextup", "title": "Next Up", "items": nu})
    if rm := movies(v, sort="added", limit=30):
        shelves.append({"id": "recent-movies", "title": "New Movies", "items": rm})
    if rs := shows(v, sort="added", limit=30):
        shelves.append({"id": "recent-shows", "title": "New TV", "items": rs})
    if cols := collections(v):
        shelves.append({"id": "collections", "title": "Collections", "items": cols})
    for g in genres(v, "movie")[:4]:
        items = movies(v, sort="rating", genre=g, limit=30)
        if len(items) >= 4:
            shelves.append({"id": f"genre-{g}", "title": g, "items": items})
    # "rows" kept for TV apps from before Cover Flow home
    return {"shelves": shelves, "rows": shelves,
            "hero": [x for x in (cw[:2] if cw else []) + (rm or [])[:6] if x.get("backdrop")][:6]}


def search(v: Viewer, q: str, limit: int = 40) -> dict:
    params = _p(v, like=f"%{q}%", limit=limit)
    movies_ = [item_summary(r) for r in db.query(
        f"SELECT {ITEM_COLS} FROM {ITEM_FROM} WHERE i.kind='movie' AND i.title LIKE :like AND {_item_visible(v)} "
        "ORDER BY i.sort_title LIMIT :limit", params)]
    shows_ = [show_summary(r) for r in db.query(
        f"SELECT {SHOW_COLS} FROM {SHOW_FROM} WHERE sh.title LIKE :like AND {_show_visible(v)} "
        "GROUP BY sh.id ORDER BY sh.sort_title LIMIT :limit", params)]
    eps = [item_summary(r) for r in db.query(
        f"SELECT {ITEM_COLS} FROM {ITEM_FROM} WHERE i.kind='episode' AND i.title LIKE :like AND {_item_visible(v)} "
        "LIMIT :limit", params)]
    return {"movies": movies_, "shows": shows_, "episodes": eps}


# ── hidden titles ───────────────────────────────────────────────────

def target_kind(target_id: str) -> str | None:
    if db.one("SELECT id FROM items WHERE id = ?", (target_id,)):
        return "item"
    if db.one("SELECT id FROM shows WHERE id = ?", (target_id,)):
        return "show"
    if db.one("SELECT id FROM collections WHERE id = ?", (target_id,)):
        return "collection"
    return None


def hidden(v: Viewer) -> list[dict]:
    out = []
    for h in db.query("SELECT target_id FROM hidden WHERE profile_id = ? ORDER BY created_at DESC", (v.profile_id,)):
        tid = h["target_id"]
        if r := get_item(tid, v):
            out.append(item_summary(r))
        elif r := db.one(f"SELECT {SHOW_COLS} FROM {SHOW_FROM} WHERE sh.id = :sid GROUP BY sh.id", _p(v, sid=tid)):
            out.append(show_summary(r))
        elif c := db.one("SELECT * FROM collections WHERE id = ?", (tid,)):
            rows = db.query(f"SELECT {ITEM_COLS} FROM {ITEM_FROM} WHERE i.collection_id = :cid", _p(v, cid=tid))
            out.append(collection_summary(c, [item_summary(r) for r in rows]))
    return out


def stats() -> dict:
    return {
        "movies": db.one("SELECT COUNT(*) AS n FROM items WHERE kind='movie'")["n"],
        "shows": db.one("SELECT COUNT(*) AS n FROM shows")["n"],
        "episodes": db.one("SELECT COUNT(*) AS n FROM items WHERE kind='episode'")["n"],
        "collections": db.one("SELECT COUNT(*) AS n FROM collections")["n"],
    }
