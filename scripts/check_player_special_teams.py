"""Check our power-play and shorthanded numbers per skater against the NHL's player reports.

Run from the repo root with the `nhl` conda environment active, after build_base_tables.py,
build_season_totals.py and ingest_reference.py:

    python scripts/check_player_special_teams.py --season 2025

Per skater (all teams added up) it compares, for the power play and for shorthanded play, goals,
assists (primary and secondary), points, shots on goal, shot attempts, time on ice and the on-ice
goals per 60 with the NHL's skater power-play and penalty-kill reports
(data/raw/season=YYYY/reference/skater_powerplay.json.gz and skater_penaltykill.json.gz).
Also compares the boxscore's power-play goals (every game) with the NHL's.

Our strength numbers come from player_game_strength, which has only the games with shift data, so a
skater who played in a game with no shift data is low. Each line therefore shows all skaters and, on
the right, only the skaters with shift data for every game they played (games included equals games
played in player_season_advanced). Skaters in the NHL's report with no power-play or shorthanded row
of ours count as zero for us. The NHL's individual shot attempts are tried three ways (all four
kinds of attempt, without blocks, without misses) to find the one it uses. The per-60 goals are
worked out with the NHL's own seconds, so they test the goal counts and not the time. For goals, assists, points and
shots a second line, "from situation code", counts them from the play-by-play with the strength of each
goal or shot taken from the NHL's situation code (all games, no shifts needed), for comparison. If the
built table data/metrics/season=YYYY/player_season_special_teams.parquet exists it is checked the same way
at the end.
"""

import argparse
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "nhl_pipeline" / "transform"))

from special_teams import goal_assists, individual_counts_from_code  # noqa: E402

RAW_ROOT = REPO_ROOT / "data" / "raw"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
STAGING_ROOT = REPO_ROOT / "data" / "staging"
CODE_KEYS = ("goals", "assists", "assists_primary", "assists_secondary", "points", "shots")
STATE_COLUMNS = [
    "player_id", "strength", "seconds", "for_goal", "against_goal",
    "ind_goal", "ind_sog", "ind_miss", "ind_block", "assists_primary", "assists_secondary",
]
# NHL report field -> our key, per strength
COUNT_FIELDS = {
    "pp": {
        "ppGoals": "goals", "ppAssists": "assists", "ppPrimaryAssists": "assists_primary",
        "ppSecondaryAssists": "assists_secondary", "ppPoints": "points", "ppShots": "shots",
        "ppIndividualSatFor": "attempts", "ppTimeOnIce": "seconds",
    },
    "sh": {
        "shGoals": "goals", "shAssists": "assists", "shPrimaryAssists": "assists_primary",
        "shSecondaryAssists": "assists_secondary", "shPoints": "points", "shShots": "shots",
        "shIndividualSatFor": "attempts", "shTimeOnIce": "seconds",
    },
}
# NHL per-60 field -> (strength, our on-ice key)
PER_60_FIELDS = {"ppGoalsForPer60": ("pp", "gf"), "ppGoalsAgainstPer60": ("sh", "ga")}
SECONDS_FIELD = {"pp": "ppTimeOnIce", "sh": "shTimeOnIce"}
# NHL attempt fields -> other ways of counting our attempts to try besides 'attempts'
ATTEMPT_VARIANTS = {"ppIndividualSatFor": ("fenwick", "goal_shot_block"), "shIndividualSatFor": ("fenwick", "goal_shot_block")}
REPORTS = {"pp": "skater_powerplay", "sh": "skater_penaltykill"}


def special_team_counts(rows):
    """{player_id: {'pp': Counter, 'sh': Counter}} from player_game_strength rows.

    Keys: goals, assists_primary, assists_secondary, assists, points, shots (shots on goal, goals
    included), attempts (goals, shots on goal, misses and blocks), fenwick (without blocks),
    goal_shot_block (without misses), seconds, and the on-ice goals
    for and against, gf and ga.
    """
    out = defaultdict(lambda: {"pp": Counter(), "sh": Counter()})
    for row in rows:
        if row["strength"] not in ("pp", "sh"):
            continue
        counts = out[row["player_id"]][row["strength"]]
        primary, secondary = row["assists_primary"] or 0, row["assists_secondary"] or 0
        counts["goals"] += row["ind_goal"] or 0
        counts["assists_primary"] += primary
        counts["assists_secondary"] += secondary
        counts["assists"] += primary + secondary
        counts["points"] += (row["ind_goal"] or 0) + primary + secondary
        counts["shots"] += (row["ind_goal"] or 0) + (row["ind_sog"] or 0)
        counts["attempts"] += sum(row[c] or 0 for c in ("ind_goal", "ind_sog", "ind_miss", "ind_block"))
        counts["fenwick"] += sum(row[c] or 0 for c in ("ind_goal", "ind_sog", "ind_miss"))
        counts["goal_shot_block"] += sum(row[c] or 0 for c in ("ind_goal", "ind_sog", "ind_block"))
        counts["seconds"] += row["seconds"] or 0
        counts["gf"] += row["for_goal"] or 0
        counts["ga"] += row["against_goal"] or 0
    return out


def summarize(pairs):
    """pairs: list of (our value, NHL value, player id) -> exact, within 2, total ours, total NHL, worst gap."""
    diffs = [(ours - nhl, player) for ours, nhl, player in pairs]
    worst = max(diffs, key=lambda d: abs(d[0]), default=(0, None))
    return {
        "exact": sum(1 for d, _ in diffs if d == 0),
        "within_2": sum(1 for d, _ in diffs if abs(d) <= 2),
        "ours": sum(p[0] for p in pairs),
        "nhl": sum(p[1] for p in pairs),
        "worst": worst,
    }


def skaters_with_all_games(metrics):
    """Player ids whose games included in the on-ice stats equal their games played."""
    games, included = Counter(), Counter()
    for row in pq.read_table(
        metrics / "player_season_advanced.parquet", columns=["player_id", "kind", "situation", "games_played", "games_included"]
    ).to_pylist():
        if row["kind"] == "team" and row["situation"] == "all":
            games[row["player_id"]] += row["games_played"]
            included[row["player_id"]] += row["games_included"]
    return {p for p in games if games[p] == included[p]}


def by_player(code_counts):
    """{player_id: {'pp': Counter, 'sh': Counter}} from individual_counts_from_code (teams added up)."""
    out = defaultdict(lambda: {"pp": Counter(), "sh": Counter()})
    for (player_id, _, situation), counts in code_counts.items():
        out[player_id][situation].update(counts)
    return out


def load_code_counts(season):
    """Individual counts from the situation code, from shot_attempts and the goal events."""
    attempts = pq.read_table(
        METRICS_ROOT / f"season={season}" / "shot_attempts.parquet",
        columns=["game_id", "event_id", "attempt_type", "shooter_id", "team_id",
                 "skaters_for", "skaters_against", "goalie_for", "goalie_against"],
    ).to_pylist()
    events = pq.read_table(
        STAGING_ROOT / f"season={season}" / "events.parquet",
        columns=["game_id", "event_id", "event_type", "assist1_player_id", "assist2_player_id"],
    ).to_pylist()
    return by_player(individual_counts_from_code(attempts, goal_assists(events)))


def load_report(season, name):
    with gzip.open(RAW_ROOT / f"season={season}" / "reference" / f"{name}.json.gz", "rb") as handle:
        return {r["playerId"]: r for r in json.loads(handle.read())["data"]}


def main():
    parser = argparse.ArgumentParser(description="Check player power-play and shorthanded numbers.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    metrics = METRICS_ROOT / f"season={args.season}"

    rows = pq.read_table(metrics / "player_game_strength.parquet", columns=STATE_COLUMNS).to_pylist()
    ours = special_team_counts(rows)
    clean = skaters_with_all_games(metrics)
    code = load_code_counts(args.season)
    print(f"Season {args.season}: skaters with power-play or shorthanded rows in our tables: {len(ours)}; "
          f"skaters with shift data for every game played: {len(clean)}")

    def both(pairs):
        """Summary line for all skaters and for the clean ones."""
        a, c = summarize(pairs), summarize([x for x in pairs if x[2] in clean])
        return (f"exact {a['exact']:3d}/{len(pairs)}, within 2 {a['within_2']:3d}, ours {a['ours']} NHL {a['nhl']}, "
                f"worst {a['worst'][0]:+d} | clean: exact {c['exact']:3d}/{sum(1 for x in pairs if x[2] in clean)}, "
                f"within 2 {c['within_2']:3d}, ours {c['ours']} NHL {c['nhl']}, worst {c['worst'][0]:+d}")

    for strength, report_name in REPORTS.items():
        reference = load_report(args.season, report_name)
        players = list(reference)
        label = "Power play" if strength == "pp" else "Shorthanded"
        missing = [p for p in players if p not in ours]
        seconds_field = SECONDS_FIELD[strength]
        print(f"\n{label}: NHL skaters {len(reference)}; no row of ours for {len(missing)} of them "
              f"(their NHL time on ice adds up to {sum(reference[p].get(seconds_field) or 0 for p in missing)} s, "
              f"goals {sum(reference[p].get('ppGoals', reference[p].get('shGoals')) or 0 for p in missing)}); "
              f"ours only: {len(set(ours) - set(reference))}")
        for field, key in COUNT_FIELDS[strength].items():
            if any(field not in reference[p] for p in players):
                print(f"  {field:20s} the NHL report has no such field")
                continue
            print(f"  {field:20s} {both([(ours[p][strength][key], reference[p][field] or 0, p) for p in players])}")
            if key in CODE_KEYS:
                print(f"    from situation code {both([(code[p][strength][key], reference[p][field] or 0, p) for p in players])}")
            for variant in ATTEMPT_VARIANTS.get(field, ()):
                print(f"    as {variant:16s} {both([(ours[p][strength][variant], reference[p][field] or 0, p) for p in players])}")
        for field, (field_strength, key) in PER_60_FIELDS.items():
            if field_strength != strength:
                continue
            close = close_clean = 0
            # only skaters with time on ice: with none there is no rate to compare
            timed = [p for p in players if reference[p].get(seconds_field) and reference[p].get(field) is not None]
            for p in timed:
                value = ours[p][strength][key] * 3600 / reference[p][seconds_field]
                ok = abs(value - reference[p][field]) <= 0.011
                close += ok
                close_clean += ok and p in clean
            print(f"  {field:20s} {close} of {len(timed)} skaters with time on ice match to 2 decimals using the NHL's "
                  f"seconds ({close_clean} of {len([p for p in timed if p in clean])} clean)")

    built_path = metrics / "player_season_special_teams.parquet"
    if built_path.exists():
        built = defaultdict(lambda: {"pp": Counter(), "sh": Counter()})
        for row in pq.read_table(built_path).to_pylist():
            if row["kind"] == "team":
                for key in ("goals", "assists", "assists_primary", "assists_secondary", "points", "shots", "seconds"):
                    built[row["player_id"]][row["situation"]][key] += row[key]
        print("\nThe built table (player_season_special_teams, team rows added up) against the NHL's reports:")
        for strength, report_name in REPORTS.items():
            reference = load_report(args.season, report_name)
            players = list(reference)
            for field, key in COUNT_FIELDS[strength].items():
                if key == "attempts" or field not in reference[players[0]]:
                    continue
                result = summarize([(built[p][strength][key], reference[p][field] or 0, p) for p in players])
                print(f"  {field:20s} exact {result['exact']:3d}/{len(players)}, within 2 {result['within_2']:3d}, "
                      f"ours {result['ours']} NHL {result['nhl']}, worst {result['worst'][0]:+d}")

    totals = pq.read_table(metrics / "player_season_totals.parquet", columns=["player_id", "power_play_goals"]).to_pylist()
    box = Counter()
    for row in totals:
        box[row["player_id"]] += row["power_play_goals"] or 0
    reference = load_report(args.season, "skater_powerplay")
    compared = [p for p in reference if p in box]
    result = summarize([(box[p], reference[p]["ppGoals"] or 0, p) for p in compared])
    print(f"\nBoxscore power-play goals against the NHL's ppGoals: exact {result['exact']} of {len(compared)}; "
          f"total ours {result['ours']}, NHL {result['nhl']}; largest gap {result['worst'][0]:+d} (player {result['worst'][1]})")


if __name__ == "__main__":
    main()