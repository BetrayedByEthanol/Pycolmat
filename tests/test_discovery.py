"""Tests for customfmt.discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from customfmt.discovery import IGNORED_DIRS, CollectFiles


def MakeTree(base: Path, structure: dict) -> None:
   """Recursively create files and dirs from a dict spec."""
   for name, content in structure.items():
      p = base / name
      if isinstance(content, dict):
         p.mkdir(parents=True, exist_ok=True)
         MakeTree(p, content)
      else:
         p.parent.mkdir(parents=True, exist_ok=True)
         p.write_text(content or "")


# ---------------------------------------------------------------------------
# Basic collection
# ---------------------------------------------------------------------------


class TestCollectFiles:
   def TestSinglePyFile(self, tmp_path):
      f = tmp_path / "a.py"
      f.write_text("")
      assert CollectFiles([str(f)]) == [f]

   def TestNonPyFileSkipped(self, tmp_path):
      f = tmp_path / "a.txt"
      f.write_text("")
      assert CollectFiles([str(f)]) == []

   def TestDirectoryRecurse(self, tmp_path):
      MakeTree(tmp_path, {"a.py": "", "sub/b.py": "", "sub/c.txt": ""})
      result = CollectFiles([str(tmp_path)])
      names = {p.name for p in result}
      assert names == {"a.py", "b.py"}

   def TestSortedOutput(self, tmp_path):
      MakeTree(tmp_path, {"z.py": "", "a.py": "", "m.py": ""})
      result = CollectFiles([str(tmp_path)])
      assert result == sorted(result)

   def TestDedupAcrossMultiplePaths(self, tmp_path):
      f = tmp_path / "a.py"
      f.write_text("")
      result = CollectFiles([str(f), str(f)])
      assert result.count(f) == 1

   def TestNonexistentRaises(self, tmp_path):
      with pytest.raises(FileNotFoundError):
         CollectFiles([str(tmp_path / "nope.py")])


# ---------------------------------------------------------------------------
# Ignored directories
# ---------------------------------------------------------------------------


class TestIgnoredDirs:
   @pytest.mark.parametrize("ignored", sorted(IGNORED_DIRS))
   def TestIgnoredDirSkipped(self, tmp_path, ignored):
      MakeTree(tmp_path, {ignored: {"secret.py": ""}})
      result = CollectFiles([str(tmp_path)])
      assert not any(p.name == "secret.py" for p in result)

   def TestNonIgnoredSubdirIncluded(self, tmp_path):
      MakeTree(tmp_path, {"src": {"a.py": ""}})
      result = CollectFiles([str(tmp_path)])
      assert any(p.name == "a.py" for p in result)

   def TestNestedIgnoredSkipped(self, tmp_path):
      MakeTree(tmp_path, {"src": {"__pycache__": {"cached.py": ""}}})
      result = CollectFiles([str(tmp_path)])
      assert not any(p.name == "cached.py" for p in result)

   def TestIgnoredDirAlongsideValid(self, tmp_path):
      MakeTree(
         tmp_path,
         {
            "src": {"good.py": ""},
            ".venv": {"hidden.py": ""},
         },
      )
      result = CollectFiles([str(tmp_path)])
      names = {p.name for p in result}
      assert "good.py" in names
      assert "hidden.py" not in names
