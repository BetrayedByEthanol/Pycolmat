"""Tests for customfmt.discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from customfmt.discovery import IGNORED_DIRS, collect_files


def make_tree(base: Path, structure: dict) -> None:
    """Recursively create files and dirs from a dict spec."""
    for name, content in structure.items():
        p = base / name
        if isinstance(content, dict):
            p.mkdir(parents=True, exist_ok=True)
            make_tree(p, content)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content or "")


# ---------------------------------------------------------------------------
# Basic collection
# ---------------------------------------------------------------------------


class TestCollectFiles:
    def test_single_py_file(self, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("")
        assert collect_files([str(f)]) == [f]

    def test_non_py_file_skipped(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("")
        assert collect_files([str(f)]) == []

    def test_directory_recurse(self, tmp_path):
        make_tree(tmp_path, {"a.py": "", "sub/b.py": "", "sub/c.txt": ""})
        result = collect_files([str(tmp_path)])
        names = {p.name for p in result}
        assert names == {"a.py", "b.py"}

    def test_sorted_output(self, tmp_path):
        make_tree(tmp_path, {"z.py": "", "a.py": "", "m.py": ""})
        result = collect_files([str(tmp_path)])
        assert result == sorted(result)

    def test_dedup_across_multiple_paths(self, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("")
        result = collect_files([str(f), str(f)])
        assert result.count(f) == 1

    def test_nonexistent_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            collect_files([str(tmp_path / "nope.py")])


# ---------------------------------------------------------------------------
# Ignored directories
# ---------------------------------------------------------------------------


class TestIgnoredDirs:
    @pytest.mark.parametrize("ignored", sorted(IGNORED_DIRS))
    def test_ignored_dir_skipped(self, tmp_path, ignored):
        make_tree(tmp_path, {ignored: {"secret.py": ""}})
        result = collect_files([str(tmp_path)])
        assert not any(p.name == "secret.py" for p in result)

    def test_non_ignored_subdir_included(self, tmp_path):
        make_tree(tmp_path, {"src": {"a.py": ""}})
        result = collect_files([str(tmp_path)])
        assert any(p.name == "a.py" for p in result)

    def test_nested_ignored_skipped(self, tmp_path):
        make_tree(tmp_path, {"src": {"__pycache__": {"cached.py": ""}}})
        result = collect_files([str(tmp_path)])
        assert not any(p.name == "cached.py" for p in result)

    def test_ignored_dir_alongside_valid(self, tmp_path):
        make_tree(
            tmp_path,
            {
                "src": {"good.py": ""},
                ".venv": {"hidden.py": ""},
            },
        )
        result = collect_files([str(tmp_path)])
        names = {p.name for p in result}
        assert "good.py" in names
        assert "hidden.py" not in names
