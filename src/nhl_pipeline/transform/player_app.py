"""Phase 8: the skater table the Players page shows (pure logic, no file access).

One row per skater, season and kind ('team' = one team's rows, 'total' = the combined row of a player who changed
teams), joining four season tables on (season, player_id, kind, team_id):
  player_season_display          basic stats (kept as they are, all columns)
  player_season_advanced         the '5v5' row: on-ice shot attempts and goals, relative shares, individual shots
  player_season_special_teams    the 'pp' row (power play) and the 'sh' row (penalty kill, prefix pk_)
  player_season_faceoffs         the 'all' row (prefix fo_)
Columns are grouped the way the page shows them. 5v5 columns end in _5v5, power-play columns start with pp_,
penalty-kill columns with pk_ and faceoff columns with fo_, so no column can be mistaken for an
all-situations number. Seconds become minutes. Shares and rates are rounded to one decimal.

A player with no row in one of the other tables keeps None in those columns rather than being dropped.
"""

FACEOFF_SITUATION = "all"

# (output column, source column, "minutes" to turn seconds into minutes)
ADVANCED_5V5 = (
    ("minutes_5v5", "seconds", "minutes"), ("cf_5v5", "cf", None), ("ca_5v5", "ca", None),
    ("cf_pct_5v5", "cf_pct", None), ("cf_pct_rel_5v5", "cf_pct_rel", None), ("ff_pct_5v5", "ff_pct", None),
    ("sf_pct_5v5", "sf_pct", None), ("gf_5v5", "gf", None), ("ga_5v5", "ga", None), ("gf_pct_5v5", "gf_pct", None),
    ("cf_per_60_5v5", "cf_per_60", None), ("ca_per_60_5v5", "ca_per_60", None),
    ("icf_5v5", "icf", None), ("isf_5v5", "isf", None), ("ig_5v5", "ig", None),
    ("blocks_made_5v5", "blocks_made", None),
)
POWER_PLAY = (
    ("pp_minutes", "seconds", "minutes"), ("pp_goals", "goals", None), ("pp_assists", "assists", None),
    ("pp_points", "points", None), ("pp_shots", "shots", None), ("pp_points_per_60", "points_per_60", None),
    ("pp_team_share_pct", "team_share_pct", None),
)
PENALTY_KILL = (
    ("pk_minutes", "seconds", "minutes"), ("pk_goals", "goals", None), ("pk_points", "points", None),
    ("pk_ga", "ga", None), ("pk_ga_per_60", "ga_per_60", None), ("pk_team_share_pct", "team_share_pct", None),
)
FACEOFFS = (
    ("fo_faceoffs", "faceoffs", None), ("fo_wins", "faceoff_wins", None), ("fo_pct", "faceoff_pct", None),
)


def _key(row):
    return (row["season"], row["player_id"], row["kind"], row["team_id"])


def _value(row, source, how):
    value = row[source]
    if value is None:
        return None
    if how == "minutes":
        return round(value / 60, 1)
    return round(value, 1) if isinstance(value, float) else value


def _pick(spec, source_row):
    return {out: (_value(source_row, src, how) if source_row else None) for out, src, how in spec}


def build_player_rows(display, advanced, special, faceoffs):
    """Lists of row dicts from the four season tables. Returns one joined row per display row."""
    adv = {_key(r): r for r in advanced if r["situation"] == "5v5"}
    pp = {_key(r): r for r in special if r["situation"] == "pp"}
    pk = {_key(r): r for r in special if r["situation"] == "sh"}
    fo = {_key(r): r for r in faceoffs if r["situation"] == FACEOFF_SITUATION}
    rows = []
    for d in display:
        key = _key(d)
        row = dict(d)
        row.update(_pick(ADVANCED_5V5, adv.get(key)))
        row.update(_pick(POWER_PLAY, pp.get(key)))
        row.update(_pick(PENALTY_KILL, pk.get(key)))
        row.update(_pick(FACEOFFS, fo.get(key)))
        rows.append(row)
    rows.sort(key=lambda r: (-(r["points"] or 0), r["name"]))
    return rows