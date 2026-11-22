"""Phase 7: percentile ranks of skaters for the pizza charts (pure logic, no file access).

A percentile says how a player ranks in his pool: 100 is the best of the pool and 50 the middle. The pool is the
players of the same group (forwards: C, L, R; defensemen: D) in the same season who played at least `min_minutes` of
5v5 hockey (default 600). Forwards are not split into centers and wingers, because listed centers often play wing.

  percentile  100 x (players with a worse value + half of those with the same value) / pool size, so the best player
              is near 100 and a tie shares its place. For a stat where lower is better (shot attempts against,
              giveaways) the order is reversed, so a bigger slice is always better.
  in_pool     whether the player himself reached the minimum. A player below it still gets a percentile, computed
              against the pool, and is marked in_pool = False so the app can say the sample is small.

Every stat in STATS gets a percentile (the charts show DEFAULT_CHART, a user can add the others). Stats come from
two tables: `display` (player_season_display, boxscore totals, all situations) and `advanced`
(player_season_advanced, 5v5 rows). One row per player is used: the combined row of a traded player, else his only row.
"""

FORWARDS = {"C", "L", "R", "LW", "RW", "F"}
GROUPS = ("F", "D")

# key, label, source table, column, higher is better, scale (the column is divided by it)
STATS = [
    ("goals_per_60", "Goals per 60", "display", "goals_per_60", True, 1),
    ("assists_per_60", "Assists per 60", "display", "assists_per_60", True, 1),
    ("points_per_60", "Points per 60", "display", "points_per_60", True, 1),
    ("shots_per_60", "Shots on goal per 60", "display", "shots_per_60", True, 1),
    ("shooting_pct", "Shooting %", "display", "shooting_pct", True, 1),
    ("hits_per_60", "Hits per 60", "display", "hits_per_60", True, 1),
    ("blocks_per_60", "Blocks per 60", "display", "blocks_per_60", True, 1),
    ("takeaways_per_60", "Takeaways per 60", "display", "takeaways_per_60", True, 1),
    ("giveaways_per_60", "Giveaways per 60 (fewer is better)", "display", "giveaways_per_60", False, 1),
    ("toi_per_game", "Time on ice per game (minutes)", "display", "toi_per_game_seconds", True, 60),
    ("icf_per_60", "Individual shot attempts per 60 (5v5)", "advanced", "icf_per_60", True, 1),
    ("isf_per_60", "Individual shots on goal per 60 (5v5)", "advanced", "isf_per_60", True, 1),
    ("ig_per_60", "Individual goals per 60 (5v5)", "advanced", "ig_per_60", True, 1),
    ("cf_pct", "Corsi % (5v5)", "advanced", "cf_pct", True, 1),
    ("ff_pct", "Fenwick % (5v5)", "advanced", "ff_pct", True, 1),
    ("sf_pct", "Shots on goal % (5v5)", "advanced", "sf_pct", True, 1),
    ("gf_pct", "Goals % (5v5)", "advanced", "gf_pct", True, 1),
    ("cf_pct_rel", "Relative Corsi % (5v5)", "advanced", "cf_pct_rel", True, 1),
    ("ff_pct_rel", "Relative Fenwick % (5v5)", "advanced", "ff_pct_rel", True, 1),
    ("sf_pct_rel", "Relative shots on goal % (5v5)", "advanced", "sf_pct_rel", True, 1),
    ("gf_pct_rel", "Relative goals % (5v5)", "advanced", "gf_pct_rel", True, 1),
    ("cf_per_60", "Shot attempts for per 60 (5v5)", "advanced", "cf_per_60", True, 1),
    ("ca_per_60", "Shot attempts against per 60 (5v5, fewer is better)", "advanced", "ca_per_60", False, 1),
    ("ff_per_60", "Unblocked attempts for per 60 (5v5)", "advanced", "ff_per_60", True, 1),
    ("fa_per_60", "Unblocked attempts against per 60 (5v5, fewer is better)", "advanced", "fa_per_60", False, 1),
    ("sf_per_60", "Shots on goal for per 60 (5v5)", "advanced", "sf_per_60", True, 1),
    ("sa_per_60", "Shots on goal against per 60 (5v5, fewer is better)", "advanced", "sa_per_60", False, 1),
    ("gf_per_60", "Goals for per 60 (5v5)", "advanced", "gf_per_60", True, 1),
    ("ga_per_60", "Goals against per 60 (5v5, fewer is better)", "advanced", "ga_per_60", False, 1),
]
STATS_BY_KEY = {stat[0]: stat for stat in STATS}
DEFAULT_CHART = {
    "F": [
        "goals_per_60",
        "assists_per_60",
        "cf_pct",
        "ff_pct",
        "cf_per_60",
        "ca_per_60",
        "cf_pct_rel",
        "takeaways_per_60",
    ],
    "D": [
        "goals_per_60",
        "assists_per_60",
        "cf_per_60",
        "ca_per_60",
        "cf_pct_rel",
        "blocks_per_60",
        "hits_per_60",
        "takeaways_per_60",
    ],
}


def position_group(position):
    """'D' for defensemen, 'F' for forwards, None for anything else (goalies are not in these tables)."""
    if position == "D":
        return "D"
    return "F" if position in FORWARDS else None


def one_row_per_player(rows):
    """{player id: the combined ('total') row of a traded player, else his only row}."""
    chosen = {}
    for row in rows:
        current = chosen.get(row["player_id"])
        if current is None or (row.get("kind") == "total" and current.get("kind") != "total"):
            chosen[row["player_id"]] = row
    return chosen


def percentile_rank(value, pool_values, higher_is_better=True):
    """0-100 rank of `value` in `pool_values` (ties share their place); None without a value or a pool."""
    if value is None or not pool_values:
        return None
    if higher_is_better:
        worse = sum(1 for v in pool_values if v < value)
    else:
        worse = sum(1 for v in pool_values if v > value)
    equal = sum(1 for v in pool_values if v == value)
    return 100 * (worse + equal / 2) / len(pool_values)


def stat_value(stat, display_row, advanced_row):
    _, _, source, column, _, scale = stat
    row = display_row if source == "display" else advanced_row
    value = None if row is None else row.get(column)
    return None if value is None else value / scale


def build_percentile_rows(season, display_rows, advanced_rows, min_minutes=600, stats=STATS):
    """Long rows, one per player and stat: value, percentile, pool size and whether he is in the pool.

    `display_rows` are player_season_display rows, `advanced_rows` the 5v5 rows of player_season_advanced."""
    display = one_row_per_player(display_rows)
    advanced = one_row_per_player(r for r in advanced_rows if r["situation"] == "5v5")

    players = {}
    for player_id, row in display.items():
        group = position_group(row["position"])
        if group is None:
            continue
        adv = advanced.get(player_id)
        minutes = adv["seconds"] / 60 if adv else 0
        players[player_id] = (row, adv, group, minutes, minutes >= min_minutes)

    pools = {}
    for player_id, (row, adv, group, _, in_pool) in players.items():
        if not in_pool:
            continue
        for stat in stats:
            value = stat_value(stat, row, adv)
            if value is not None:
                pools.setdefault((group, stat[0]), []).append(value)

    out = []
    for player_id in sorted(players):
        row, adv, group, minutes, in_pool = players[player_id]
        for key, label, _, _, higher, _ in stats:
            stat = STATS_BY_KEY.get(key) or next(s for s in stats if s[0] == key)
            value = stat_value(stat, row, adv)
            pool = pools.get((group, key), [])
            out.append(
                {
                    "season": season,
                    "player_id": player_id,
                    "name": row["name"],
                    "position": row["position"],
                    "position_group": group,
                    "team": row["team"],
                    "teams": row["teams"],
                    "minutes_5v5": round(minutes, 1),
                    "in_pool": in_pool,
                    "stat": key,
                    "label": label,
                    "value": value,
                    "percentile": percentile_rank(value, pool, higher),
                    "pool_size": len(pool),
                    "higher_is_better": higher,
                    "in_default_chart": key in DEFAULT_CHART[group],
                }
            )
    return out
