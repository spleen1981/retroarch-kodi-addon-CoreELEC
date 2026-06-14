"""Parser and writer for retroarch.cfg.

The retroarch.cfg format is a flat list of `key = "value"` assignments, plus
comments (`# ...`) and blank lines. Order, comments and blank lines must be
preserved across a load/save round-trip so that diffs against upstream remain
reviewable.

Design:
    * Load: stream the file once, classify every line as either a key/value
      pair or "verbatim" (comment, blank, malformed line we don't understand).
    * In-memory model: ordered list of `_Line` objects plus a `key -> index`
      map for O(1) lookups. New keys appended at the end.
    * Save: write to a sibling temporary file then `os.replace()` for atomic
      replacement. Avoids leaving a half-written cfg if power dies mid-write
      (a real concern on CoreELEC set-top boxes).
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping, Optional

# Matches `key = "value"` or `key = value` (unquoted), tolerant of surrounding
# whitespace. The key is restricted to identifier characters, which is the
# RetroArch convention and avoids matching commented-out lines whose first
# non-space character is `#`.
_ASSIGNMENT_RE = re.compile(
    r"""^\s*
        (?P<key>[A-Za-z_][A-Za-z0-9_]*)
        \s*=\s*
        (?:"(?P<qval>[^"]*)"|(?P<uval>[^\s#].*?))
        \s*$""",
    re.VERBOSE,
)


@dataclass
class _Line:
    """One line in the cfg. Either an assignment (key/value set) or verbatim."""
    raw: str
    key: Optional[str] = None
    value: Optional[str] = None

    @property
    def is_assignment(self) -> bool:
        return self.key is not None


def _format_assignment(key: str, value: str) -> str:
    return f'{key} = "{value}"'


class RetroArchConfig:
    """In-memory representation of a retroarch.cfg file.

    Typical usage:
        cfg = RetroArchConfig.load(path)
        cfg["audio_driver"] = "alsa"
        cfg.update({"video_refresh_rate": "60.000000"})
        cfg.save()
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lines: list[_Line] = []
        self._index: dict[str, int] = {}

    # ------------------------------------------------------------------ load

    @classmethod
    def load(cls, path: Path) -> "RetroArchConfig":
        cfg = cls(path)
        if not path.exists():
            return cfg
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                cfg._append_parsed(raw.rstrip("\n"))
        return cfg

    def _append_parsed(self, raw: str) -> None:
        match = _ASSIGNMENT_RE.match(raw)
        if match is None or raw.lstrip().startswith("#"):
            self._lines.append(_Line(raw=raw))
            return
        key = match.group("key")
        value = match.group("qval")
        if value is None:
            value = match.group("uval") or ""
        # Last writer wins if the same key appears twice (matches sed behavior).
        self._lines.append(_Line(raw=raw, key=key, value=value))
        self._index[key] = len(self._lines) - 1

    # ----------------------------------------------------------------- read

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        idx = self._index.get(key)
        if idx is None:
            return default
        return self._lines[idx].value

    def __contains__(self, key: str) -> bool:
        return key in self._index

    def __getitem__(self, key: str) -> str:
        value = self.get(key)
        if value is None:
            raise KeyError(key)
        return value

    def items(self) -> Iterator[tuple[str, str]]:
        for line in self._lines:
            if line.is_assignment and line.value is not None:
                yield (line.key, line.value)  # type: ignore[misc]

    # ---------------------------------------------------------------- write

    def __setitem__(self, key: str, value: str) -> None:
        self.set(key, value)

    def set(self, key: str, value: str) -> None:
        """Set `key` to `value`. Append if absent, replace in place if present."""
        idx = self._index.get(key)
        new_raw = _format_assignment(key, value)
        if idx is None:
            self._lines.append(_Line(raw=new_raw, key=key, value=value))
            self._index[key] = len(self._lines) - 1
        else:
            self._lines[idx] = _Line(raw=new_raw, key=key, value=value)

    def update(self, mapping: Mapping[str, str]) -> None:
        for key, value in mapping.items():
            self.set(key, value)

    def delete(self, key: str) -> bool:
        """Remove an assignment. Returns True if a line was removed."""
        idx = self._index.pop(key, None)
        if idx is None:
            return False
        del self._lines[idx]
        # Rebuild index since list indices have shifted.
        self._index = {
            line.key: i for i, line in enumerate(self._lines)
            if line.is_assignment and line.key is not None
        }
        return True

    def redirect_path_suffix(self, suffix: str, replacement: str) -> int:
        """Replace any value matching `*/<suffix>` with `replacement`.

        Used at first-run to redirect cfg entries that point inside the addon
        installation (read-only, version-pinned) toward the user-writable
        config directory. Returns the number of lines modified.
        """
        # The value must end with `/<suffix>` to match. We do not anchor the
        # leading slash with `^` because some retroarch defaults use a relative
        # path like `:/assets`.
        pattern = re.compile(r".*/" + re.escape(suffix) + r"/?$")
        url_re = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")
        changed = 0
        for line in self._lines:
            if not line.is_assignment or line.value is None or url_re.match(line.value):
                continue
            if pattern.match(line.value):
                line.value = replacement
                line.raw = _format_assignment(line.key, replacement)  # type: ignore[arg-type]
                changed += 1
        return changed

    # ----------------------------------------------------------------- save

    def save(self) -> None:
        """Write atomically: write a sibling temp file then `os.replace()`."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path_str = tempfile.mkstemp(
            prefix=self.path.name + ".",
            suffix=".tmp",
            dir=str(self.path.parent),
        )
        tmp_path = Path(tmp_path_str)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                for line in self._lines:
                    fh.write(line.raw)
                    fh.write("\n")
            # Match permissions of the original file if it existed.
            if self.path.exists():
                try:
                    st = self.path.stat()
                    os.chmod(tmp_path, st.st_mode & 0o7777)
                except OSError:
                    pass
            os.replace(tmp_path, self.path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
