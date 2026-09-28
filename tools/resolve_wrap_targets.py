"""Resolve, for each --wrap symbol, the translation units to redefine.

Apple's ld64 has no --wrap, so the Apple build reproduces it with the
preprocessor: the defining TU is compiled with `-D<sym>=__real_<sym>` and the
wrapping TU with `-D__wrap_<sym>=<sym>`. Call sites elsewhere keep referring to
`<sym>` and therefore reach the wrapper, exactly as --wrap redirects them, and
a wrapper that delegates to `__real_<sym>` still finds the stock routine.

Prints one `symbol|defining_file|wrapper_file` record per symbol; the wrapper
field is empty when no src/*.c defines it, which means a generated wrapper the
caller must supply. Fails loudly rather than guessing: a symbol with no
definition, or more than one, stops the configure step.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def guest_definition(text: str, sym: str) -> bool:
    """Recompiled shards spell every routine the same way."""
    return re.search(rf"^void {re.escape(sym)}\(CPUState\* cpu\)", text, re.M) is not None


def _defines(text: str, name: str) -> bool:
    """True when some line opens a definition of *name*.

    A definition starts at column 0, is not an `extern` declaration, and does
    not end its line with `;`. That last test is what separates
    `int spu_snapshot_read(const uint8_t *p, uint32_t len) {` from
    `extern int spu_snapshot_read(const uint8_t* p, uint32_t len);`, while
    still accepting a one-line body such as
    `void __wrap_spu_init(void) { stop_voices();__real_spu_init(); }`,
    whose semicolons sit inside the braces.
    """
    head = rf"^(?!extern\b)[A-Za-z_][A-Za-z0-9_ \t\*]*\b{re.escape(name)}\s*\("
    for line in text.splitlines():
        if re.match(head, line) and not line.rstrip().endswith(";"):
            return True
    return False


def host_definition(text: str, sym: str) -> bool:
    return _defines(text, sym)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--symbols", required=True, help="semicolon or comma separated")
    args = ap.parse_args()

    root: Path = args.root.resolve()
    symbols = [s for s in re.split(r"[;,]", args.symbols) if s.strip()]

    shards = sorted((root / "generated").glob("SLUS_004.02_full_*.c"))
    hosts = sorted((root / "psxrecomp/runtime/src").glob("*.c"))
    wrappers = sorted((root / "src").glob("*.c"))
    if not shards:
        print("no recompiled shards under generated/", file=sys.stderr)
        return 1

    # Read each file once: 39 symbols against 45 shards must not reread them.
    shard_text = {f: f.read_text(encoding="utf-8", errors="replace") for f in shards}
    host_text = {f: f.read_text(encoding="utf-8", errors="replace") for f in hosts}
    wrapper_text = {f: f.read_text(encoding="utf-8", errors="replace") for f in wrappers}

    failures: list[str] = []
    records: list[str] = []
    for sym in symbols:
        defs = [f for f, t in shard_text.items() if guest_definition(t, sym)]
        defs += [f for f, t in host_text.items() if host_definition(t, sym)]
        if len(defs) != 1:
            found = ", ".join(str(f.relative_to(root)) for f in defs) or "nothing"
            failures.append(f"{sym}: expected exactly one definition, found {found}")
            continue
        # Wrappers are not all void: spu_snapshot_read returns int and
        # tekken3_outfits_input returns uint16_t.
        hits = [f for f, t in wrapper_text.items() if _defines(t, f"__wrap_{sym}")]
        if len(hits) > 1:
            names = ", ".join(str(f.relative_to(root)) for f in hits)
            failures.append(f"{sym}: {len(hits)} wrappers under src/ ({names})")
            continue
        wrapper = str(hits[0]) if hits else ""
        records.append(f"{sym}|{defs[0]}|{wrapper}")

    if failures:
        for line in failures:
            print(line, file=sys.stderr)
        return 1
    print("\n".join(records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
