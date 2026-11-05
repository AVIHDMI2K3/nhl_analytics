import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import make_project_map  # noqa: E402


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_describe_python_file_reads_docstring_functions_classes_and_tests(tmp_path):
    path = tmp_path / "module.py"
    write(path, '"""\nDoes one thing.\n\nMore detail.\n"""\n\nclass Box:\n    pass\n\n\ndef helper():\n    pass\n\n\ndef test_a():\n    pass\n\n\ndef test_b():\n    pass\n')
    info = make_project_map.describe_python_file(path)
    assert info == {"purpose": "Does one thing.", "functions": ["helper"], "classes": ["Box"], "tests": 2}


def test_describe_python_file_without_docstring(tmp_path):
    path = tmp_path / "bare.py"
    write(path, "def run():\n    pass\n")
    assert make_project_map.describe_python_file(path)["purpose"] == ""


def test_markdown_title_uses_the_first_heading(tmp_path):
    path = tmp_path / "notes.md"
    write(path, "intro\n\n## Data notes: known issues\n\n# later\n")
    assert make_project_map.markdown_title(path) == "Data notes: known issues"


def test_build_map_lists_files_and_skips_init_and_cache(tmp_path):
    write(tmp_path / "src" / "pkg" / "__init__.py", "")
    write(tmp_path / "src" / "pkg" / "core.py", '"""Core logic."""\n\ndef run():\n    pass\n')
    write(tmp_path / "src" / "pkg" / "__pycache__" / "junk.py", "x = 1\n")
    write(tmp_path / "tests" / "test_core.py", "def test_run():\n    pass\n")
    write(tmp_path / "docs" / "metrics.md", "# Metrics\n")
    text = make_project_map.build_map(tmp_path)
    assert "### `src/pkg/core.py`" in text and "Core logic." in text and "`run`" in text
    assert "__init__" not in text and "junk" not in text
    assert "- tests: 1" in text
    assert "`docs/metrics.md`: Metrics" in text
    assert "data tables" in text