"""CLI: audit / plan / apply / gui for Project Studio."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow `python migrate_project.py` and `python -m project_studio`
_TOOLKIT = Path(__file__).resolve().parent.parent
if str(_TOOLKIT) not in sys.path:
    sys.path.insert(0, str(_TOOLKIT))

from project_studio import __version__  # noqa: E402
from project_studio.detect import audit_project  # noqa: E402
from project_studio.models import MigrateOptions  # noqa: E402
from project_studio.ops import apply_plan, list_ops  # noqa: E402
from project_studio.plan import build_plan  # noqa: E402


def _print_audit(report, *, as_json: bool) -> int:
    if as_json:
        print(json.dumps(report.to_dict(), indent=2))
        return 0 if report.to_dict()["fail_count"] == 0 else 1

    print(f"Project Studio audit  v{__version__}")
    print(f"  root:    {report.root}")
    print(f"  name:    {report.project_name}")
    print(f"  layout:  {report.layout.value}")
    print(f"  boot:    {report.boot_exe or '(unknown)'}")
    print()
    width = max(len(c.title) for c in report.checks) if report.checks else 10
    for c in report.checks:
        mark = {
            "pass": "OK  ",
            "fail": "FAIL",
            "warn": "WARN",
            "skip": "SKIP",
        }.get(c.status.value, "????")
        print(f"  [{mark}] {c.title:<{width}}  {c.detail}")
        if c.fix_op and c.status.value in ("fail", "warn"):
            print(f"         → op: {c.fix_op}")
    if report.notes:
        print()
        for n in report.notes:
            print(f"  note: {n}")
    fails = sum(1 for c in report.checks if c.status.value == "fail")
    warns = sum(1 for c in report.checks if c.status.value == "warn")
    print()
    print(f"Summary: {fails} fail, {warns} warn  (setup-host releases only)")
    return 1 if fails else 0


def _options_from_args(args: argparse.Namespace) -> MigrateOptions:
    only = [x.strip() for x in (args.only or "").split(",") if x.strip()]
    skip = [x.strip() for x in (args.skip or "").split(",") if x.strip()]
    return MigrateOptions(
        disc=args.disc,
        project_name=args.name,
        boot_exe=args.boot_exe,
        players=args.players,
        zip_prefix=args.zip_prefix,
        window_title=args.window_title,
        enable_recomp_ui=not args.no_recomp_ui,
        enable_wizard=not args.no_wizard,
        enable_netplay=args.enable_netplay,
        lobby_url=args.lobby_url,
        enable_ci=not args.no_ci,
        relocate_boxart=not args.no_boxart,
        rewrite_cmake=not args.no_rewrite_cmake,
        merge_gitignore=not args.no_gitignore,
        probe_disc=bool(args.disc) and not args.no_probe,
        record_pins=not args.no_pins,
        force=args.force,
        only=only,
        skip=skip,
        dry_run=args.dry_run,
    )


def cmd_audit(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2
    return _print_audit(audit_project(root), as_json=args.json)


def cmd_plan(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser().resolve()
    opts = _options_from_args(args)
    plan = build_plan(root, opts)
    if args.json:
        print(json.dumps(plan.to_dict(), indent=2))
        return 0
    print(f"Project Studio plan  ({plan.layout.value})")
    print(f"  root: {plan.root}")
    print(f"  dry-run default for apply: use --dry-run")
    print()
    if not plan.steps:
        print("  (no steps — audit looks clean for selected options)")
        return 0
    for i, s in enumerate(plan.steps, 1):
        print(f"  {i:2d}. [{s.op_id}] {s.title}")
        if s.detail:
            print(f"      {s.detail}")
    print()
    print("Apply with: migrate_project.py apply --root … [--dry-run]")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser().resolve()
    opts = _options_from_args(args)
    # Setup-host exclusive hard rules
    opts.enable_wizard = True
    opts.enable_recomp_ui = True
    if opts.players < 2:
        opts.enable_netplay = False

    report = audit_project(root)
    plan = build_plan(root, opts, report)
    if args.json_plan:
        print(json.dumps(plan.to_dict(), indent=2))

    if not plan.steps:
        print("Nothing to apply.")
        return 0

    print(f"Applying {len(plan.steps)} step(s) to {root}"
          + (" [DRY-RUN]" if opts.dry_run else ""))
    results = apply_plan(plan)
    failed = 0
    for r in results:
        mark = "OK" if r.ok else "FAIL"
        print(f"  [{mark}] {r.op_id}: {r.message}")
        for p in r.changed_paths:
            print(f"         · {p}")
        if not r.ok:
            failed += 1
    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    return 1 if failed else 0


def cmd_ops(_: argparse.Namespace) -> int:
    for op in list_ops():
        print(op)
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    from project_studio.gui import run_gui

    root = Path(args.root).expanduser().resolve() if args.root else None
    return run_gui(initial_root=root)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="migrate_project",
        description=(
            "PSXRecomp Project Studio — migrate / update title repos to the "
            "New Project Layout (setup-host releases only)."
        ),
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_root(p: argparse.ArgumentParser, required: bool = True) -> None:
        p.add_argument(
            "--root",
            required=required,
            help="Game repository root",
        )

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--disc", help="Redump .cue for probe_disc refresh")
        p.add_argument("--name", help="Project name override")
        p.add_argument("--boot-exe", help="Boot EXE basename (e.g. SCUS_944.23)")
        p.add_argument("--players", type=int, default=2)
        p.add_argument("--zip-prefix", help="CI/zip prefix")
        p.add_argument("--window-title", help="WINDOW_TITLE override")
        p.add_argument("--enable-netplay", action="store_true")
        p.add_argument("--lobby-url", default="ws://netplay.retcomm.net:8765")
        p.add_argument("--no-recomp-ui", action="store_true",
                       help="Ignored for setup-host apply (forced on)")
        p.add_argument("--no-wizard", action="store_true",
                       help="Ignored for setup-host apply (forced on)")
        p.add_argument("--no-ci", action="store_true")
        p.add_argument("--no-boxart", action="store_true")
        p.add_argument("--no-rewrite-cmake", action="store_true")
        p.add_argument("--no-gitignore", action="store_true")
        p.add_argument("--no-probe", action="store_true")
        p.add_argument("--no-pins", action="store_true")
        p.add_argument("--force", action="store_true", help="Overwrite existing stubs")
        p.add_argument("--only", help="Comma-separated op ids")
        p.add_argument("--skip", help="Comma-separated op ids to skip")
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--json", action="store_true")

    p_audit = sub.add_parser("audit", help="Audit a title repo")
    add_root(p_audit)
    p_audit.add_argument("--json", action="store_true")
    p_audit.set_defaults(func=cmd_audit)

    p_plan = sub.add_parser("plan", help="Show migration plan")
    add_root(p_plan)
    add_common(p_plan)
    p_plan.set_defaults(func=cmd_plan)

    p_apply = sub.add_parser("apply", help="Apply migration plan")
    add_root(p_apply)
    add_common(p_apply)
    p_apply.add_argument("--json-plan", action="store_true")
    p_apply.set_defaults(func=cmd_apply)

    p_ops = sub.add_parser("ops", help="List op ids")
    p_ops.set_defaults(func=cmd_ops)

    p_gui = sub.add_parser("gui", help="Open Project Studio GUI")
    p_gui.add_argument("--root", default=None, help="Optional initial game root")
    p_gui.set_defaults(func=cmd_gui)

    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
