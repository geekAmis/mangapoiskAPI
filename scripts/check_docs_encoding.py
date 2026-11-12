#!/usr/bin/env python3
"""Fail if README/docs are not clean UTF-8 or contain CP1251 mojibake.

The check is intentionally dependency-free so it can run locally and in CI:

    python scripts/check_docs_encoding.py

It verifies:
- strict UTF-8 decoding (no invalid byte sequences);
- no UTF-8 BOM;
- no U+FFFD replacement characters;
- no common UTF-8 -> CP1251 mojibake signatures;
- no mixed CRLF/LF line endings inside one file.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Strong mojibake signatures.  They do not match normal Russian words.
MOJIBAKE = re.compile(
    r"Рџ|Р С|Сѓ|вЂ|РєР°|"
    r"[РС][\u0080-\u00BF\u2010-\u203A]|"
    r"[РС][ѓЂЃ‚„…†‡€‰‹ЊЌЋЏђ‘’“”•–—™љњћџўЈ¤¦§©«¬®±µ¶·»]|"
    r"Ð[\u0080-\u00BF]|Ñ[\u0080-\u00BF]"
)

DEFAULT_FILES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]


def check_file(path: Path) -> list[str]:
    problems: list[str] = []
    data = path.read_bytes()

    if data.startswith(b"\xef\xbb\xbf"):
        problems.append("has UTF-8 BOM")

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [f"invalid UTF-8 at byte {exc.start}: {exc.reason}"]

    if "\ufffd" in text:
        problems.append(f"contains {text.count(chr(0xFFFD))} U+FFFD replacement char(s)")

    for match in MOJIBAKE.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        problems.append(f"mojibake {match.group(0)!r} at line {line}")

    crlf = data.count(b"\r\n")
    lf = data.count(b"\n") - crlf
    if crlf and lf:
        problems.append(f"mixed line endings: {crlf} CRLF and {lf} LF")

    return problems


def main(argv: list[str]) -> int:
    paths = [Path(arg) for arg in argv] if argv else DEFAULT_FILES
    failed = 0
    for path in paths:
        if not path.is_file():
            print(f"skip missing: {path}")
            continue
        problems = check_file(path)
        if problems:
            failed += 1
            print(f"FAIL {path}")
            for problem in problems:
                print(f"  - {problem}")
        else:
            print(f"OK   {path}")

    if failed:
        print(f"\n{failed} file(s) failed the encoding check.")
        return 1
    print(f"\nAll {len(paths)} file(s) are clean UTF-8.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
