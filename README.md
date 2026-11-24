# NHL Analytics

A data pipeline and app that gives NHL fans basic and advanced stats, and the tools to build their own analysis from them.

> **Status: in development (portfolio project).** The data pipeline is built: raw ingestion, staging tables, the on-ice join, the metrics, validation against Natural Stat Trick, the line and defense-pair tables, the skater percentiles and the player similarity table. The Streamlit app has pages for players, lines and pairs, teams and stat definitions; the player comparison and similarity pages, and the deployment, are next. See [Project status](#project-status).

## About

Fans who like the data side of hockey can find basic stats in many places, but advanced stats (Corsi, Fenwick, on-ice splits, line and pair results) are spread across sites that each show a fixed set of tables. This project aims to put all of it in one place and let users build their own comparisons.

Features:

- basic and advanced stats for players and teams (in the app)
- forward line and defense pair comparison and performance (in the app)
- team performance (in the app)
- player comparison with pizza charts, and player similarity (planned; the data tables are built)

The advanced stats are computed in this repository from the NHL's play-by-play events and shift charts, then checked against official boxscores and Natural Stat Trick, instead of being copied from another site. Simple totals (goals, assists, hits, time on ice and so on) are taken from the NHL boxscore, which was checked against the NHL's official game reports; stats that depend on who was on the ice are calculated here and never mixed with them in one number.

**Version 1 scope:** seasons from 2023-24 onward, regular season only. Playoffs and earlier seasons come later.

**What the data can't do:** the NHL's public play-by-play has no pass events, so pass-based metrics are out of scope. The NHL's shift-chart API returns no shifts for some games (57 games in 2024-25); those shifts are taken from the NHL's HTML time-on-ice reports instead, which agree with the API exactly on games that have both, so every game contributes to the on-ice stats. Games with no shifts from either source would be left out and the app would show games played and games included in the on-ice stats side by side. Every known difference from the NHL's own numbers, and what we did about it, is in [`docs/data_notes.md`](docs/data_notes.md).

### How it works

```
NHL API -> raw -> staging -> intermediate -> metrics -> analysis -> app
```

Data lives in Parquet files queried with DuckDB. The app is built with Streamlit and reads a small set of finished tables copied into `app_data/`, so it runs without the raw data or the pipeline.

- **raw:** each API response saved exactly as received, gzipped, and never edited.
- **staging:** the raw responses parsed into flat tables (games, players, events, shifts, boxscore players).
- **intermediate:** staging tables joined into who was on the ice for every event, cleaned shifts, and each skater's plus/minus from that.
- **metrics:** shot attempts, stints (stretches of play with a fixed lineup), long base tables of counts and seconds by strength and game state, skater and goalie season totals from the boxscore, and the fan-facing season tables for skaters, goalies and teams. Definitions are in [`docs/metrics.md`](docs/metrics.md).
- **analysis:** percentile ranks of skaters and a player similarity table.
- **app:** the fan-facing tables are exported to `app_data/` and shown by the Streamlit app in `app/`.

Data comes from the NHL's unofficial, undocumented services, so they can change without notice. This project is not affiliated with or endorsed by the NHL. Requests are paced at one per second with a descriptive User-Agent.

| Data | Endpoint |
| --- | --- |
| League schedule (weekly) | `https://api-web.nhle.com/v1/schedule/{date}` |
| Play-by-play | `https://api-web.nhle.com/v1/gamecenter/{gameId}/play-by-play` |
| Boxscore | `https://api-web.nhle.com/v1/gamecenter/{gameId}/boxscore` |
| Shift charts | `https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId={gameId}` |

Game IDs look like `2023020001`: season start year, a 2-digit game type (`01` preseason, `02` regular season, `03` playoffs), then the game number. A 32-team regular season has 1,312 games.

## Installation

Requires Python 3.11. The project is developed in a conda environment named `nhl`.

```
git clone https://github.com/AVIHDMI2K3/nhl_analytics.git
cd nhl_analytics
conda create -n nhl python=3.11
conda activate nhl
pip install requests tenacity pyarrow polars duckdb pytest streamlit pandas
```

Check the install by running the tests from the repository root:

```
pytest
```

Run the app from the repository root. It needs only the committed `app_data/` folder, not the pipeline data:

```
pip install -r app/requirements.txt
streamlit run app/Home.py
```

## Codebase and usage

```
src/nhl_pipeline/ingest/
    endpoints.py        endpoint URLs and the rate-limited, retrying HTTP client
    rawstore.py         raw file layout, atomic gzip writes, readers
    ingest_season.py    download one regular season (command-line tool)
    staging.py          parsers: raw responses -> rows (no file or network access)
    stage_season.py     build the staging tables for one season (command-line tool)
    ingest_reference.py download the NHL's own season reports (skater time on ice, power play, penalty kill and faceoffs, goalie summary, team power play and penalty kill) used for checks
    probe.py            Phase 0 script: fetch one game and print the response shapes
src/nhl_pipeline/transform/
    onice.py            who was on the ice for each event (pure logic, no file access)
    shift_reports.py    parse the NHL's HTML time-on-ice reports into shift rows (used by scripts/fill_missing_shifts.py)
    build_onice.py      build the on-ice tables for one season (command-line tool)
    shot_attempts.py, build_shot_attempts.py   one row per shot attempt, with who was on the ice
    stints.py, build_stints.py                 stretches of a period with a fixed lineup, and each side's strength
    base_tables.py, build_base_tables.py       long tables of seconds and attempt counts by player, game and state
    event_stats.py                             assists, hits, giveaways, takeaways, faceoffs, penalties by state
    season_totals.py, build_season_totals.py   skater and goalie season totals from the boxscore
    season_display.py, build_season_display.py fan-facing skater and goalie season tables (traded players get a combined row)
    special_teams.py, build_player_special_teams.py   skater power-play and penalty-kill stats (strength of goals and shots from the NHL situation code, time on ice from shifts)
    faceoffs.py, build_player_faceoffs.py      skater faceoff wins, losses and percentage (all games, by strength and zone)
    team_special_teams.py, build_team_special_teams.py   team power-play and penalty-kill numbers and percentages (goals from the situation code, opportunities counted from penalty events)
    advanced_stats.py, build_player_advanced.py, build_team_advanced.py   Corsi, Fenwick, shots, goals, rates, relative stats
    team_basic.py, build_team_basic.py         team record, goals, shots, hits and the like
    lines.py, line_tables.py, build_line_tables.py   forward lines (3 forwards) and defense pairs (2 defensemen) at 5v5: time together and shot attempts for and against
    zone_starts.py, build_unit_zone_starts.py  faceoffs (zone starts) of lines and pairs at 5v5, in their own terms
    percentiles.py, build_player_percentiles.py   percentile ranks of skaters for the pizza charts (forwards against forwards, defensemen against defensemen, each season on its own)
    similarity.py, build_player_similarity.py  the closest skaters to each skater, same season and all seasons (equal weight per category of stats)
    line_display.py, build_line_display.py     fan-facing line and pair table: id, label (LW-C-RW), positions, rates, zone starts; units under 20 minutes together dropped
    team_app.py, build_team_app.py             the team table the Teams page shows (pure logic, then the command-line build)
    player_app.py, build_player_app.py         the skater table the Players page shows (pure logic, then the command-line build)
    column_labels.py    fan-facing column names, descriptions and groups for the app's tables
scripts/
    inspect_staging.py  health check of the staging tables
    check_boxscore.py   compare per-player counts from events and shifts with the official boxscore
    probe_situation_code.py  compare situationCode with who is on the ice, per shift chart
    inspect_onice.py    where the on-ice tables disagree with situationCode and with the boxscore plus/minus
    find_pm_goals.py    which goal explains a plus/minus difference with the boxscore
    probe_goal_boundary.py  compare four boundary rules for goals against the boxscore plus/minus
    check_stints.py, test_strength_toi.py   how strength is decided, checked against the NHL's time on ice by strength
    check_base_tables.py, check_season_totals.py, check_goalie_totals.py, check_player_faceoffs.py, check_player_special_teams.py, check_team_special_teams.py, check_player_advanced.py, check_team_advanced.py, check_team_basic.py
                        checks of each metrics table (exact identities and comparisons with the NHL's numbers)
    compare_boxscore_to_nhl.py   compare the boxscore with the NHL's official event summary pages for a sample of games
    fill_missing_shifts.py       fill games with no API shifts from the NHL's HTML reports; check_html_shift_reports.py and compare_html_shifts.py check that the reports exist and agree with the API
    diagnose_skater_minutes.py   how many skaters reach each 5v5 minimum (used to choose the 600-minute pool minimum)
    export_app_data.py   copy the tables the app reads into the committed app_data/ folder
    check_line_tables.py, diagnose_unit_gaps.py   check that line and pair numbers add up to the skaters' 5v5 totals, and explain the 5v5 time that has no line or pair
    check_against_nst.py         compare skater and team on-ice stats with Natural Stat Trick CSV exports (NST files go in data/reference/nst, not committed)
    diagnose_nst_5v5.py, diagnose_skater_gap.py, diagnose_boundary_rules.py, diagnose_nst_time_by_strength.py   investigations of the remaining differences with Natural Stat Trick
    diagnose_shots_against_gap.py, diagnose_boxscore_vs_pbp.py, diagnose_special_teams_goals.py, diagnose_team_opportunities.py, diagnose_team_opportunities_by_game.py, diagnose_shorthanded_goals.py, diagnose_on_ice_membership.py, inspect_goal_strength.py
                        investigations of small differences between sources
app/
    Home.py             landing page
    pages/              Players, Lines and Pairs, Teams and Stat definitions
    table_view.py       filters and table layout for the pages
    loaders.py          cached readers of app_data/
    shared.py           makes src/ and config/ importable from the app
config/settings.py      app settings (seasons, default minimums)
app_data/               the finished tables the app reads (committed)
requirements.txt        what the deployed app needs
docs/
    metrics.md          what each stat means and how it is calculated
    data_notes.md       where our numbers differ from the NHL's, why, and how each case is handled
tests/                  offline tests with made-up responses
data/                   not tracked by git
    raw/                season=2023/game=2023020001/play-by-play.json.gz ...
    staging/            season=2023/events.parquet, shifts.parquet ...
    intermediate/       season=2023/event_on_ice.parquet, shifts_clean.parquet ...
    metrics/            season=2023/shot_attempts.parquet, stints.parquet, player_game_strength.parquet,
                        player_season_totals.parquet, player_season_display.parquet, goalie_season_totals.parquet,
                        goalie_season_display.parquet, player_season_special_teams.parquet, team_game_special_teams.parquet, team_season_special_teams.parquet, player_season_faceoffs.parquet, player_season_advanced.parquet,
                        team_season_advanced.parquet, team_season_basic.parquet ...
    logs/               ingestion_log.jsonl, staging_report_2023.json, onice_report_2023.json, base_tables_report_2023.json
```

Run these from the repository root with the environment active. `--season` is the year the season starts (`2023` means 2023-24).

**1. Download the raw files for a season.** Check what would be downloaded first (nothing is written), then try a small batch, then run the full season:

```
python src/nhl_pipeline/ingest/ingest_season.py --season 2023 --dry-run
python src/nhl_pipeline/ingest/ingest_season.py --season 2023 --limit 20
python src/nhl_pipeline/ingest/ingest_season.py --season 2023
```

A full season takes roughly 70 minutes. Stopping with Ctrl+C is safe: run the same command again to resume. For the season in progress, rerun it to pick up newly finished games. If the NHL returns an empty shift chart for a game, the game is marked as having no shift data and is not retried unless you pass `--recheck-empty`.

**2. Build the staging tables.** This reads only the raw files and rebuilds the season's tables each time:

```
python src/nhl_pipeline/ingest/stage_season.py --season 2023 --limit 5
python src/nhl_pipeline/ingest/stage_season.py --season 2023
```

| Table | One row per | Contents |
| --- | --- | --- |
| `games` | game | date, teams, final score, shift-data status, per-game check results |
| `players` | player per game | team, name, jersey number, position |
| `events` | play-by-play event | type, period, game clock in seconds, team, coordinates, players involved, situation code |
| `shifts` | shift | player, team, period, start and end in seconds |
| `boxscore_players` | player per game | the NHL's official per-game numbers, used to check our own counts |

The command prints a summary and writes `data/logs/staging_report_<season>.json`. It checks that goals counted from events match the final score, that every game has events and a boxscore, and that no shift ends before it starts or overlaps another shift by the same player.

Query the tables with DuckDB:

```python
import duckdb

duckdb.sql("""
    select event_type, count(*) as n
    from 'data/staging/season=2023/events.parquet'
    group by 1 order by n desc
""").show()
```

**2b. Fill games the API has no shifts for (only if the staging step reports `none_from_nhl` games).** 57 games in 2024-25 (ids 2024021235 to 2024021291) have an empty shift chart. The NHL's HTML time-on-ice reports for them exist, so this step reads those reports, matches players to ids by jersey number through the boxscore, checks each player's total shift time against the boxscore's time on ice (it holds back a game that differs by more than 2 seconds), and adds the shifts to staging. The first command only reports; run it with `--write` when every game is clean. Re-running the staging step replaces the tables, so run this again afterwards.

```
python scripts/fill_missing_shifts.py --season 2024
python scripts/fill_missing_shifts.py --season 2024 --write
```

**3. Build the on-ice tables.** This reads the staging tables and writes `data/intermediate/season=2023/`. Games with no shift data (after step 2b, none) are skipped:

```
python src/nhl_pipeline/transform/build_onice.py --season 2023 --limit 20
python src/nhl_pipeline/transform/build_onice.py --season 2023
```

| Table | One row per | Contents |
| --- | --- | --- |
| `event_on_ice` | event | the skaters and goalies on the ice for each team, their counts, the four `situationCode` digits and whether they agree |
| `shifts_clean` | shift | shifts with exact duplicates removed, goalies marked, conflicting shifts flagged |
| `player_game_plus_minus` | skater per game | plus/minus from our on-ice data |

The command prints how often the on-ice counts agree with `situationCode` and how our plus/minus compares with the boxscore, and writes `data/logs/onice_report_<season>.json`. Two rules decide the result:

- **A shift that starts or ends on the second of an event.** For a goal, penalty, delayed penalty, period end or game end, a shift ending at that second counts and one starting at that second does not. For every other event it is the opposite.
- **Plus/minus** follows the NHL's rule: even-strength and shorthanded goals count, power-play goals and penalty-shot goals count for nobody. A team with its goalie pulled is counted one skater short when deciding whether a goal is a power-play goal.

**4. Build the metrics tables.** Run these in order for each season. Each reads the tables before it and writes to `data/metrics/season=2023/`:

```
python src/nhl_pipeline/transform/build_shot_attempts.py --season 2023
python src/nhl_pipeline/transform/build_stints.py --season 2023
python src/nhl_pipeline/transform/build_base_tables.py --season 2023
python src/nhl_pipeline/transform/build_season_totals.py --season 2023
python src/nhl_pipeline/transform/build_season_display.py --season 2023
python src/nhl_pipeline/transform/build_player_advanced.py --season 2023
python src/nhl_pipeline/transform/build_team_advanced.py --season 2023
python src/nhl_pipeline/transform/build_team_basic.py --season 2023
python src/nhl_pipeline/transform/build_line_tables.py --season 2023
python src/nhl_pipeline/transform/build_unit_zone_starts.py --season 2023
python src/nhl_pipeline/transform/build_line_display.py --season 2023
```

`build_line_display.py` reads the line table, the zone starts and the skater display table, so it runs after them. The Phase 7 tables come last. Build the percentiles for every season first: the similarity table reads all of them at once and has no `--season`.

```
python src/nhl_pipeline/transform/build_player_percentiles.py --season 2023
python src/nhl_pipeline/transform/build_player_similarity.py
```

| Table | One row per | Contents |
| --- | --- | --- |
| `shot_attempts` | shot attempt | goals, shots on goal, misses and blocks with the shooter, coordinates, score and who was on the ice |
| `stints` | stretch with a fixed lineup | the skaters and goalies of each team and each side's strength (even, power play, shorthanded) |
| `player_game_strength`, `team_game_strength` | player (or team), game and state | seconds and attempt counts; every season total is a sum of these rows |
| `player_season_totals` | skater and team | season totals from the boxscore, checked against the NHL's skater report |
| `player_season_display` | skater and team, plus a combined row for a traded player | the basic stats and per-60 rates for fans |
| `player_season_special_teams` | skater, team (plus a combined row for a traded player) and situation (power play, shorthanded) | time on ice, share of team time, goals, assists, points, shots, shooting percentage and per-60 rates; goals and shots take their strength from the NHL's situation code, time from the shifts; matches the NHL's skater power-play and penalty-kill reports |
| `goalie_season_totals` | goalie and team | games played and started, record, shots, saves, goals against (also by strength), shutouts, from the boxscore; matches the NHL's goalie summary for every goalie |
| `goalie_season_display` | goalie and team, plus a combined row for a traded goalie | save percentage (also by strength), goals-against average, shots against per 60 |
| `player_season_faceoffs` | skater, team (plus a combined row for a traded player) and situation (all, even strength, power play, shorthanded, offensive, defensive and neutral zone) | faceoffs, wins, losses and win percentage, counted from the faceoff events for every game; matches the NHL's skater faceoff report for every skater |
| `team_game_special_teams`, `team_season_special_teams` | team and game (or season) | power-play opportunities, goals and percentage, times shorthanded, goals against and penalty-kill percentage, shorthanded goals for and against; goals match the NHL's team reports in every team-game, opportunities are our own count and match the NHL's in about 98% of team-games |
| `player_season_advanced`, `team_season_advanced` | player (or team) and situation | Corsi, Fenwick, shots and goals for and against, percentages, per-60 rates and, for players, relative stats, for all situations, even strength, 5v5, power play and shorthanded |
| `team_season_basic` | team | record, points, goals, shots, hits, blocks, giveaways, takeaways and penalty minutes |

Each table has a check script in `scripts/` (for example `python scripts/check_team_basic.py --season 2023`) that prints how it compares with the NHL's own numbers.

## Project status

| Phase | What | Status |
| --- | --- | --- |
| 0 | Probe the endpoints and confirm the response shapes | Done |
| 1 | Raw ingestion of a regular season | Done for 2023-24, 2024-25 and 2025-26 |
| 2 | Staging tables | Done for all three seasons. Goals counted from events match the final score in all 3,936 games, and player goals, assists, hits, giveaways and takeaways match the boxscore exactly |
| 3 | On-ice join of events to shifts, strength states | Done for all three seasons. On-ice counts agree with `situationCode` for 99.3-99.4% of events, and our plus/minus matches the boxscore for 99.9% of skater-games |
| 4 | Metrics (Corsi, Fenwick, rates, relative stats) | In progress. Built for all three seasons: shot attempts, stints, base tables, skater season totals and display table, advanced on-ice tables for players and teams, team basic stats. Skater season totals match the NHL's skater report for every skater (games played and time on ice), and goalie season totals match the NHL's goalie summary for every goalie (record, shots, saves, goals against, shutouts, time on ice). Skater power-play and penalty-kill stats are built (power-play goals, assists and points match the NHL's reports for every skater). Team power-play and penalty-kill percentages are built (within 0.5 points of the NHL's for every team). Skater faceoff counts and percentages are built (counts and percentages match the NHL's faceoff report for every skater, in total, by strength and by zone). Phase 4 is complete except the stats that need the xG model (high-danger goalie stats), which come in Phase 9, after the first version of the app is deployed |
| 5 | Validation against boxscores and Natural Stat Trick | Done for all three seasons. Boxscore and the NHL's reports were checked in earlier phases. Against Natural Stat Trick (skaters and teams, all situations and 5v5): league totals of shot attempts match within 0.01% for skaters and 0.03% for teams, team time on ice within 0.1 minute for 94-100% of teams, goals exact for 95-99% of skaters, and 72-78% of skaters are within 2 shot attempts of NST. The 57 games of 2024-25 with no API shifts were filled from the NHL's HTML reports. Remaining differences and their causes are in [`docs/data_notes.md`](docs/data_notes.md) |
| 6 | Line and defense-pair analysis | Done for all three seasons. Forward lines and defense pairs at 5v5 with time together, shot attempts, goals, percentages, per-60 rates and zone starts. A line or pair is found for 98.6-99.0% of 5v5 time and 99.4-99.6% of 5v5 faceoffs, and the units add up to the skaters' 5v5 totals with no violations. The fan-facing table keeps units with at least 20 minutes together. Limits are in [`docs/data_notes.md`](docs/data_notes.md) |
| 7 | Player comparison (pizza charts) and similarity | Data tables done for all three seasons: percentile ranks of every skater in 29 stats (forwards against forwards, defensemen against defensemen, each season ranked on its own, among the 195-351 skaters per group with at least 600 minutes of 5v5) and the 15 closest skaters of each pool skater, in the same season and across seasons. The charts themselves are drawn in the app (Phase 8). Limits are in [`docs/data_notes.md`](docs/data_notes.md) |
| 8 | App (Streamlit) and deployment of version 1 (Corsi, shots and goals; no xG) | In progress. Built: Home, Players (with a per-team breakdown for traded players), Lines and Pairs, Teams and Stat definitions. The player comparison and similarity pages and the deployment are next |
| 9 | xG model, then high-danger and goalie stats, added to the app as version 2 | Planned |

Findings so far:

- A blocked shot belongs to the shooter's team (`event_owner_team_id`). About 7.5% of blocked shots are marked `teammate-blocked`, where the blocker is on the shooter's team.
- The boxscore's blocked-shot stat leaves out `teammate-blocked` shots. Time on ice from de-duplicated shifts is within 2 seconds of the boxscore for over 99% of skater-games.
- The NHL's giveaway and takeaway totals change sharply between seasons (about 19,000 giveaways in 2023-24 against about 38,000 in 2024-25), so those two stats are not comparable across seasons.
- The NHL shift data contains duplicate rows (the same shift listed twice) and a few conflicting ones, in roughly 20-40% of games depending on the season. They are cleaned in Phase 3: exact duplicates are dropped and the few conflicting shifts are flagged.
- `situationCode` has four digits in this order: away goalie, away skaters, home skaters, home goalie (`1551` is 5 on 5). A penalty shot shows up as `1010` or `0101`.
- Goals and shifts are both timed in whole seconds, so a shift that starts or ends on a goal's second is ambiguous. Of four possible rules, only one matches the boxscore plus/minus (99.9% of skater-games against 31-46% for the others).
- The boxscore was compared with the NHL's official event summary pages for 60 random games (2,160 player-games): everything matched except two penalty-minute values, where the boxscore had 10 minutes more. Simple totals therefore come from the boxscore.
- For the strength of a goal or shot, the NHL's `situationCode` on the event beats the shifts: it matches the goalies' boxscore numbers in every power-play team-game and the NHL's player power-play reports for every skater, while the shifts are a second or two off at line changes and penalty expiries (strength for time on ice still has to come from the shifts).
- A shift chart can hold another game's shifts (game 2025020565 held the shifts of a different game). Shifts by a team that is not in the game are removed before anything else.
- Shot attempts, plus/minus and strength agree with the NHL's own numbers to within small gaps listed in [`docs/data_notes.md`](docs/data_notes.md), for example time on ice by strength within 0.04% at even strength and about 0.2-0.3% on special teams.
- On stoppages the NHL's `situationCode` disagrees with the shift chart about 3% of the time (it sometimes seems to describe the restart). Our shift-based counts are used and the disagreement is kept in `matches_situation`.

## Papers

None yet. The definitions of each metric are in [`docs/metrics.md`](docs/metrics.md); references will be added when the metrics phase is finished.

## Extended docs

- [`docs/metrics.md`](docs/metrics.md): what each stat means, where it comes from and how it is calculated.
- [`docs/data_notes.md`](docs/data_notes.md): where our numbers can differ from the NHL's, the cause where we found one, and how each case is handled.

## License

Copyright (c) 2026 Avi Sharma. All rights reserved. This code is shared for viewing as part of a portfolio.