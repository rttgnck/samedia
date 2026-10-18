from pathlib import Path

import pytest

from samedia.naming import parse, split_title_year

ROOT = Path("/media")


@pytest.mark.parametrize("rel, title, year", [
    ("Movies/The Matrix (1999)/The.Matrix.1999.2160p.UHD.BluRay.REMUX.HDR.HEVC.Atmos-GRP.mkv", "The Matrix", 1999),
    ("Movies/Blade Runner 2049 (2017)/movie.mkv", "Blade Runner 2049", 2017),
    ("Movies/1917 (2019).mkv", "1917", 2019),
    ("Arrival.2016.1080p.WEB-DL.mkv", "Arrival", 2016),
    ("Movies/Heat/Heat.mkv", "Heat", None),
])
def test_movies(rel, title, year):
    p = parse(ROOT / rel, ROOT)
    assert (p.kind, p.title, p.year) == ("movie", title, year)


@pytest.mark.parametrize("rel, show, season, episode, end", [
    ("TV/Breaking Bad/Season 02/Breaking.Bad.S02E03.Bit.by.a.Dead.Bee.1080p.mkv", "Breaking Bad", 2, 3, None),
    ("TV/The Office (US)/Season 3/The Office S03E01E02.mkv", "The Office (US)", 3, 1, 2),
    ("TV/Doctor Who (2005)/Specials/Doctor.Who.S00E05.mkv", "Doctor Who", 0, 5, None),
    ("TV/Firefly/1x04 Shindig.avi", "Firefly", 1, 4, None),
    ("TV/Firefly/Season 1/04 - Shindig.mkv", "Firefly", 1, 4, None),
    ("Downloads/Severance.S02E01.Hello.Ms.Cobel.2160p.mkv", "Severance", 2, 1, None),
])
def test_episodes(rel, show, season, episode, end):
    p = parse(ROOT / rel, ROOT)
    assert p.kind == "episode"
    assert (p.show_title, p.season, p.episode, p.episode_end) == (show, season, episode, end)


def test_resolution_is_not_an_episode():
    assert parse(ROOT / "Movies/Some Film 2010 1920x1080.mkv", ROOT).kind == "movie"


def test_split_title_year_keeps_numeric_titles():
    assert split_title_year("2012") == ("2012", None)


def test_hidden_and_appledouble_files_are_ignored():
    from pathlib import Path
    from samedia.naming import is_ignored
    root = Path("/media")
    assert is_ignored(Path("/media/Movies/._Dune.Part.Two.2024.mkv"), root)
    assert is_ignored(Path("/media/.hidden.mkv"), root)
    assert not is_ignored(Path("/media/Movies/Dune.Part.Two.2024.mkv"), root)


def test_folder_per_movie_name_wins_over_abbreviated_file():
    from pathlib import Path
    from samedia.naming import parse
    root = Path("/m")
    p = Path("/m/Mission Impossible (1996)/MI.1996.1080p.mkv")
    assert (parse(p, root, folder_exclusive=True).title, parse(p, root, folder_exclusive=True).year) == ("Mission Impossible", 1996)
    # A shared folder ("Movies 2024") is not a title
    q = Path("/m/Movies 2024/Dune.Part.Two.2024.mkv")
    assert parse(q, root, folder_exclusive=False).title == "Dune Part Two"


import pytest as _pytest


@_pytest.mark.parametrize("rel,kind,title,year", [
    ("Earth 2 (1994)/Earth2_E01_First-Contact-Part1.mp4", "episode", "First Contact Part1", 1994),
    ("www.UIndex.org    -    Elio (2025)/Elio.2025.1080p.WEB.h264-ETHEL.mkv", "movie", "Elio", 2025),
    ("Terminator_2--Extended_Special_Edition [DTS] (h264-sickboy88).mkv", "movie", "Terminator 2", None),
    ("Timecrimes - Horror 2007 Eng Spa Multi-Subs 1080p [H264-mp4].mp4", "movie", "Timecrimes", 2007),
    ("Free Willy 2.English.Nordic sub.mkv", "movie", "Free Willy 2", None),
    # real titles that look like junk must survive
    ("The Net 1995.mkv", "movie", "The Net", 1995),
    ("The English Patient 1996.mkv", "movie", "The English Patient", 1996),
    ("WALL-E 2008 1080p.mkv", "movie", "WALL-E", 2008),
])
def test_messy_names(rel, kind, title, year):
    from pathlib import Path
    from samedia.naming import parse
    p = parse(Path("/m") / rel, Path("/m"), folder_exclusive=True)
    assert (p.kind, p.title, p.year) == (kind, title, year)


def test_tmdb_matching_variants():
    from samedia.metadata import _best_match, _query_variants

    def match(hits, title, year):
        return (_best_match(hits, title, year, "title", "release_date") or {}).get("title")
    assert "Zootopia 2" in _query_variants("Z00topia 2", 2025)
    assert "Free Willy" in _query_variants("Free Willy Havets forsvarer & Den gigantiske ålen", 1994)
    assert match([{"title": "The Mandalorian and Grogu", "release_date": "2026-05-22"}],
                 "Star Wars The Mandalorian And Grogu", 2026) == "The Mandalorian and Grogu"
    assert match([{"title": "Free Willy 2: The Adventure Home", "release_date": "1995-07-19"}],
                 "Free Willy 2", None) == "Free Willy 2: The Adventure Home"
    # no false friends
    assert match([{"title": "Alien Resurrection", "release_date": "1997-11-12"}], "Alien", None) is None
    assert match([{"title": "Star Wars", "release_date": "1977-05-25"}], "Star Wars The Mandalorian", 2026) is None
