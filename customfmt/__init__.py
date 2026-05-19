"""customfmt – opinionated Python formatter for self-assignment blocks."""

from .formatter import (
    Violation,
    check_lines,
    fix_lines,
    process_file,
    RULE_ALIGN_SELF,
    RULE_TRAILING_WS,
    RULE_FINAL_NEWLINE,
)

__all__ = [
    "Violation",
    "check_lines",
    "fix_lines",
    "process_file",
    "RULE_ALIGN_SELF",
    "RULE_TRAILING_WS",
    "RULE_FINAL_NEWLINE",
]
