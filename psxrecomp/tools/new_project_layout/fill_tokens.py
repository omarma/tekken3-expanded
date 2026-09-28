#!/usr/bin/env python3
"""Replace @TOKEN@ placeholders (and CI YOUR_* tokens) in scaffold files."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def derive_zip_prefix(name: str) -> str:
    base = re.sub(r"(?i)recomp(iled)?$", "", name).strip()
    caps = re.findall(r"[A-Z][a-z0-9]*|[0-9]+", base)
    if len(caps) >= 3:
        acr = "".join(w[0] for w in caps if w and w[0].isalpha()).lower()
        if 3 <= len(acr) <= 8:
            return acr
    slug = re.sub(r"[^a-z0-9]+", "", base.lower())
    return (slug or "game")[:20]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument(
        "--set-file",
        action="append",
        default=[],
        metavar="KEY=PATH",
        help="Read VALUE from a file (for multiline CMake blocks)",
    )
    ap.add_argument(
        "--ci-placeholders",
        action="store_true",
        help="Also replace YOUR_ZIP_PREFIX / YOUR_GAME_TITLE / yourgame-release",
    )
    args = ap.parse_args()

    repl: dict[str, str] = {}
    for item in args.set:
        if "=" not in item:
            print(f"bad --set {item!r} (want KEY=VALUE)", file=sys.stderr)
            return 2
        k, v = item.split("=", 1)
        repl[k] = v
    for item in args.set_file:
        if "=" not in item:
            print(f"bad --set-file {item!r} (want KEY=PATH)", file=sys.stderr)
            return 2
        k, path = item.split("=", 1)
        repl[k] = Path(path).read_text(encoding="utf-8").rstrip("\n")

    text = Path(args.src).read_text(encoding="utf-8")
    for k, v in repl.items():
        text = text.replace(f"@{k}@", v)

    if args.ci_placeholders:
        zp = repl.get("ZIP_PREFIX", "game")
        title = repl.get("GAME_TITLE") or repl.get("WINDOW_TITLE") or "Game"
        # Collapse runs of whitespace; escape for YAML double-quoted release names
        # (template uses name: "YOUR_GAME_TITLE ${{ … }}").
        title = re.sub(r"\s+", " ", title.strip())
        title_yaml = (
            title.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", " ")
            .replace("\r", "")
        )
        text = text.replace("YOUR_ZIP_PREFIX", zp)
        text = text.replace("YOUR_GAME_TITLE", title_yaml)
        text = text.replace("yourgame-release", f"{zp}-release")

    Path(args.dst).parent.mkdir(parents=True, exist_ok=True)
    Path(args.dst).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
