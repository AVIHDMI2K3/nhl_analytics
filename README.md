# NHL Analytics

A data pipeline and app that gives NHL fans basic and advanced stats, and the tools to build their own analysis from them.

> **Status: in development (portfolio project).** Raw ingestion, staging tables, the on-ice join and most of the metrics (season totals, advanced on-ice stats for players and teams, team records) are built. Validation against Natural Stat Trick, line and pair analysis, player comparison and the app are planned. See [Project status](#project-status).

## About

Fans who like the data side of hockey can find basic stats in many places, but advanced stats (Corsi, Fenwick, on-ice splits, line and pair results) are spread across sites that each show a fixed set of tables. This project aims to put all of it in one place and let users build their own comparisons.

Planned features:

- basic and advanced stats for players and teams
- forward line and defense pair comparison and performance
- player comparison with pizza charts, and player similarity
- team performance

The advanced stats are computed in this repository from the NHL's play-by-play events and shift charts, then checked against official boxscores and Natural Stat Trick, instead of being copied from another site. Simple totals (goals, assists, hits, time on ice and so on) are taken from the NHL boxscore, which was checked against the NHL's official game reports; stats that depend on who was on the ice are calculated here and never mixed with them in one number.

**Version 1 scope:** seasons from 2023-24 onward, regular season only. Playoffs and earlier seasons come later.

**What the data can't do:** the NHL's public play-by-play has no pass events, so pass-based metrics are out of scope. The NHL also returns no shift data for some games (57 games in 2024-25, for example), so those games can't contribute to on-ice stats. They are in the boxscore totals, so the app shows games played and games included in the on-ice stats side by side. Every known difference from the NHL's own numbers, and what we did about it, is in [`docs/data_notes.md`](docs/data_notes.md).

### How it works

```
NHL API -> raw -> staging -> intermediate -> metrics -> analysis -> app
```

Data lives in Parquet files queried with DuckDB. The app starts as Streamlit.

- **raw:** each API response saved exactly as received, gzipped, and never edited.
- **staging:** the raw responses parsed into flat tables (games, players, events, shifts, boxscore players).
- **intermediate:** staging tables joined into who was on the ice for every event, cleaned shifts, and each skater's plus/minus from that.
- **metrics:** shot attempts, stints (stretches of play with a fixed lineup), long base tables of counts and seconds by strength and game state, skater season totals from the boxscore, and the fan-facing season tables for skaters and teams. Definitions are in [`docs/metrics.md`](docs/metrics.md).
- **analysis, app:** planned (see the roadmap).

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
pip install requests tenacity pyarrow polars duckdb pytest
```

Check the install by running the tests from the repository root:

```
pytest
```

## Codebase and usage

```
src/nhl_pipeline/ingest/
    endpoints.py        endpoint URLs and the rate-limited, retrying HTTP client
    rawstore.py         raw file layout, atomic gzip writes, readers
    ingest_season.py    download one regular season (command-line tool)
    staging.py          parsers: raw responses -> rows (no file or network access)
    stage_season.py     build the staging tables for one season (command-line tool)
    probe.py            Phase 0 script: fetch one game and print the response shapes
src/nhl_pipeline/transform/
    onice.py            who was on the ice for each event (pure logic, no file access)
    build_onice.py      build the on-ice tables for one season (command-line tool)
    shot_attempts.py, build_shot_attempts.py   one row per shot attempt, with who was on the ice
    stints.py, build_stints.py                 stretches of a period with a fixed lineup, and each side's strength
    base_tables.py, build_base_tables.py       long tables of seconds and attempt counts by player, game and state
    event_stats.py                             assists, hits, giveaways, takeaways, faceoffs, penalties by state
    season_totals.py, build_season_totals.py   skater season totals from the boxscore
    season_display.py, build_season_display.py fan-facing skater season table (traded players get a combined row)
    advanced_stats.py, build_player_advanced.py, build_team_advanced.py   Corsi, Fenwick, shots, goals, rates, relative stats
    team_basic.py, build_team_basic.py         team record, goals, shots, hits and the like
scripts/
    inspect_staging.py  health check of the staging tables
    check_boxscore.py   compare per-player counts from events and shifts with the official boxscore
    probe_situation_code.py  compare situationCode with who is on the ice, per shift chart
    inspect_onice.py    where the on-ice tables disagree with situationCode and with the boxscore plus/minus
    find_pm_goals.py    which goal explains a plus/minus difference with the boxscore
    probe_goal_boundary.py  compare four boundary rules for goals against the boxscore plus/minus
    check_stints.py, test_strength_toi.py   how strength is decided, checked against the NHL's time on ice by strength
    check_base_tables.py, check_season_totals.py, check_player_advanced.py, check_team_advanced.py, check_team_basic.py
                        checks of each metrics table (exact identities and comparisons with the NHL's numbers)
    compare_boxscore_to_nhl.py   compare the boxscore with the NHL's official event summary pages for a sample of games
    diagnose_shots_against_gap.py, diagnose_boxscore_vs_pbp.py   investigations of small differences between sources
docs/
    metrics.md          what each stat means and how it is calculated
    data_notes.md       where our numbers differ from the NHL's, why, and how each case is handled
tests/                  offline tests with made-up responses
data/                   not tracked by git
    raw/                season=2023/game=2023020001/play-by-play.json.gz ...
    staging/            season=2023/events.parquet, shifts.parquet ...
    intermediate/       season=2023/event_on_ice.parquet, shifts_clean.parquet ...
    metrics/            season=2023/shot_attempts.parquet, stints.parquet, player_game_strength.parquet,
                        player_season_totals.parquet, player_season_display.parquet, player_season_advanced.parquet,
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

**3. Build the on-ice tables.** This reads the staging tables and writes `data/intermediate/season=2023/`. Games with no shift data are skipped:

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
```

| Table | One row per | Contents |
| --- | --- | --- |
| `shot_attempts` | shot attempt | goals, shots on goal, misses and blocks with the shooter, coordinates, score and who was on the ice |
| `stints` | stretch with a fixed lineup | the skaters and goalies of each team and each side's strength (even, power play, shorthanded) |
| `player_game_strength`, `team_game_strength` | player (or team), game and state | seconds and attempt counts; every season total is a sum of these rows |
| `player_season_totals` | skater and team | season totals from the boxscore, checked against the NHL's skater report |
| `player_season_display` | skater and team, plus a combined row for a traded player | the basic stats and per-60 rates for fans |
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
| 4 | Metrics (Corsi, Fenwick, rates, relative stats) | In progress. Built for all three seasons: shot attempts, stints, base tables, skater season totals and display table, advanced on-ice tables for players and teams, team basic stats. Skater season totals match the NHL's skater report for every skater (games played and time on ice). Still to build: goalie season stats, power-play and penalty-kill percentages, faceoff percentage |
| 5 | Validation against boxscores and Natural Stat Trick | Planned |
| 6 | Line and defense-pair analysis | Planned |
| 7 | Player comparison (pizza charts) and similarity | Planned |
| 8 | App (Streamlit) and deployment | Planned |

Findings so far:

- A blocked shot belongs to the shooter's team (`event_owner_team_id`). About 7.5% of blocked shots are marked `teammate-blocked`, where the blocker is on the shooter's team.
- The boxscore's blocked-shot stat leaves out `teammate-blocked` shots. Time on ice from de-duplicated shifts is within 2 seconds of the boxscore for over 99% of skater-games.
- The NHL's giveaway and takeaway totals change sharply between seasons (about 19,000 giveaways in 2023-24 against about 38,000 in 2024-25), so those two stats are not comparable across seasons.
- The NHL shift data contains duplicate rows (the same shift listed twice) and a few conflicting ones, in roughly 20-40% of games depending on the season. They are cleaned in Phase 3: exact duplicates are dropped and the few conflicting shifts are flagged.
- `situationCode` has four digits in this order: away goalie, away skaters, home skaters, home goalie (`1551` is 5 on 5). A penalty shot shows up as `1010` or `0101`.
- Goals and shifts are both timed in whole seconds, so a shift that starts or ends on a goal's second is ambiguous. Of four possible rules, only one matches the boxscore plus/minus (99.9% of skater-games against 31-46% for the others).
- The boxscore was compared with the NHL's official event summary pages for 60 random games (2,160 player-games): everything matched except two penalty-minute values, where the boxscore had 10 minutes more. Simple totals therefore come from the boxscore.
- A shift chart can hold another game's shifts (game 2025020565 held the shifts of a different game). Shifts by a team that is not in the game are removed before anything else.
- Shot attempts, plus/minus and strength agree with the NHL's own numbers to within small gaps listed in [`docs/data_notes.md`](docs/data_notes.md), for example time on ice by strength within 0.04% at even strength and about 0.2-0.3% on special teams.
- On stoppages the NHL's `situationCode` disagrees with the shift chart about 3% of the time (it sometimes seems to describe the restart). Our shift-based counts are used and the disagreement is kept in `matches_situation`.

## Papers

None yet. The definitions of each metric are in [`docs/metrics.md`](docs/metrics.md); references will be added when the metrics phase is finished.

## Extended docs

- [`docs/metrics.md`](docs/metrics.md): what each stat means, where it comes from and how it is calculated.
- [`docs/data_notes.md`](docs/data_notes.md): where our numbers can differ from the NHL's, the cause where we found one, and how each case is handled.

## License

Not yet chosen.