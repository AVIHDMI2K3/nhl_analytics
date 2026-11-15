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

## Games without API shifts

**57 games in 2024-25 have no shift data from the NHL's API** (game ids 2024021235 to 2024021291,
`shift_status` = `none_from_nhl`). Without shifts there is no time on ice and no record of who was
on the ice, and the 2024-25 on-ice numbers were about 4.4% below Natural Stat Trick's (6,963 of
159,107 team minutes, which is 57 games of about 122 team-minutes).

**They are filled from the NHL's HTML time-on-ice reports** (`nhl.com/scores/htmlreports`, the `TH`
and `TV` pages, the source Natural Stat Trick uses). `scripts/compare_html_shifts.py` compared the reports
with the API shifts on four games that have both: every shift had the same start and end second
(715, 738, 752 and 724 shifts). `scripts/fill_missing_shifts.py` reads the 57 games, matches players to
ids by jersey number through the boxscore, and checks that each player's total shift time is within
2 seconds of the boxscore's time on ice (all 57 games passed, 43,224 shifts). It adds the shifts to
`shifts.parquet`, sets the games' `shift_status` to `ok` and `shift_source` to `html_report`, and
keeps the first version of the files as `.bak`. The HTML reports have no shift id, so `shift_id` is empty
for these rows. After the fill, on-ice counts for the 57 games agree with `situationCode` like the rest
(99.39% of events in the season), plus/minus matches the boxscore for 99.96% of skater-games, and
all-situations league Corsi for matches Natural Stat Trick's 777,260 with 777,259. The staging step replaces
`games.parquet` and `shifts.parquet`, so run the fill again after re-staging a season. A game with no shifts
from either source would be left out of every table built from stints; the advanced tables carry both
`games_played` and `games_included` so the app can show them side by side.

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
  10 shorthanded; 2023: 75, 45 and 28. 2024 has not been rechecked here since its 57 games were filled.
- **The season totals table (from the boxscore) matches the NHL's report exactly** for all skaters:
  924 (2023), 920 (2024) and 940 (2025) skaters, with the same games played and the same total time on
  ice, in total and per player (`scripts/check_season_totals.py`). That is a different number from the
  shift-based time above, which is what the advanced stats use.
- **By strength**, even-strength time is 0.02-0.04% below the NHL's, and power-play and
  shorthanded time is 0.17-0.26% above it (2025 and 2023; 2024 is not comparable because the
  NHL's totals included the 57 games with no API shifts, which are now filled). Cause not found. Strength comes from the skaters on
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
  be checked against Natural Stat Trick in Phase 5. Checked: our Corsi totals match NST's within 0.01%, so NST counts these attempts for the shooter's team as we do.
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
- **Faceoffs** (`player_season_faceoffs`) are counted from the faceoff events with the strength from the
  situation code and the loser's zone flipped from the event's. Faceoff counts match the NHL's skater
  faceoff report for every skater in all three seasons (924, 920 and 940 skaters; 148,376, 148,592 and
  146,992 faceoffs) in total, by strength (even strength, power play, shorthanded) and by zone, and so do
  the win percentages to 0.1 point. Power-play and shorthanded faceoffs are the same total in each season
  (every faceoff has one skater on each side), as are offensive and defensive zone.
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
  7, 9 and 8 over the three seasons. The cause is goals scored into an empty net, which are charged
  to no goalie (see "Power play and shorthanded").

## Power play and shorthanded

`player_season_special_teams` takes the strength of each goal and shot from the NHL's `situationCode` on
the event (every game) and time on ice and on-ice goals from our shifts (games with shift data only; 57
games in 2024 have none). Checked with `scripts/check_player_special_teams.py` against the NHL's skater
power-play and penalty-kill reports, and with `scripts/diagnose_special_teams_goals.py` against the
goalies' boxscore numbers game by game.

- **Why the code for goals and shots.** Strength from the shifts is wrong for a few goals a season: in
  seven goals we inspected (`scripts/inspect_goal_strength.py`) the shifts showed an extra or missing
  skater at the goal's second (overtime line changes, a 7th skater in one game), or put the goal on the
  wrong side of a penalty expiring at that second (the NHL counts the power play from the penalty clock,
  not from who is on the ice yet), or showed six real skaters for a team that had pulled its goalie. The
  code was right in all seven. Over all goals with a goalie in net the code agrees with the goalies'
  boxscore numbers in every team-game for power-play goals (2,624, 2,510 and 2,624 team-games) and in all
  but 0, 1 and 2 for shorthanded goals (the remaining ones are penalty-shot goals, see below); the shifts
  were off in 16, 12 and 10 power-play team-games and 4, 2 and 3 shorthanded ones.
- **Against the NHL's player reports** (strength from the code): power-play goals, assists, primary and
  secondary assists and points match for every skater in all three seasons (924, 920 and 940), including
  2024 because the code does not need shifts; shorthanded assists match for every skater, and so do
  shorthanded goals and points once the penalty-shot goals are added (see below). Shots on goal match for 99% of skaters on the power play
  (916 of 924, 915 of 920, 935 of 940) and 98-99% shorthanded. Totals are equal or within a few.
  Strength from the shifts was exact for only 91-97% (and, before the 57 games were filled, not for skaters in them).
- **Boxscore power-play goals** match the NHL's skater report for every skater in all three seasons.
- **Goalies' numbers leave out empty-net goals.** A goal into an empty net is charged to no goalie, but
  the NHL's skater reports and the boxscore's skater goals count it. This is the cause of the skaters'
  power-play goals exceeding the goalies' power-play goals against by 7, 9 and 8 (see "Team basic stats"),
  and of 26, 28 and 27 shorthanded goals a season that no goalie has.
- **Time on ice by strength per skater** comes from the shifts and matches the NHL exactly for only part of
  the skaters (power play 322 of 924, shorthanded 363 of 924 in 2023; 519 and 588 of 940 in 2025), with
  gaps up to about 160 s. In total ours is 0.2-0.3% high (see "Time on ice"). Cause not found.
- **On-ice goals for and against** (`gf`, `ga`): the skaters credited come from the shifts, but the state
  (power play, shorthanded, even strength) each goal and shot is counted under now comes from the situation
  code (`base_tables.py`; the shift state is still used for seconds). This changed 0.1-0.2% of attempts
  (266, 180 and 173 in 2023-2025). Compared as whole goals with the NHL's (per 60 x its seconds / 3600) by
  `scripts/diagnose_on_ice_membership.py`, for skaters with time on ice (in 2024 only the 260 with shift
  data in every game): power-play goals for match for 849 of 849 (2023), 194 of 194 (2024) and 833 of 835
  (2025); penalty-kill goals against for 781 of 788, 172 of 172 and 806 of 811. All 14 differences are one
  goal, ours the higher. For 12 of them a goal scored at a line change could account for the gap (not proven,
  since most matching skaters also have line-change goals); for one skater (2025 power play) no such goal
  exists. Earlier figures of 64-86% came from a check that counted skaters with no time on ice as
  mismatches, and were wrong.
- **Individual shot attempts** are not in the special-teams table. On the power play the NHL's count sits
  between our Fenwick (without blocks) and our Corsi, about 2% above Fenwick; shorthanded it matches our
  Corsi for 94% of skaters. The rule is not understood. They stay in the advanced table with our definition.
- **Per-60 rates** of goals, assists, points and shots use only the games with shift data (the
  `included_*` columns), so a count and a time cover the same games; shooting percentage uses all games.
- **Penalty-shot goals** are not in `shot_attempts` (the situation code shows one skater against none, and
  they are not counted as shot attempts). The NHL counts one scored by a team that is shorthanded as a
  shorthanded goal. Both special-teams tables add those goals, found from the events (situation code 1010 or
  0101, not in a shootout) with the scorer's strength taken from the stint covering that second
  (`team_special_teams.penalty_shot_goals`). There are 16, 7 and 6 penalty-shot goals outside shootouts in
  2023-2025; 0, 1 and 2 were scored shorthanded and the rest at even strength. None was scored on a
  power play, so the NHL's treatment of that case is untested (power-play goals match with penalty-shot
  goals left out). With this, shorthanded goals match the NHL for every skater and every team-game in all
  three seasons. Found with `scripts/diagnose_shorthanded_goals.py`.
- **Remaining disagreement:** shots on goal differ by one for a few skaters (power play 5 in each of 2024 and 2025,
  shorthanded 5 and 6; see above), and individual shot attempts and time on ice by strength as
  described above.

## Team power play and penalty kill

`team_game_special_teams` and `team_season_special_teams` take goals from the situation code (strength as in
"Power play and shorthanded") and count opportunities from the penalty events. Checked with
`scripts/check_team_special_teams.py` against the NHL's per-team, per-game and per-season reports.

- **Goals:** power-play and shorthanded goals, for and against, match the NHL for every team-game in all three
  seasons (2,624 of 2,624 each; 2023-2025 power-play goals 1,660, 1,537 and 1,595; shorthanded 234, 208
  and 205). The shorthanded ones need the penalty-shot goals added (see "Power play and shorthanded").
- **Opportunities** are our own count because the NHL does not publish its rule. The rule, found by comparing
  with the NHL's per-game counts: a 2- or 5-minute penalty is one opportunity for the other team, a 4-minute
  double minor is two; penalties of the same length given to both teams at the same second cancel one for
  one (coincident minors, and the pair of majors in a fight); penalties at exactly 3600 s of a game without
  overtime do not count; misconducts (10 minutes) and penalty shots (0) do not count.
  Result: exact in 2,555, 2,582 and 2,583 of 2,624 team-games in 2023-2025, no team-game off by more than 2,
  and totals of 7,943, 7,123 and 7,581 opportunities against the NHL's 7,917, 7,101 and 7,555 (+0.3%). Rules tried and rejected because they matched
  less often: a full penalty-clock model, leaving majors uncancelled (about 600 too many), treating minors
  and majors differently, and ignoring late penalties.
- **Open:** the remaining 1.6-2.6% of team-games are off by one or two with no pattern found.
  Season percentages are not affected much: power-play % and penalty-kill % are within 0.5 points of the NHL's
  for all 32 teams in every season (mean difference 0.09-0.13 points).

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

## Validation against Natural Stat Trick

`scripts/check_against_nst.py` compares our player and team on-ice tables with Natural Stat Trick's
(NST) season CSV exports (skaters and teams, 5v5 and all situations, counts, regular season). NST ids are not
NHL ids, so skaters are matched by name and team (a traded player is one NST row), with a fallback on
last name and games played for spelling differences such as Nick and Nicholas. All 924, 920 and 940
skaters match in 2023, 2024 and 2025. The NST files are not committed.

| All situations | 2023 | 2024 | 2025 |
| --- | --- | --- | --- |
| Skaters with goals for exact | 880 of 924 | 906 of 920 | 915 of 940 |
| Skaters with goals against exact | 899 of 924 | 907 of 920 | 927 of 940 |
| Skaters with Corsi for exact (within 2) | 273 (667) | 262 (718) | 279 (721) |
| Skaters with Corsi against exact (within 2) | 387 (828) | 442 (852) | 430 (857) |
| League Corsi for, ours / NST | 793,200 / 793,189 | 777,259 / 777,260 | 760,410 / 760,411 |
| Team goals, ours / NST | 8,070 / 8,086 | 7,894 / 7,901 | 8,080 / 8,086 |
| Teams with time on ice within 0.1 minute | 32 of 32 | 30 of 32 | 32 of 32 |

**Differences and their causes**
- **Penalty-shot goals.** NST counts them; our shot-attempt tables do not contain them (the NHL's
  play-by-play lists them differently). The gap in team goals is exactly the number of penalty-shot goals
  outside shootouts (16 in 2023, 7 in 2024, 6 in 2025). Team power-play and penalty-kill goals add them
  separately (see the power-play section).
- **Who is on the ice at a line change.** An attempt at the second a shift ends can be credited to the
  outgoing or incoming skaters. Testing the four boundary rules against NST (`diagnose_boundary_rules.py`)
  gave one rule per attempt type that agrees best in both 2023 and 2025: the skaters of the defending team
  for any non-goal attempt, and the skaters of the shooting team for a shot on goal, come from the stint that
  ends at the attempt's second; goals are end-inclusive for both sides; missed and blocked shots are
  start-inclusive for the shooting side. This raised per-skater exact matches (for example 2025 shots on
  goal for 307 to 332 of 940, Corsi against 394 to 430). No rule makes per-skater Corsi exact: 72-78% of
  skaters are within 2 attempts of NST and about 95% within 5, a mean gap of 1.6-1.8 attempts per skater. The
  remaining difference is probably how NST processes the shift reports.
- **5v5 time on ice.** Our 5v5 team time is 0.04-0.06% above NST's (78 minutes of 127,693 in 2025) while all-
  situations time agrees to 0.1 minute. Splitting even-strength time by state (`diagnose_nst_time_by_strength.py`)
  showed about 49 minutes of power-play and shorthanded time that NST has and we do not, and 29 minutes that NST
  places in 4v4 and goalie-out states. Probably the exact second at which a penalty starts or ends or a goalie
  leaves the ice; about 1.8 seconds per team-game. Cause not found; no stat a fan reads changes.
- **Team shot totals** differ by 0.03-0.1% (2025 shots on goal are 0.06% above NST's). Cause not found.