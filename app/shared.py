"""The one place that makes the repo's own modules importable from the app, and re-exports what the pages need.

The app lives in app/, but its labels are in src/nhl_pipeline/transform/ and its settings in config/. Streamlit only
puts app/ on the import path, so this module adds the other two folders and then imports from them. Pages and helpers
import `labels` and `settings` from here and do not touch sys.path themselves.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT / "src" / "nhl_pipeline" / "transform", ROOT):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import column_labels as labels  # noqa: E402

from config import settings  # noqa: E402

__all__ = ["labels", "settings"]
