# Data notes: known issues, and how each is handled

A record of where our numbers can differ from the NHL's, and why. Numbers are from the
2023-24, 2024-25 and 2025-26 seasons as built so far (named 2023, 2024, 2025 in the code) and
should be refreshed when the data is rebuilt. Anything marked "cause not found" has been looked
at and not explained.

## Where the data comes from

All of it is the NHL's own web services, which are not officially documented and could change:
the schedule, play-by-play and boxscore come from `api-web.nhle.com`; the shift charts and the
season time-on-ice totals used for checking come from `api.nhle.com/stats`. Our checks compare
our numbers with the boxscore and the season totals. Agreement shows we reproduce the NHL's own
figures. It does not by itself show that those figures are right, and we do not know how the
NHL computes its boxscore fields from its other data.

**The boxscore was compared with the NHL's official event summary pages** (nhl.com
`htmlreports`, `ES` pages) for 60 random games, 20 per season, with
`scripts/compare_boxscore_to_nhl.py`: 2,160 player-games and 21,600 values (goals, assists,
plus/minus, penalty minutes, shots, hits, giveaways, takeaways, blocked shots, time on ice).
All matched except two penalty-minute values, where the boxscore had 10 more than the official
page (game 2024020913 player 8475231: 20 against 10; game 2023020130 player 8479325: 15 against
5). Both sources probably come from the same NHL database. Simple totals are therefore taken from
the boxscore; stats that depend on who was on the ice are calculated by us.

## Games left out

**57 games in 2024-25 have no shift data from the NHL** (game ids 2024021235 to 2024021291).
Without shifts there is no time on ice and no record of who was on the ice, so those games are
left out of every table built from stints: on-ice numbers and the rates built from them.
They are not partly included, so every on-ice stat in a season describes the same games. The
boxscore does cover these games (checked: all 57 are there with time on ice), so skater season
totals and games played match the NHL's. The advanced tables carry both `games_played` and
`games_included`, and the fan view must show them side by side and say why they differ. Our
2024-25 on-ice time is about 4% below the NHL's for the same reason.
`data/logs/base_tables_report_<season>.json` lists the games left out. The ingestion re-checks
them, and an HTML time-on-ice fallback is possible; if either fills them, rebuild.

**One game's shift chart held another game's shifts.** The chart for 2025020565 (NJD-BUF) also
had the shifts of SJS-VGK, 667 rows. Shifts by a team that is not in the game are removed.

## Time on ice

- **Shift rows are noisy** (exact copies, corrupted rows, rows that overlap). Cleaning keeps
  rows in shift-number order and drops any that overlap one already kept; the one exception is a
  goalie row that lasts a whole period, whose stretches no kept goalie row of the team covers are
  kept (see Shots and blocks). Total time on ice from our cleaned shifts against the NHL's
  season total (`scripts/check_reference_toi.py`): 2025: 818 of 940 skaters exact, 848 within 2 s, 41
  off by 3-10 s, 48 by 11-60 s, 3 by more than 60 s. 2023: 744 of 924 exact, 802 within 2 s, 52, 64 and
  6. Games played are equal for every skater. We never have fewer shifts than the NHL; 101 skaters (2025)
  and 177 (2023) have more, and for most of them (82 and 132) none of the extra shifts is flagged as
  conflicting. Merging overlapping shifts into one stretch gives the same exact counts, and where we
  differ we are almost always higher (2025: 86 higher, 6 lower). Cause not found. By strength
  (`scripts/check_base_tables.py`), skaters more than 60 s off: 2025: 28 even strength, 14 power play,
  10 shorthanded; 2023: 75, 45 and 28. 2024 is not comparable because of the 57 games with no shifts.
- **The season totals table (from the boxscore) matches the NHL's report exactly** for all skaters:
  924 (2023), 920 (2024) and 940 (2025) skaters, with the same games played and the same total time on
  ice, in total and per player (`scripts/check_season_totals.py`). That is a different number from the
  shift-based time above, which is what the advanced stats use.
- **By strength**, even-strength time is 0.02-0.04% below the NHL's, and power-play and
  shorthanded time is 0.17-0.26% above it (2025 and 2023; 2024 is not comparable because the
  NHL's totals include the 57 games with no shifts). Cause not found. Strength comes from the skaters on
  the ice, with one fewer for a team whose goalie is off the ice, and short blips of 2 seconds or
  less are smoothed.
- **Strength at events.** Power-play goals match the boxscore for 99.96-99.98% of player-games.

## Plus/minus

Our plus/minus, derived from goals by strength, matches the boxscore for 99.89% (2023), 99.96%
(2024) and 99.93% (2025) of player-games; the rest are off by exactly one (2023: 32 below and 22
above, 2024: 12 and 6, 2025: 16 and 15). Power-play-goal status differed from the boxscore for 17, 11
and 10 player-games in the three seasons (counted before the goalie fill, not repeated). Cause not found. Displayed plus/minus comes from the boxscore (the season totals table).

## Shots and blocks

- **Teammate blocks.** In 7.5% to 8.9% of blocked shots (3,363 in 2023, 3,716 in 2024, 3,617 in
  2025) the NHL lists a blocker on the shooter's own team. We count the attempt for the shooter's
  team and give nobody a block. Our blocks are then 11 to 34 below the boxscore per season, so the
  boxscore does not credit these either. Whether the attempt belongs to the shooter's team is to
  be checked against Natural Stat Trick in Phase 5.
- **Blocked shots** are 11-34 below the boxscore per season (99.93-99.98% of player-games
  exact), always by one. Cause not found.
- **A goalie as shooter** (12 in 2023, 18 in 2024, 35 in 2025). The attempt counts for the team
  and the skaters on the ice, and the goalie gets no row in the skater table. Probably a goalie
  shooting at an empty net, not yet verified. The cases are in the report's `cases`.
- **Shooter not on the ice by our shifts** (304, 142 and 128 attempts). In 2025, 125 of the 128
  are at the exact second a shift of his starts or ends. The shot is credited to him. The cases are in the
  report's `cases`.
- **Left out of attempts:** shootouts, penalty shots (in 2025 our goals are 6 below the
  boxscore, the number of penalty-shot goals we leave out) and two `failed-shot-attempt` events
  in 2025, whose meaning is not known.

## Other counting stats

- Assists, hits, giveaways and takeaways match the boxscore for every player-game, and faceoff
  percentage matches within 0.1 point.
- **Giveaways and takeaways are not comparable across seasons.** Skaters' giveaways in the
  boxscore were 19,192 in 2023, 36,824 in 2024 and 39,180 in 2025, and takeaways were 18,298,
  12,065 and 12,099. That is too large a change to be play, so it is probably a change in how
  the NHL records them (not verified).
- **Penalty minutes** differ from the boxscore for 16, 10 and 4 player-games, always by exactly
  10 minutes too few. Cause not found. The boxscore-against-official comparison found two cases where
  the boxscore has 10 more than the official page, so the boxscore may overcount some penalty
  minutes; our events were not yet checked against those two cases. A bench penalty has no
  penalized player and counts for nobody.

## Team basic stats

The team table (`team_season_basic`) takes the record and goals from the final scores in the games
table and the rest from the boxscore. Checked in all three seasons: wins equal losses plus overtime
losses, goals for equal goals against, points equal 2 x wins + overtime losses, and shots for equal
shots against. The standings agree with the NHL's final standings for the two seasons we could
check from memory (2023-24 and 2024-25).

- **Goals.** Final scores count a shootout-winning goal as one goal for the winner. After taking
  those off, the final scores are 8,086, 7,901 and 8,086 goals in the three seasons against 8,085,
  7,898 and 8,086 goals by skaters in the boxscore. Cause of the gaps of 1 and 3 not found.
- **Shots against** are the opponent skaters' shots on goal, so they include shots on an empty net.
  The goalies' own shots against in the boxscore are lower, by 9 to 25 per team in 2025-26. The
  NHL's play-by-play names the goalie in net on every shot and goal, and names none when the net was
  empty. Checked in 2025-26 (`scripts/diagnose_shots_against_gap.py`, 2,624 team-games):
  skaters' shots minus goalies' shots against equals the play-by-play's empty-net shots in 99.4% of
  team-games (492 against 508 in total). The boxscore itself is about 0.05% below the play-by-play:
  skaters' shots 73,022 against 73,062 events, goalies' shots against 72,530 against 72,554 events
  that name a goalie (24 goalie-games, each exactly one shot lower in the boxscore).
  **Cause (found, `scripts/diagnose_boxscore_vs_pbp.py`, 2025-26): a goal with no shot type.** All 30
  skater-games and all 24 goalie-games that differ have a goal event with no `shotType` in the
  play-by-play; none of the games that agree do. In each the boxscore is exactly one shot lower.
  The other features (a second shot within 2 s, overtime, the last seconds of a period) are in only a
  minority of the differing games (at most 13% of skater-games, 42% of goalie-games), so they cannot be
  the cause; no shot has missing coordinates and no goalie shot is involved. The 6 skater-games without a goalie-game are
  empty-net goals (checked: 24 of the 30 no-type goals name a goalie, 6 are on an empty net). Confirmed by `scripts/check_goal_shot_type_and_goalie_rows.py`: all 30 skater-games
  with such a goal are exactly one shot below the play-by-play and the other 47,201 match; for 9 of the 30 scorers
  the boxscore shows more goals than shots on goal. So the boxscore leaves out a goal that has no shot type from
  shots on goal. Our own shot counts use every goal as a shot on goal, so they are 30 above the boxscore in 2025-26.
  **Shift timing is not the cause of the boxscore gap.** Our shifts show 521 empty-net shots against
  508 in the play-by-play; the 13 extra are shots where the play-by-play names a goalie but our shifts
  show him off the ice. Verified: 72,541 of 72,554 shots (100.0%) have the named goalie on the ice in
  our stints. The 13 are in 4 games (2025020544, 2025021031, 2025021204, 2025021215) and every one falls
  inside a raw goalie row that runs for a whole period (2400-3600 or 3600-3900) and that cleaning
  dropped (why is not yet known). **Fix (in use):** `clean_shifts` keeps the stretches of a dropped period-long goalie row
  that no kept goalie row of the team covers (`fill_goalie_gaps` in `onice.py`, marked as conflicting).
  Original code against the fix, 2025: the named goalie is on the ice for 72,554 of 72,554 shots (72,541
  before); disagreements with the situationCode 2,449 (2,545); skaters more than 60 s off the NHL's time
  on ice, 28 (45) at even strength, 14 (22) on the power play, 10 (19) shorthanded; even strength -0.02%
  (-0.03%), power play and shorthanded +0.17% (+0.20%). Plus/minus, goals and shots per player-game did not
  change. 2023: skaters more than 60 s off 75 (99), 45 (68), 28 (46); power play +0.26% (+0.28%),
  shorthanded +0.26% (+0.30%). Unexplained: 503 of the 508 empty-net shots sit exactly on the first or
  last second of a kept goalie row. The 13 shots are in games 2025020544, 2025021031, 2025021204 and
  2025021215; the fill does not tell a missing goalie row from a real pull, so it could cover a pull in
  a period where a whole-period row was dropped (no sign of it in the numbers). The team-level gaps seen with
  a per-team comparison (exact for 17 of 32 teams, 1 to 4 off for the rest) are these small
  differences adding up.
- **Power-play goals.** Skaters' power-play goals exceed the goalies' power-play goals against by
  7, 9 and 8 over the three seasons. Cause not found.

## Goalie season stats

Goalie totals come from the boxscore only (`season_totals.build_goalie_season_totals`), one row per
goalie and team. Checked against the NHL's goalie summary (`scripts/check_goalie_totals.py`): for all
98, 103 and 98 goalies who played in 2023, 2024 and 2025, games played, games started, wins, losses,
overtime losses, shots against, saves, goals against and time on ice match exactly, and so do save
percentage (3 decimals) and goals-against average (2 decimals). The shots and goals by strength add up
to the totals in every row.

- **Games played** is the number of games with time on ice. Goalies who dressed and never played have a
  row with 0 games (19, 18 and 25 of them); the fan view hides them by default.
- **Decision.** `W` win, `L` regulation loss, `O` overtime or shootout loss.
- **Goalie time on ice** in a shootout game is more than 3600 s (the shootout time is added).
- **Shutout.** The NHL counts a shutout when the goalie played all of his team's goalie time, allowed no
  goal and did not lose in regulation, so a shootout loss in a 0-0 game counts too (the shootout goals
  are not goals against). Of five definitions tried, only this one matches every goalie in all three
  seasons (142, 151 and 111 shutouts). Without the shootout loss each season was one short (Sorokin 2023,
  Tarasov 2024, Daccord 2025).
- **Not included yet:** high-danger shots and goals saved above expected (need the xG model).

## Situation codes

The NHL's `situationCode` is not used for strength. It disagrees with the skaters on the ice at
about 3% of stoppages, and seven 2023 events have none. Strength from the skaters on the ice
agrees with the code at 99.86-99.91% of shot attempts.