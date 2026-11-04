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
  rows in shift-number order and drops any that overlap one already kept. In 2025, 818 of 940
  skaters match the NHL's season total exactly and 848 are within 2 seconds. In 2023 it is 744 and
  802 of 924. The rest differ by small amounts we could not explain.
- **By strength**, even-strength time is 0.03-0.04% below the NHL's, and power-play and
  shorthanded time is 0.20-0.30% above it. Cause not found. Strength comes from the skaters on
  the ice, with one fewer for a team whose goalie is off the ice, and short blips of 2 seconds or
  less are smoothed.
- **Strength at events.** Power-play goals match the boxscore for 99.96-99.98% of player-games.

## Plus/minus

Our plus/minus, derived from goals by strength, matches the boxscore for 99.58% (2023), 99.75%
(2024) and 99.77% (2025) of player-games, and runs slightly more negative (by 6 to 18 over a
season of about 500). Power-play-goal status differs from the boxscore for 17, 11 and 10
player-games in the three seasons. Cause not found. Displayed plus/minus comes from the boxscore (the season totals table).

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
  The goalies' own shots against in the boxscore are lower, by 9 to 25 per team in 2025-26. In
  2025-26 the opponent's shots while the team's goalie was off the ice (from our shifts) equal that
  gap exactly for 17 of 32 teams and are 1 to 4 higher for 14 more; Florida's is 9 higher (31
  against 22). So the gap is mostly shots on an empty net; the small excess where it is not exact is
  not explained (possibly shift timing at the moment the goalie leaves).
- **Power-play goals.** Skaters' power-play goals exceed the goalies' power-play goals against by
  7, 9 and 8 over the three seasons. Cause not found.

## Situation codes

The NHL's `situationCode` is not used for strength. It disagrees with the skaters on the ice at
about 3% of stoppages, and seven 2023 events have none. Strength from the skaters on the ice
agrees with the code at 99.86-99.91% of shot attempts.