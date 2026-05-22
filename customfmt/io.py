"""
UTF-8 / LF I/O helpers for customfmt.

All file reads and writes go through this module so that encoding
and line-ending policy is enforced in exactly one place.

Policy
------
- Files are read as raw bytes first, then decoded as UTF-8 without BOM.
- A UTF-8 BOM (0xEF 0xBB 0xBF) is treated as an error, not silently stripped.
- Invalid UTF-8 byte sequences are treated as an error.
- Files are written as UTF-8 with LF line endings only.

Raised exceptions
-----------------
UnicodeDecodeError  – raised by ReadUtf8Text when bytes are invalid UTF-8.
ValueError          – raised by ReadUtf8Text when a BOM is detected.
OSError             – raised by ReadUtf8Bytes / WriteUtf8Lf on I/O failure.
"""

from __future__ import annotations

from pathlib import Path

UTF8_BOM = b"\xef\xbb\xbf"


def ReadUtf8Bytes(path: Path) -> bytes:
   """Read *path* and return its raw bytes."""
   return path.read_bytes()


def ReadUtf8Text(path: Path) -> str:
   """
   Read *path* and return its content as a Unicode string.

   Raises
   ------
   ValueError        if the file starts with a UTF-8 BOM.
   UnicodeDecodeError if the file contains invalid UTF-8 sequences.
   """
   raw = ReadUtf8Bytes(path)
   if raw.startswith(UTF8_BOM):
      raise ValueError(
         f"{path}: file starts with a UTF-8 BOM (EF BB BF); "
         "remove the BOM and re-save as plain UTF-8."
      )
   return raw.decode("utf-8")


def WriteUtf8Lf(path: Path, text: str) -> None:
   """
   Write *text* to *path* as UTF-8 with LF line endings only.

   Any CR characters remaining in *text* are stripped before writing
   so that callers that forgot to normalise do not silently produce CRLF.
   """
   normalised = text.replace("\r\n", "\n").replace("\r", "\n")
   path.write_bytes(normalised.encode("utf-8"))
