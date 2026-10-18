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
