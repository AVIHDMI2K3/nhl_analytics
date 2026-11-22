"""Phase 6: the fan-facing line and defense-pair table (pure logic, no file access).

Turns the season rows of line_tables.season_unit_rows into the table the app reads: one row per unit with a readable
label, the players in reading order, and the rates. Only units with at least `min_seconds` together at 5v5 are kept
(default 60 minutes).

  unit_id   team abbreviation, type and the player ids sorted by id, e.g. 'ANA-line-8476460-8478398-8480014'. The
            same players on the same team always give the same id, in any season, so a unit can be followed across
            seasons through `season`.
  label     last names in reading order: a line is left wing, center, right wing ('Smith / Jones / Brown') with its
            one listed center in the middle, a pair is alphabetical. A last name shared by two players of
            the team gets a first initial.
  positions the listed positions in the same order, e.g. 'L-C-R'. A player's position is the one the display
            table gives him for that team. When a line has two players of one position they follow the order of the
            positions that exist (L, then C, then R), then name.
"""

POSITION_ORDER = {"L": 0, "C": 1, "R": 2}
MAX_MEMBERS = 3
PERCENT_COLUMNS = ("cf_pct", "ff_pct", "sf_pct", "gf_pct", "sh_pct", "sv_pct", "pdo")
PER_60_COLUMNS = ("cf_per_60", "ca_per_60", "gf_per_60", "ga_per_60")


def rounded(value, digits):
    return None if value is None else round(value, digits)


def unit_id(team_abbrev, unit_type, player_ids):
    return f"{team_abbrev}-{unit_type}-" + "-".join(str(p) for p in sorted(player_ids))


def last_name(full_name):
    """Everything after the first word ('Alex Newhook' -> 'Newhook', 'Mitch Del Zotto' -> 'Del Zotto')."""
    parts = (full_name or "").split()
    return " ".join(parts[1:]) if len(parts) > 1 else (parts[0] if parts else "")


def reading_order(player_ids, info, unit_type):
    """The ids of a unit in reading order. `info` maps a player id to (full name, position).

    A pair is by name. A line puts its one listed center in the middle and the two wingers on the sides, left wing
    before right wing (then name). With no center or with two or more, the listed order L, C, R (then name) is used."""

    def name_key(player_id):
        name = info.get(player_id, ("", None))[0]
        return last_name(name), name, player_id

    def position_key(player_id):
        position = info.get(player_id, ("", None))[1]
        return (POSITION_ORDER.get(position, len(POSITION_ORDER)),) + name_key(player_id)

    if unit_type != "line":
        return sorted(player_ids, key=name_key)
    centers = [p for p in player_ids if info.get(p, ("", None))[1] == "C"]
    if len(centers) == 1 and len(player_ids) == MAX_MEMBERS:
        wings = sorted((p for p in player_ids if p != centers[0]), key=position_key)
        return [wings[0], centers[0], wings[1]]
    return sorted(player_ids, key=position_key)


def short_names(player_ids, info, repeated):
    """Last names of the players; a name in `repeated` (shared on the team) gets the first initial."""
    names = []
    for player_id in player_ids:
        full = info.get(player_id, (str(player_id), None))[0]
        last = last_name(full) or full
        names.append(f"{full[0]}. {last}" if last in repeated and full and full != last else last)
    return names


def repeated_last_names(info_by_team):
    """The set of last names that two different players of one team share."""
    seen, repeated = {}, set()
    for player_id, (name, _) in info_by_team.items():
        last = last_name(name)
        if last in seen and seen[last] != player_id:
            repeated.add(last)
        seen.setdefault(last, player_id)
    return repeated


def build_unit_display(season_rows, info, abbrevs, min_seconds=3600, zone_starts=None):
    """Display rows for the units with at least `min_seconds` together, most time first within each team.

    `season_rows` come from line_tables.season_unit_rows, `info` is {(player_id, team_id): (full name, position)}
    and `abbrevs` {team_id: abbreviation}. `zone_starts` is
    {(team_id, unit_type, sorted player ids): {'oz', 'dz', 'nz'}}
    from zone_starts.season_zone_rows; a unit without faceoffs gets 0 and no start percentage."""
    by_team = {}
    for (player_id, team_id), value in info.items():
        by_team.setdefault(team_id, {})[player_id] = value
    rows = []
    for unit in season_rows:
        if unit["seconds"] < min_seconds:
            continue
        team_id, unit_type = unit["team_id"], unit["unit_type"]
        team_info = by_team.get(team_id, {})
        ordered = reading_order(unit["player_ids"], team_info, unit_type)
        repeated = repeated_last_names(team_info)
        members = {f"player_{i + 1}_id": (ordered[i] if i < len(ordered) else None) for i in range(MAX_MEMBERS)}
        row = {
            "unit_id": unit_id(abbrevs.get(team_id), unit_type, unit["player_ids"]),
            "team_id": team_id,
            "team": abbrevs.get(team_id),
            "unit_type": unit_type,
            "label": " / ".join(short_names(ordered, team_info, repeated)),
            "positions": "-".join((team_info.get(p, ("", None))[1] or "?") for p in ordered),
            "player_names": " / ".join(team_info.get(p, (str(p), None))[0] for p in ordered),
            **members,
            "games": unit["games"],
            "minutes": round(unit["seconds"] / 60, 1),
            "minutes_per_game": round(unit["seconds"] / 60 / unit["games"], 2) if unit["games"] else None,
        }
        zones = (zone_starts or {}).get((team_id, unit_type, tuple(sorted(unit["player_ids"]))), {})
        oz, dz, nz = (zones.get(name, 0) for name in ("oz", "dz", "nz"))
        row.update(
            {
                "oz_starts": oz,
                "dz_starts": dz,
                "nz_starts": nz,
                "oz_start_pct": rounded(100 * oz / (oz + dz), 1) if oz + dz else None,
            }
        )
        row.update({name: unit[name] for name in ("cf", "ca", "ff", "fa", "sf", "sa", "gf", "ga")})
        row.update({name: rounded(unit[name], 1) for name in PERCENT_COLUMNS})
        row.update({name: rounded(unit[name], 2) for name in PER_60_COLUMNS})
        rows.append(row)
    rows.sort(key=lambda r: (r["team"] or "", r["unit_type"], -r["minutes"]))
    return rows
