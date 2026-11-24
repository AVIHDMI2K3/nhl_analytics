"""Settings shared by the Streamlit app and the pipeline: where the app's data lives and which seasons it shows."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DATA_ROOT = REPO_ROOT / "app_data"

# A season is coded by the year it starts in (2025 is 2025-26). Newest first, which is the order the app lists them.
SEASONS = (2025, 2024, 2023)

DEFAULT_MIN_MINUTES_5V5 = 0
DEFAULT_MIN_GAMES_GOALIE = 10
DEFAULT_MIN_MINUTES_UNIT = 100

# Fill these in once the repo is public; the Home page shows plain text until then.
GITHUB_URL = "https://github.com/AVIHDMI2K3/nhl_analytics"
DATA_NOTES_URL = "https://github.com/AVIHDMI2K3/nhl_analytics/blob/main/docs/data_notes.md"


def season_label(season):
    """2025 -> '2025-26'."""
    return f"{season}-{(season + 1) % 100:02d}"
