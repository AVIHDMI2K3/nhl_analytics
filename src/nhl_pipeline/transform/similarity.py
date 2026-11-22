"""Phase 7: player similarity from the percentile table (pure logic, no file access).

Every player-season in the pool (percentiles.py) is one entry, described by its percentiles in the 29 stats of the
catalog. Two entries are compared only when they are in the same group (forwards with forwards, defensemen with
defensemen). The comparison gives every category the same weight, so the many shot-share stats cannot drown out
scoring, physical play or usage:

  gap of a category   root of the mean squared difference of the two entries' percentiles in the category's stats
                      (a stat either entry lacks is left out, a category with no stat left is left out)
  distance            root of the mean of the categories' squared gaps, in percentile points (0 to 100)
  similarity          100 - distance, so 100 is identical and 90 means the percentiles differ by about 10 points

Percentiles are ranks within each season, so entries from different seasons are comparable as "how good in his own
year" (a stat that league-wide moved up or down between seasons does not matter), but a rank cannot show how far apart
two players really are. `nearest` returns for each entry its closest entries in the same season and in all seasons.
A player's own other seasons are never matches (a player is always most like himself), so the list is
always other players.
"""

import heapq

CATEGORIES = {
    "scoring": [
        "goals_per_60",
        "assists_per_60",
        "points_per_60",
        "shots_per_60",
        "shooting_pct",
        "icf_per_60",
        "isf_per_60",
        "ig_per_60",
    ],
    "shot_share": ["cf_pct", "ff_pct", "sf_pct", "gf_pct", "cf_pct_rel", "ff_pct_rel", "sf_pct_rel", "gf_pct_rel"],
    "shot_volume": [
        "cf_per_60",
        "ca_per_60",
        "ff_per_60",
        "fa_per_60",
        "sf_per_60",
        "sa_per_60",
        "gf_per_60",
        "ga_per_60",
    ],
    "physical": ["hits_per_60", "blocks_per_60", "takeaways_per_60", "giveaways_per_60"],
    "usage": ["toi_per_game"],
}
MODES = ("same_season", "all_seasons")


def build_entries(percentile_rows):
    """[{'key': (season, player_id), name, team, position, group, 'percentiles': {stat: percentile}}] for the players
    in the pool, from the long rows of percentiles.build_percentile_rows."""
    entries = {}
    for row in percentile_rows:
        if not row["in_pool"]:
            continue
        key = (row["season"], row["player_id"])
        entry = entries.setdefault(
            key,
            {
                "key": key,
                "season": row["season"],
                "player_id": row["player_id"],
                "name": row["name"],
                "team": row["team"],
                "position": row["position"],
                "group": row["position_group"],
                "percentiles": {},
            },
        )
        if row["percentile"] is not None:
            entry["percentiles"][row["stat"]] = row["percentile"]
    return [entries[key] for key in sorted(entries)]


def category_gaps(a, b, categories=CATEGORIES):
    """{category: root mean squared percentile difference, or None when the two share no stat in it}."""
    gaps = {}
    for category, stats in categories.items():
        squares = [(a[s] - b[s]) ** 2 for s in stats if s in a and s in b]
        gaps[category] = (sum(squares) / len(squares)) ** 0.5 if squares else None
    return gaps


def similarity(gaps):
    """100 - the root of the mean squared category gap, or None when no category could be compared."""
    squares = [g * g for g in gaps.values() if g is not None]
    return 100 - (sum(squares) / len(squares)) ** 0.5 if squares else None


def nearest(entries, top_n=15, categories=CATEGORIES):
    """Rows of the `top_n` most similar entries for every entry, in both modes ('same_season', 'all_seasons').

    The neighbors are always other players: none of the entry's own seasons is included. Rank 1 is the most similar."""
    by_group = {}
    for entry in entries:
        by_group.setdefault(entry["group"], []).append(entry)

    rows = []
    for group_entries in by_group.values():
        for entry in group_entries:
            scored = []
            for other in group_entries:
                if other["player_id"] == entry["player_id"]:
                    continue
                gaps = category_gaps(entry["percentiles"], other["percentiles"], categories)
                score = similarity(gaps)
                if score is not None:
                    scored.append((score, other, gaps))
            for mode in MODES:
                pool = scored if mode == "all_seasons" else [s for s in scored if s[1]["season"] == entry["season"]]
                best = heapq.nlargest(top_n, pool, key=lambda s: (s[0], -s[1]["season"], -s[1]["player_id"]))
                for rank, (score, other, gaps) in enumerate(best, start=1):
                    row = {
                        "season": entry["season"],
                        "player_id": entry["player_id"],
                        "name": entry["name"],
                        "position_group": entry["group"],
                        "mode": mode,
                        "rank": rank,
                        "other_season": other["season"],
                        "other_player_id": other["player_id"],
                        "other_name": other["name"],
                        "other_team": other["team"],
                        "other_position": other["position"],
                        "similarity": score,
                    }
                    row.update({f"gap_{category}": gaps[category] for category in categories})
                    rows.append(row)
    return rows
