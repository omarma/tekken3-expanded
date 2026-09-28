#!/usr/bin/env python3
"""starvation_walk.py — query helper for starvation_dump.jsonl.

The starvation ring captures every SIO MMIO event + periodic PC samples
+ SIO state at each event. When the watchdog dumps, we get a JSONL file
where line 0 is the meta and lines 1..N are events in chronological order.

This walker reverses the order and answers questions of the form
"working backward from the watchdog fire, what was the last event that
matched <predicate>?". Reasoning forward through 14K events is wasteful;
reasoning backward is how we naturally diagnose hangs.

Examples:
  starvation_walk.py meta
  starvation_walk.py last kind=CTRL_WRITE
  starvation_walk.py last_change ctrl
  starvation_walk.py last_change stat
  starvation_walk.py last stat=0x0000
  starvation_walk.py last_nonzero stat
  starvation_walk.py since_pc 0xBFC14054 kind=CTRL_WRITE
  starvation_walk.py between 12900 12910
  starvation_walk.py why_idle      # composite: last events that drove SIO idle

Predicate syntax:
  field=value     — equality (decimal or 0xHEX, both sides normalized to int)
  field~regex     — string match (against the JSON value as text)
  field!=value    — not equal
  field>value     — greater (numeric)

Multiple predicates AND together: `kind=CTRL_WRITE ctrl=0x0000`.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

DEFAULT_PATH = Path("starvation_dump.jsonl")

NUMERIC_FIELDS = {
    "seq", "cyc", "us",
    "in_exc", "shift_act", "shift_rem", "buf", "ack_pend", "ack_rem",
    "owner", "bbidx", "dev", "mc", "pad", "slot", "gact", "tx_rdy", "tx_em",
}
HEX_FIELDS = {
    "func", "pc", "ctrl", "stat", "tx", "rx", "i_stat", "i_mask",
}
ALL_FIELDS = NUMERIC_FIELDS | HEX_FIELDS | {"kind"}


def _parse_int(s: str) -> int:
    s = s.strip()
    if s.lower().startswith("0x"):
        return int(s, 16)
    return int(s, 10)


def _coerce(field: str, raw_value: Any) -> Any:
    """Coerce a JSON value to a comparable form per field type."""
    if field == "kind":
        return str(raw_value)
    if field in HEX_FIELDS:
        if isinstance(raw_value, str):
            return _parse_int(raw_value)
        return int(raw_value)
    if field in NUMERIC_FIELDS:
        return int(raw_value)
    return raw_value


def _coerce_pred_value(field: str, raw: str) -> Any:
    if field == "kind":
        return raw
    if field in HEX_FIELDS or field in NUMERIC_FIELDS:
        return _parse_int(raw)
    return raw


PRED_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)(==|!=|=|~|>=|<=|>|<)(.+)$")


def parse_predicate(token: str) -> Callable[[dict], bool]:
    m = PRED_RE.match(token)
    if not m:
        raise ValueError(f"bad predicate: {token!r}")
    field, op, raw = m.group(1), m.group(2), m.group(3)
    if op == "==":
        op = "="

    def get(entry: dict) -> Any:
        if field not in entry:
            return None
        return _coerce(field, entry[field])

    if op == "~":
        rx = re.compile(raw)
        return lambda e: (lambda v: v is not None and rx.search(str(v)))(get(e))

    target = _coerce_pred_value(field, raw)

    if op == "=":
        return lambda e: get(e) == target
    if op == "!=":
        return lambda e: get(e) != target
    if op == ">":
        return lambda e: (lambda v: v is not None and v > target)(get(e))
    if op == "<":
        return lambda e: (lambda v: v is not None and v < target)(get(e))
    if op == ">=":
        return lambda e: (lambda v: v is not None and v >= target)(get(e))
    if op == "<=":
        return lambda e: (lambda v: v is not None and v <= target)(get(e))
    raise ValueError(f"bad op: {op!r}")


def parse_predicates(tokens: Iterable[str]) -> Callable[[dict], bool]:
    preds = [parse_predicate(t) for t in tokens]
    if not preds:
        return lambda _e: True
    return lambda e: all(p(e) for p in preds)


def load(path: Path) -> tuple[dict, list[dict]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return {}, []
    meta_obj = json.loads(lines[0])
    meta = meta_obj.get("meta", {}) if isinstance(meta_obj, dict) else {}
    events: list[dict] = []
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return meta, events


def fmt(e: dict) -> str:
    """Compact one-line entry render."""
    return (
        f"#{e.get('seq'):>5} {e.get('kind','?'):>15} "
        f"cyc={e.get('cyc')} us={e.get('us')} "
        f"func={e.get('func')} pc={e.get('pc')} "
        f"ctrl={e.get('ctrl')} stat={e.get('stat')} "
        f"tx={e.get('tx')} rx={e.get('rx')} "
        f"in_exc={e.get('in_exc')} shift={e.get('shift_act')}/{e.get('shift_rem')} "
        f"ack={e.get('ack_pend')}/{e.get('ack_rem')} "
        f"owner={e.get('owner')} bbidx={e.get('bbidx')} "
        f"dev={e.get('dev')} mc={e.get('mc')} pad={e.get('pad')} "
        f"gact={e.get('gact')} i_stat={e.get('i_stat')} i_mask={e.get('i_mask')}"
    )


def cmd_meta(meta: dict, _events: list[dict], _argv: list[str]) -> int:
    for k, v in meta.items():
        print(f"{k:>20}: {v}")
    return 0


def cmd_last(meta: dict, events: list[dict], argv: list[str]) -> int:
    pred = parse_predicates(argv)
    for e in reversed(events):
        if pred(e):
            print(fmt(e))
            return 0
    print("no match")
    return 1


def cmd_first(meta: dict, events: list[dict], argv: list[str]) -> int:
    pred = parse_predicates(argv)
    for e in events:
        if pred(e):
            print(fmt(e))
            return 0
    print("no match")
    return 1


def cmd_all(meta: dict, events: list[dict], argv: list[str]) -> int:
    """Print every match (forward order) with optional limit."""
    limit = None
    rest = []
    for tok in argv:
        if tok.startswith("limit="):
            limit = int(tok[len("limit="):])
        else:
            rest.append(tok)
    pred = parse_predicates(rest)
    n = 0
    for e in events:
        if pred(e):
            print(fmt(e))
            n += 1
            if limit and n >= limit:
                break
    print(f"# {n} match(es)", file=sys.stderr)
    return 0 if n > 0 else 1


def cmd_count(meta: dict, events: list[dict], argv: list[str]) -> int:
    pred = parse_predicates(argv)
    n = sum(1 for e in events if pred(e))
    print(n)
    return 0


def cmd_last_change(meta: dict, events: list[dict], argv: list[str]) -> int:
    """Find the last entry where <field> changed value vs the prior entry.

    Optional extra predicates restrict which entries are considered.
    """
    if not argv:
        print("usage: last_change <field> [pred ...]", file=sys.stderr)
        return 2
    field = argv[0]
    if field not in ALL_FIELDS:
        print(f"unknown field: {field}", file=sys.stderr)
        return 2
    pred = parse_predicates(argv[1:])
    last_val = object()
    change_event = None
    prior_event = None
    for e in events:
        if not pred(e):
            continue
        if field not in e:
            continue
        v = _coerce(field, e[field])
        if last_val is object:
            last_val = v
            continue
        if v != last_val:
            change_event = e
            prior_event_at_change = prior_event
            last_val = v
        prior_event = e
    if change_event is None:
        print("no change")
        return 1
    print("LAST CHANGE OF", field)
    if 'prior_event_at_change' in locals() and prior_event_at_change is not None:
        print("  prior:", fmt(prior_event_at_change))
    print("  after:", fmt(change_event))
    return 0


def cmd_last_nonzero(meta: dict, events: list[dict], argv: list[str]) -> int:
    """Last entry where <field> was non-zero."""
    if not argv:
        print("usage: last_nonzero <field>", file=sys.stderr)
        return 2
    field = argv[0]
    pred = parse_predicates(argv[1:])
    for e in reversed(events):
        if not pred(e):
            continue
        if field not in e:
            continue
        v = _coerce(field, e[field])
        if isinstance(v, int) and v != 0:
            print(fmt(e))
            return 0
    print("no nonzero")
    return 1


def cmd_between(meta: dict, events: list[dict], argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: between <seq_a> <seq_b> [pred ...]", file=sys.stderr)
        return 2
    a, b = int(argv[0]), int(argv[1])
    if a > b:
        a, b = b, a
    pred = parse_predicates(argv[2:])
    for e in events:
        s = e.get("seq")
        if s is None:
            continue
        if a <= s <= b and pred(e):
            print(fmt(e))
    return 0


def cmd_since_pc(meta: dict, events: list[dict], argv: list[str]) -> int:
    """Walk forward from the last entry whose pc equals <pc>."""
    if not argv:
        print("usage: since_pc <pc> [pred ...]", file=sys.stderr)
        return 2
    target = _parse_int(argv[0])
    pred = parse_predicates(argv[1:])
    start_idx = None
    for i in range(len(events) - 1, -1, -1):
        pc = events[i].get("pc")
        if pc is None:
            continue
        if _parse_int(pc) == target:
            start_idx = i
            break
    if start_idx is None:
        print("pc not seen")
        return 1
    print(f"# starting at #{events[start_idx].get('seq')}")
    for e in events[start_idx:]:
        if pred(e):
            print(fmt(e))
    return 0


def cmd_why_idle(meta: dict, events: list[dict], argv: list[str]) -> int:
    """Composite walk: identify the events that drove SIO into idle.

    Walks back from the end and reports:
      - last SHIFT_START / SHIFT_DONE / ACK_FIRE
      - last CTRL_WRITE that wrote ctrl=0x0000 or RESET
      - last SELECT_DEASSERT / SELECT_ASSERT
      - last TX_WRITE
      - last STAT value transition before the hang
      - first PC that repeats in the trailing PC samples
    """
    finds = []

    def find_last(label: str, pred: Callable[[dict], bool]):
        for e in reversed(events):
            if pred(e):
                finds.append((label, e))
                return

    find_last("last SHIFT_START", lambda e: e.get("kind") == "SHIFT_START")
    find_last("last SHIFT_DONE",  lambda e: e.get("kind") == "SHIFT_DONE")
    find_last("last ACK_FIRE",    lambda e: e.get("kind") == "ACK_FIRE")
    find_last("last TX_WRITE",    lambda e: e.get("kind") == "TX_WRITE")
    find_last("last RX_READ",     lambda e: e.get("kind") == "RX_READ")
    find_last("last CTRL_WRITE",  lambda e: e.get("kind") == "CTRL_WRITE")
    find_last("last CTRL=0x0000",
              lambda e: e.get("kind") == "CTRL_WRITE"
                        and e.get("ctrl") == "0x0000")
    find_last("last SELECT_ASSERT",
              lambda e: e.get("kind") == "SELECT_ASSERT")
    find_last("last SELECT_DEASSERT",
              lambda e: e.get("kind") == "SELECT_DEASSERT")
    find_last("last RESET",       lambda e: e.get("kind") == "RESET")
    find_last("last STAT_READ",   lambda e: e.get("kind") == "STAT_READ")

    print(f"# meta: psx_cycle_count={meta.get('psx_cycle_count')} "
          f"current_func={meta.get('current_func')} "
          f"in_exception={meta.get('in_exception')} "
          f"i_stat={meta.get('i_stat')} i_mask={meta.get('i_mask')}")
    finds.sort(key=lambda kv: -(kv[1].get("seq") or 0))
    for label, e in finds:
        print(f"{label:>22}: {fmt(e)}")

    # PC-sample histogram (trailing N seconds of PC samples).
    pc_samples = [e for e in events if e.get("kind") == "PC_SAMPLE"]
    if pc_samples:
        hist: dict[tuple[str, str], int] = {}
        for e in pc_samples:
            key = (str(e.get("func")), str(e.get("pc")))
            hist[key] = hist.get(key, 0) + 1
        ranked = sorted(hist.items(), key=lambda kv: -kv[1])
        print("\n# pc-sample histogram (top 5):")
        for (func, pc), n in ranked[:5]:
            pct = 100.0 * n / len(pc_samples)
            print(f"  {n:>5} ({pct:5.1f}%) func={func} pc={pc}")
    return 0


COMMANDS = {
    "meta": cmd_meta,
    "last": cmd_last,
    "first": cmd_first,
    "all": cmd_all,
    "count": cmd_count,
    "last_change": cmd_last_change,
    "last_nonzero": cmd_last_nonzero,
    "between": cmd_between,
    "since_pc": cmd_since_pc,
    "why_idle": cmd_why_idle,
}


def main(argv: list[str]) -> int:
    path = DEFAULT_PATH
    if argv and argv[0].startswith("--file="):
        path = Path(argv[0][len("--file="):])
        argv = argv[1:]
    if not argv:
        print(__doc__)
        print("commands:", " ".join(COMMANDS), file=sys.stderr)
        return 2
    cmd = argv[0]
    rest = argv[1:]
    if cmd not in COMMANDS:
        print(f"unknown command: {cmd}", file=sys.stderr)
        print("commands:", " ".join(COMMANDS), file=sys.stderr)
        return 2
    if not path.exists():
        print(f"no dump at {path}", file=sys.stderr)
        return 2
    meta, events = load(path)
    return COMMANDS[cmd](meta, events, rest)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
