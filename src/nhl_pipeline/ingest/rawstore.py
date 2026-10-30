"""Where raw files live on disk, and how they are written and read.

Layout, under the raw root (data/raw by default):

    season=2023/schedule/2023-10-01.json.gz         weekly schedule responses
    season=2023/game=2023020001/play-by-play.json.gz
    season=2023/game=2023020001/boxscore.json.gz
    season=2023/game=2023020001/shiftcharts.json.gz
    season=2023/reference/skater_timeonice.json.gz  the NHL's own season totals, for checking only

Each file holds the response bytes exactly as the NHL sent them, gzipped.
A game counts as loaded only when all three of its files exist, with one
exception: if the NHL answers the shift chart request with no rows at all, a
small marker file (shiftcharts.empty) records that, and the game counts as
loaded without shift data. The marker is not a raw response.
"""

import gzip
import json
import os
from pathlib import Path

ENDPOINT_NAMES = ("play-by-play", "boxscore", "shiftcharts")


def season_dir(raw_root, season):
    return Path(raw_root) / f"season={season}"


def schedule_path(raw_root, season, date):
    return season_dir(raw_root, season) / "schedule" / f"{date}.json.gz"


def reference_path(raw_root, season, name):
    """Season-level reference data from the NHL stats service, used only to check our numbers."""
    return season_dir(raw_root, season) / "reference" / f"{name}.json.gz"


def game_dir(raw_root, season, game_id):
    return season_dir(raw_root, season) / f"game={game_id}"


def raw_path(raw_root, season, game_id, name):
    return game_dir(raw_root, season, game_id) / f"{name}.json.gz"


def empty_marker_path(raw_root, season, game_id):
    return game_dir(raw_root, season, game_id) / "shiftcharts.empty"


def has_empty_marker(raw_root, season, game_id):
    return empty_marker_path(raw_root, season, game_id).exists()


def write_empty_marker(raw_root, season, game_id, checked_at):
    path = empty_marker_path(raw_root, season, game_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(checked_at + "\n", encoding="utf-8")


def clear_empty_marker(raw_root, season, game_id):
    empty_marker_path(raw_root, season, game_id).unlink(missing_ok=True)


def game_is_complete(raw_root, season, game_id):
    """True if the game has all three files, or two files plus the empty-shift marker."""
    for name in ENDPOINT_NAMES:
        if raw_path(raw_root, season, game_id, name).exists():
            continue
        if name == "shiftcharts" and has_empty_marker(raw_root, season, game_id):
            continue
        return False
    return True


def write_gz_atomic(path, content):
    """Write bytes gzipped, so an interrupted run never leaves a half-written file.

    The data goes to a temporary file first and is renamed into place only when
    complete. A file that exists at `path` is therefore always whole.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=6) as handle:
        handle.write(content)
    os.replace(tmp, path)


def read_gz_bytes(path):
    with gzip.open(path, "rb") as handle:
        return handle.read()


def read_gz_json(path):
    return json.loads(read_gz_bytes(path))