# Metrics specification

What each stat means, where it comes from and how it is calculated. The code follows this
file; if they disagree, one of them is wrong. Written for Phase 4; sections marked
*planned* are not built yet. The last section lists what is still to come.

## Scope

- Seasons 2023-24 onward, regular season only.
- Raw numbers: no score or venue adjustment yet (the running score is stored so it can be added).
- Two sources, never mixed in one number. Simple totals (goals, assists, hits, time on ice ...) and the
  rates built from them come from the NHL boxscore, which covers every game. Stats that depend on who
  was on the ice (Corsi, relative stats, strength splits) come from our own calculations and cover
  only games with NHL shift data (57 games in 2024-25 have none). The app shows both game counts.

## Building blocks

| Term | Meaning |
|---|---|
| Strength | From the skaters on the ice in a stint, seen from one team: real skaters are the skaters minus one when the goalie is off the ice. Equal is even strength (`ev`), more is power play (`pp`), fewer is shorthanded (`sh`). The NHL `situationCode` is only used to check this (see `docs/data_notes.md`). |
| Attempt | A goal, a shot on goal, a missed shot or a blocked shot. |
| Shooting team | The event's owner team. For a blocked shot this is the shooting team (checked by the build script). |
| For / against | For = the team that took the attempt, against = its opponent. On-ice "for" is the player's own team. |
| Time on ice (TOI) | Seconds, from cleaned shifts (Phase 3), checked against the NHL's season totals. |

Left out of every attempt count: shootout events, penalty shots, `failed-shot-attempt`.

## shot_attempts (built)

One row per attempt. Written to `data/metrics/season=YYYY/shot_attempts.parquet`.

| Column | Meaning |
|---|---|
| game_id, event_id, sort_order, period, period_type, seconds_in_period, game_seconds | Where in the game it happened |
| attempt_type | `goal`, `shot-on-goal`, `missed-shot`, `blocked-shot` |
| shooter_id | Scoring player for a goal, shooting player otherwise |
| team_id, opponent_team_id, is_home | Shooting team, its opponent, and whether the shooting team is at home |
| shot_type, zone_code | From the NHL; zone is from the shooting team's side |
| x_raw, y_raw | NHL coordinates as given |
| x, y | Turned so the shooting team always attacks toward positive x. Null when the NHL gives no coordinate or no defending side. Blocked shots have no useful location in the NHL data. |
| goalie_id, blocker_id | Goalie in net, and blocking player for blocked shots |
| blocker_is_teammate | True when the blocker is on the shooter's team (about 9% of blocks, 2.4% of all attempts in 2025); such blocks give the blocker no block credit |
| skaters_for, skaters_against, goalie_for, goalie_against | From `situationCode`, shooting team's view (goalie 0 means pulled) |
| score_for, score_against | Score just before the attempt |
| has_on_ice | False for games without shift data |
| matches_situation, uses_conflicting_shift | Phase 3 flags for the on-ice data at this event |
| skater_ids_for, skater_ids_against | Skaters on the ice for each side, from our shifts |

## Shot-based stats (definitions; built, see "Advanced on-ice stats")

All are sums over attempts. A player's on-ice stat counts the attempts that happened while he
was on the ice; off-ice is the team's total in the games he played minus his on-ice total, in the
same situation.

| Stat | Formula |
|---|---|
| CF, CA | Attempts for / against while on the ice (goals + shots on goal + misses + blocks) |
| FF, FA | The same without blocked shots |
| SF, SA | Shots on goal for / against (goals included) |
| GF, GA | Goals for / against |
| CF%, FF%, SF%, GF% | For / (for + against). Always computed from season sums, never by averaging game percentages. |
| Per 60 | count × 3600 / seconds on ice at that strength |
| Relative (Rel) | On-ice value minus off-ice value (CF% Rel = CF% − CF% off) |
| Individual: iCF, iFF, iSF, G | The player's own attempts, by shooter_id |
| Blocks | Blocked shots where the player is the blocker and the blocker is not a teammate of the shooter |

High-danger chances are not defined yet. They wait for the expected-goals model (after Phase 5),
which will use shot locations from this table.

## stints (built)

One row per stint: a stretch of one period in which nobody changes on the ice. Written to
`data/metrics/season=YYYY/stints.parquet`. Both lineups (skaters and goalies), each side's real
skaters and each side's strength.

- A stint starts at any shift start or end and covers [start, end). Stints never cross a period.
- Real skaters = skaters on the ice, minus one for a team with no goalie on the ice (the sixth
  skater is an extra attacker, so 6v5 with a pulled goalie is 5v5, not a power play).
- Strength per side: even (`ev`) if real skaters are equal, `pp` if more, `sh` if fewer.
- A stint of at most 2 seconds whose strength differs from the stints on both sides (which
  agree) takes their strength and real skater counts. Shift data is only accurate to about a
  second, so line changes can leave a team briefly with one skater too many or too few.
  Smoothing over 2 seconds was tested and is worse.

How it was chosen and checked (2023 and 2025 against the NHL's own season time on ice by
strength; all three seasons against the boxscore):

| Check | Result |
|---|---|
| Even-strength time vs NHL | 0.03-0.04% low |
| Power-play and shorthanded time vs NHL | 0.20-0.30% high (cause not found) |
| Power-play goals per player-game vs boxscore `power_play_goals` | 99.96-99.98% exact |
| Stint strength vs the NHL's situationCode at each shot attempt | 99.86-99.91% agree |

Raw skater counts and the situationCode on its own were tested and are far worse. The 57 games
in 2024-25 with no shift data have no stints.

## Base tables (built)

Counts and seconds only, so any total is a sum of rows. Ratios are made from sums later.
Written to `data/metrics/season=YYYY/`. Long tables: the wide tables for fans are made from
these later (see "Other sections").

- `player_game_strength`: one row per game, skater and state.
- `team_game_strength`: the same for a team, used for off-ice numbers (team minus on-ice).

A state is `strength` (`ev`, `pp`, `sh`), `skaters_for`, `skaters_against`, `goalies_for` and
`goalies_against`. A pulled goalie is its own state (goalies_for = 0), so empty-net time is not
mixed into 5v5.

| Column | Meaning |
|---|---|
| seconds | Time on ice in that state (team time on a team row) |
| for_goal, for_sog, for_miss, for_block, and the same with `against_` | Attempts while on the ice. They do not overlap: `sog` is a shot on goal that was not a goal. Corsi = all four, Fenwick = first three, shots on goal = goal + sog. |
| ind_goal, ind_sog, ind_miss, ind_block | The player's own attempts |
| blocks_made | Shots by the other team that the player blocked. A block of a teammate's shot gives no credit. |
| assists_primary, assists_secondary, hits_made, hits_taken, giveaways, takeaways, faceoff_wins, faceoff_losses, penalties_taken, penalties_drawn, penalty_minutes | Other counting stats from the events (see `event_stats.py`) |

An attempt goes to the stint that covers its second (goals end-inclusive, everything else
start-inclusive), and every skater in that stint gets it in his team's state. Goalies have no
skater row. Penalty shots and shootouts are not in the tables. Games without shift data have no
rows. Known differences from the NHL are in `docs/data_notes.md`.

Plus/minus (NHL rule) from the table: goals for at ev and sh, minus goals against at ev and pp.

## Skater season totals (built)

`player_season_totals`: one row per skater and team for the season, summed from the NHL boxscore
(`boxscore_players`), regular season only, goalies left out. Games played counts games with time on
ice; checked against the NHL's skater report it matches for every skater in all three seasons, and so
does total time on ice (to the second). Written by `build_season_totals.py`. Faceoff percentage is not
here: the boxscore gives only a per-game percentage, which cannot be added up.

The boxscore was compared with the NHL's official event summary pages for 60 random games (2,160
player-games): identical except two penalty-minute values (see `docs/data_notes.md`).

## Skater season display (built)

`player_season_display`: the fan-facing basic table, from `player_season_totals`. One row per player
and team in the order he joined each team, plus a combined `TOT` row for a traded player (kind `total`
or `team`). Rates (time on ice per game, shooting percentage, per-60 of goals, assists, points, shots,
hits, blocks, giveaways, takeaways) are worked out on each row from its own totals. Written by
`build_season_display.py`.

## Goalie season totals (built)

`goalie_season_totals`: one row per goalie and team, summed from the NHL boxscore, regular season only,
written by `build_season_totals.py`. A goalie who dressed and did not play has a row with 0 games.

| Column | Meaning |
|---|---|
| games_played | Games with time on ice |
| games_started | Games he started (boxscore `starter`) |
| wins, losses, ot_losses | From the boxscore decision: `W`, `L`, `O` (an overtime or shootout loss) |
| shots_against, saves, goals_against | Boxscore totals |
| even_strength_, power_play_, shorthanded_ + shots_against / goals_against | The same by strength. The boxscore gives shots by strength as "saves/shots" text; the shots are read from it |
| shutouts | Games in which he played all of his team's goalie time, allowed no goal and did not lose in regulation (a win, or a shootout loss: shootout goals are not goals against) |
| toi_seconds, pim | Time on ice (a shootout adds time) and penalty minutes |

Checked against the NHL's goalie summary (`scripts/check_goalie_totals.py`): every count above, time on
ice, save percentage and goals-against average match for every goalie in all three seasons. See
`docs/data_notes.md` for the shutout rule.

## Goalie season display (built)

`goalie_season_display`: the fan-facing table from `goalie_season_totals`, laid out like the skater
display (one row per goalie and team, plus a combined `TOT` row for a traded goalie). Rates are worked
out on each row from its own totals:

| Column | Meaning |
|---|---|
| save_pct | 100 x saves / shots against (0-100 scale). Also `even_strength_`, `power_play_` and `shorthanded_` versions from the strength totals |
| goals_against_avg | goals against x 3600 / time on ice |
| shots_against_per_60 | shots against x 3600 / time on ice |
| toi_per_game_seconds | time on ice / games played |

A rate is empty when its divisor is zero. High-danger save percentage and goals saved above expected
need the xG model and are not built.

## Advanced on-ice stats (built)

`player_season_advanced` and `team_season_advanced`, from the long base tables, for games with shift
data only. One row per situation: `all`, `ev` (all even strength), `5v5` (five skaters and a goalie
each side, no empty net), `pp`, `sh`.

| Column | Meaning |
|---|---|
| seconds | Time on ice in the situation |
| cf, ca | Corsi for / against: goals, shots on goal, misses and blocks while on the ice |
| ff, fa | Fenwick: goals, shots on goal and misses |
| sf, sa | Shots on goal (goals plus shots on goal) |
| gf, ga | Goals |
| icf, iff, isf, ig, blocks_made | The player's own attempts and blocks (player table only) |
| off_* | The team's counts in the games he played minus his on-ice counts (player table only) |
| *_pct | for / (for + against) |
| *_pct_rel | on-ice percentage minus off-ice percentage (player table only) |
| *_per_60 | count x 3600 / seconds |

Percentages and rates come from the sums. A traded player has a combined row and one row per team;
off-ice counts are per team and added for the combined row. The definition of off ice (the team's
numbers in games he played) is ours and is to be compared with Natural Stat Trick in Phase 5.
Checked: at 5v5 total Corsi for equals total Corsi against, and equals five times the teams' 5v5
attempts, exactly, in all three seasons; time on ice by strength agrees with the NHL's within the small
gaps in `docs/data_notes.md` for the games covered.

## Still planned

Power-play and penalty-kill percentages (need power-play opportunities counted from the penalty events and
checked), faceoff percentage, xG and high-danger chances including goalie quality-of-shot stats (after
Phase 5), lines and pairs, pizza charts and similarity.