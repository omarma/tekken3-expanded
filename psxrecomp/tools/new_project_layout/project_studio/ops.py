"""Apply migration plan steps (setup-host exclusively)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from fill_tokens import derive_zip_prefix

from .models import ApplyResult, MigrateOptions, Plan
from .naming import (
    boot_exe_from_game_toml,
    build_token_map,
    entry_pc_from_game_toml,
    infer_project_name,
    normalize_lobby_url,
    players_from_cmake,
    window_title_from_cmake,
    window_title_from_name,
)
from .paths import ci_setup_release_template, templates_dir, toolkit_dir


def _run(cmd: list[str], cwd: Path, dry_run: bool) -> tuple[bool, str]:
    if dry_run:
        return True, "dry-run: " + " ".join(cmd)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return False, str(exc)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        return False, err or f"exit {proc.returncode}"
    return True, (proc.stdout or "").strip()


def _write(path: Path, text: str, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fill(src: Path, dst: Path, tokens: dict[str, str], dry_run: bool, *, ci: bool = False) -> None:
    text = src.read_text(encoding="utf-8")
    for k, v in tokens.items():
        text = text.replace(f"@{k}@", v)
    if ci:
        zp = tokens.get("ZIP_PREFIX", "game")
        title = tokens.get("GAME_TITLE") or tokens.get("WINDOW_TITLE") or "Game"
        title = " ".join(title.split())
        title_yaml = (
            title.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", "")
        )
        text = text.replace("YOUR_ZIP_PREFIX", zp)
        text = text.replace("YOUR_GAME_TITLE", title_yaml)
        text = text.replace("yourgame-release", f"{zp}-release")
    _write(dst, text, dry_run)


def _is_real_psxrecomp(path: Path) -> bool:
    return (path / "runtime" / "runtime.cmake").is_file()


def _resolve_tokens(root: Path, options: MigrateOptions) -> dict[str, str]:
    name = options.project_name or infer_project_name(root)
    boot = (
        options.boot_exe
        or boot_exe_from_game_toml(root / "game.toml")
        or "SLUS_01234"
    )
    players = options.players
    if players == 2:
        detected = players_from_cmake(root / "CMakeLists.txt")
        if detected is not None:
            players = detected
    title = options.window_title or window_title_from_cmake(root / "CMakeLists.txt")
    if not title:
        # Prefer game.toml window_title
        gt = (root / "game.toml").read_text(encoding="utf-8", errors="replace") if (
            root / "game.toml"
        ).is_file() else ""
        for line in gt.splitlines():
            if line.strip().startswith("window_title"):
                _, _, v = line.partition("=")
                title = v.strip().strip('"').strip("'")
                break
    if not title:
        title = window_title_from_name(name)

    has_boxart = (root / "launcher_assets" / "img" / "boxart.tga").is_file()
    # Also treat pending relocate as has_boxart for cmake wiring after relocate runs first
    if not has_boxart:
        for p in (
            root / "recomp" / "launcher" / "boxart.tga",
            root / "recomp" / "launcher" / "boxart.png",
        ):
            if p.is_file():
                has_boxart = options.relocate_boxart
                break

    enable_netplay = options.enable_netplay and players >= 2
    return build_token_map(
        name=name,
        boot_exe=boot,
        players=players,
        zip_prefix=options.zip_prefix or derive_zip_prefix(name),
        window_title=title,
        entry_pc=entry_pc_from_game_toml(root / "game.toml"),
        lobby_url=normalize_lobby_url(options.lobby_url),
        enable_recomp_ui=options.enable_recomp_ui,
        enable_wizard=options.enable_wizard if options.enable_recomp_ui else False,
        enable_netplay=enable_netplay if options.enable_recomp_ui else False,
        has_boxart=has_boxart,
    )


def op_rename_psxrecomp_submodule(root: Path, options: MigrateOptions) -> ApplyResult:
    v4 = root / "psxrecomp-v4"
    dest = root / "psxrecomp"
    changed: list[str] = []

    if not v4.exists() and _is_real_psxrecomp(dest):
        return ApplyResult("rename_psxrecomp_submodule", True, "Already using psxrecomp/", [])

    if not v4.exists():
        return ApplyResult(
            "rename_psxrecomp_submodule", False, "psxrecomp-v4 not found", []
        )

    if dest.exists() and not _is_real_psxrecomp(dest):
        stub_bak = root / "psxrecomp.stub.bak"
        if options.dry_run:
            msg = f"dry-run: move stub {dest} → {stub_bak}, then {v4} → {dest}"
        else:
            if stub_bak.exists():
                shutil.rmtree(stub_bak)
            dest.rename(stub_bak)
            changed.append(str(stub_bak.relative_to(root)))
            msg = f"Moved stub psxrecomp/ → {stub_bak.name}"
    elif dest.exists() and _is_real_psxrecomp(dest):
        # Real tree already — drop v4 submodule entry if possible
        msg = "psxrecomp/ already real; will update .gitmodules and leave v4 for manual removal"
    else:
        msg = ""

    if not dest.exists() or not _is_real_psxrecomp(dest):
        ok, out = _run(["git", "mv", "psxrecomp-v4", "psxrecomp"], root, options.dry_run)
        if not ok:
            # Fallback without git mv
            if options.dry_run:
                out = "dry-run: shutil.move psxrecomp-v4 → psxrecomp"
            else:
                shutil.move(str(v4), str(dest))
                out = "Moved psxrecomp-v4 → psxrecomp (without git mv)"
        changed.append("psxrecomp")
        msg = (msg + "; " if msg else "") + out

    # Rewrite .gitmodules
    gm = root / ".gitmodules"
    if gm.is_file():
        text = gm.read_text(encoding="utf-8")
        new = text.replace('path = psxrecomp-v4', "path = psxrecomp")
        new = new.replace('[submodule "psxrecomp-v4"]', '[submodule "psxrecomp"]')
        if new != text:
            _write(gm, new, options.dry_run)
            changed.append(".gitmodules")

    # Patch CMakeLists PSXRECOMP_ROOT path if present
    cmake = root / "CMakeLists.txt"
    if cmake.is_file():
        text = cmake.read_text(encoding="utf-8")
        new = text.replace("psxrecomp-v4", "psxrecomp")
        if new != text:
            _write(cmake, new, options.dry_run)
            changed.append("CMakeLists.txt")

    return ApplyResult("rename_psxrecomp_submodule", True, msg or "Renamed submodule", changed)


def op_ensure_psxrecomp_submodule(root: Path, options: MigrateOptions) -> ApplyResult:
    if _is_real_psxrecomp(root / "psxrecomp"):
        return ApplyResult("ensure_psxrecomp_submodule", True, "Already present", [])
    url = "https://github.com/mstan/psxrecomp.git"
    ok, out = _run(
        ["git", "submodule", "add", "-b", "master", url, "psxrecomp"],
        root,
        options.dry_run,
    )
    if not ok:
        return ApplyResult("ensure_psxrecomp_submodule", False, out, [])
    ok2, out2 = _run(
        ["git", "submodule", "update", "--init", "--recursive", "psxrecomp"],
        root,
        options.dry_run,
    )
    return ApplyResult(
        "ensure_psxrecomp_submodule",
        ok2,
        out2 or out or "Added psxrecomp submodule",
        ["psxrecomp", ".gitmodules"],
    )


def op_ensure_recomp_ui_submodule(root: Path, options: MigrateOptions) -> ApplyResult:
    if (root / "recomp-ui").is_dir() and (
        (root / "recomp-ui" / "CMakeLists.txt").is_file()
        or (root / "recomp-ui" / ".git").exists()
    ):
        return ApplyResult("ensure_recomp_ui_submodule", True, "Already present", [])
    url = "https://github.com/mstan/recomp-ui.git"
    ok, out = _run(
        ["git", "submodule", "add", "-b", "master", url, "recomp-ui"],
        root,
        options.dry_run,
    )
    if not ok:
        return ApplyResult("ensure_recomp_ui_submodule", False, out, [])
    _run(
        ["git", "submodule", "update", "--init", "--recursive", "recomp-ui"],
        root,
        options.dry_run,
    )
    return ApplyResult(
        "ensure_recomp_ui_submodule",
        True,
        out or "Added recomp-ui submodule",
        ["recomp-ui", ".gitmodules"],
    )


def op_emit_codegen_setup(root: Path, options: MigrateOptions) -> ApplyResult:
    tokens = _resolve_tokens(root, options)
    tdir = templates_dir()
    changed = []
    for name in ("codegen_setup.c", "codegen_setup.h"):
        src = tdir / f"{name}.in"
        dst = root / name
        if dst.is_file() and not options.force:
            # Refresh if missing forward helper
            if name.endswith(".c") and "psx_game_codegen_forward_if_built" in dst.read_text(
                encoding="utf-8", errors="replace"
            ):
                continue
        _fill(src, dst, tokens, options.dry_run)
        changed.append(name)
    if not changed:
        return ApplyResult("emit_codegen_setup", True, "Already up to date", [])
    return ApplyResult("emit_codegen_setup", True, "Wrote codegen_setup", changed)


def op_emit_version(root: Path, options: MigrateOptions) -> ApplyResult:
    dst = root / "VERSION"
    if dst.is_file() and not options.force:
        return ApplyResult("emit_version", True, "VERSION already exists", [])
    src = templates_dir() / "VERSION.in"
    text = "0.1.0\n" if not src.is_file() else src.read_text(encoding="utf-8")
    # VERSION.in may have tokens — keep simple
    text = text.replace("@VERSION@", "0.1.0")
    if not text.endswith("\n"):
        text += "\n"
    _write(dst, text if "@" not in text else "0.1.0\n", options.dry_run)
    return ApplyResult("emit_version", True, "Wrote VERSION", ["VERSION"])


def op_emit_symbols_toml(root: Path, options: MigrateOptions) -> ApplyResult:
    dst = root / "symbols.toml"
    if dst.is_file() and not options.force:
        return ApplyResult("emit_symbols_toml", True, "symbols.toml already exists", [])
    tokens = _resolve_tokens(root, options)
    _fill(templates_dir() / "symbols.toml.in", dst, tokens, options.dry_run)
    return ApplyResult("emit_symbols_toml", True, "Wrote symbols.toml", ["symbols.toml"])


def op_emit_sync_symbols(root: Path, options: MigrateOptions) -> ApplyResult:
    src = toolkit_dir() / "sync_symbols.py"
    dst = root / "tools" / "sync_symbols.py"
    if dst.is_file() and not options.force:
        return ApplyResult("emit_sync_symbols", True, "Already present", [])
    if options.dry_run:
        return ApplyResult("emit_sync_symbols", True, "dry-run: copy sync_symbols.py", ["tools/sync_symbols.py"])
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return ApplyResult("emit_sync_symbols", True, "Installed tools/sync_symbols.py", ["tools/sync_symbols.py"])


def op_merge_gitignore(root: Path, options: MigrateOptions) -> ApplyResult:
    src = templates_dir() / "gitignore.in"
    template = src.read_text(encoding="utf-8")
    tokens = _resolve_tokens(root, options)
    for k, v in tokens.items():
        template = template.replace(f"@{k}@", v)

    dst = root / ".gitignore"
    existing = dst.read_text(encoding="utf-8") if dst.is_file() else ""
    required = [
        "/generated/",
        "/disc/",
        "/bios/",
        "/dist/",
        "/build/",
        "/build-*/",
        "/saves/",
        "*.bin",
        "*.cue",
    ]
    additions = []
    for pat in required:
        if pat not in existing:
            additions.append(pat)

    if not existing:
        _write(dst, template if not template.startswith("@") else "\n".join(required) + "\n", options.dry_run)
        return ApplyResult("merge_gitignore", True, "Wrote .gitignore from template", [".gitignore"])

    if not additions:
        return ApplyResult("merge_gitignore", True, "No gitignore changes needed", [])

    block = (
        "\n# --- PSXRecomp setup-host (project studio) ---\n"
        + "\n".join(additions)
        + "\n"
    )
    _write(dst, existing.rstrip() + "\n" + block, options.dry_run)
    return ApplyResult(
        "merge_gitignore",
        True,
        f"Appended {len(additions)} ignore rules",
        [".gitignore"],
    )


def op_emit_mods_preloaded(root: Path, options: MigrateOptions) -> ApplyResult:
    base = root / "mods" / "preloaded"
    readme = base / "README.md"
    packages = base / "packages" / ".gitkeep"
    if readme.is_file() and (base / "packages").is_dir() and not options.force:
        return ApplyResult("emit_mods_preloaded", True, "Already present", [])
    if options.dry_run:
        return ApplyResult(
            "emit_mods_preloaded",
            True,
            "dry-run: stub mods/preloaded",
            ["mods/preloaded/README.md"],
        )
    packages.parent.mkdir(parents=True, exist_ok=True)
    packages.write_text("", encoding="utf-8")
    readme.write_text(
        "# Preloaded mods\n\n"
        "Ship default-off `.psxmod` packages under `packages/<id>/<version>/`.\n"
        "Setup-host releases copy this tree beside the executable when present.\n",
        encoding="utf-8",
    )
    return ApplyResult(
        "emit_mods_preloaded",
        True,
        "Created mods/preloaded stub",
        ["mods/preloaded/README.md", "mods/preloaded/packages/.gitkeep"],
    )


def op_relocate_boxart(root: Path, options: MigrateOptions) -> ApplyResult:
    dest_dir = root / "launcher_assets" / "img"
    dest = dest_dir / "boxart.tga"
    if dest.is_file() and not options.force:
        return ApplyResult("relocate_boxart", True, "Modern boxart already present", [])

    sources = [
        root / "recomp" / "launcher" / "boxart.tga",
        root / "recomp" / "launcher" / "boxart.png",
    ]
    src = next((p for p in sources if p.is_file()), None)
    if src is None:
        return ApplyResult("relocate_boxart", False, "No legacy boxart found", [])

    if options.dry_run:
        return ApplyResult(
            "relocate_boxart",
            True,
            f"dry-run: copy {src.name} → launcher_assets/img/boxart.tga",
            ["launcher_assets/img/boxart.tga"],
        )

    dest_dir.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == ".tga":
        shutil.copy2(src, dest)
    else:
        # Keep png beside expected path with note — TGA preferred by launcher
        shutil.copy2(src, dest_dir / src.name)
        (dest_dir / "BOXART_SOURCE.txt").write_text(
            f"Copied from {src.relative_to(root)}; convert to boxart.tga if needed.\n",
            encoding="utf-8",
        )
        return ApplyResult(
            "relocate_boxart",
            True,
            f"Copied {src.name} (not TGA — convert for LAUNCHER_BOXART)",
            [str((dest_dir / src.name).relative_to(root))],
        )

    (dest_dir / "BOXART_SOURCE.txt").write_text(
        f"Relocated from {src.relative_to(root)} by project studio.\n",
        encoding="utf-8",
    )
    return ApplyResult(
        "relocate_boxart",
        True,
        "Relocated boxart to launcher_assets/img/boxart.tga",
        ["launcher_assets/img/boxart.tga", "launcher_assets/img/BOXART_SOURCE.txt"],
    )


def op_emit_boxart_stub(root: Path, options: MigrateOptions) -> ApplyResult:
    dest_dir = root / "launcher_assets" / "img"
    if dest_dir.is_dir() and not options.force:
        return ApplyResult("emit_boxart_stub", True, "launcher_assets already exists", [])
    if options.dry_run:
        return ApplyResult("emit_boxart_stub", True, "dry-run: mkdir launcher_assets/img", [])
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / ".gitkeep").write_text("", encoding="utf-8")
    return ApplyResult(
        "emit_boxart_stub",
        True,
        "Created launcher_assets/img (add boxart.tga later)",
        ["launcher_assets/img/.gitkeep"],
    )


def op_rewrite_cmake_setup_host(root: Path, options: MigrateOptions) -> ApplyResult:
    tokens = _resolve_tokens(root, options)
    # Force wizard for setup-host policy
    if not options.enable_wizard and options.enable_recomp_ui:
        # Still rewrite with wizard ON — exclusive setup-host
        options = MigrateOptions(**{**options.to_dict(), "enable_wizard": True})
        tokens = _resolve_tokens(root, options)

    cmake = root / "CMakeLists.txt"
    changed = ["CMakeLists.txt"]
    extras_note = root / "CMakeLists.migrate_extras.txt"

    old = cmake.read_text(encoding="utf-8") if cmake.is_file() else ""
    # Capture extras for the user
    extras_bits = []
    if "EXTRAS_SOURCES" in old:
        extras_bits.append("Old CMakeLists used EXTRAS_SOURCES — re-attach mod/plugin sources.")
    if "add_test(" in old or "BUILD_TESTING" in old:
        extras_bits.append("Old CMakeLists had tests — restore from CMakeLists.txt.pre_migrate.bak.")
    if "POST_BUILD" in old and "mods/preloaded" in old:
        extras_bits.append("Old CMakeLists copied mods/preloaded POST_BUILD — re-add if needed.")

    bak = root / "CMakeLists.txt.pre_migrate.bak"
    if cmake.is_file() and not options.dry_run:
        if not bak.is_file() or options.force:
            bak.write_text(old, encoding="utf-8")
            changed.append("CMakeLists.txt.pre_migrate.bak")

    _fill(templates_dir() / "CMakeLists.txt.in", cmake, tokens, options.dry_run)

    if extras_bits and not options.dry_run:
        extras_note.write_text(
            "Preserved notes after setup-host CMake rewrite:\n\n"
            + "\n".join(f"- {b}" for b in extras_bits)
            + "\n\nFull previous file: CMakeLists.txt.pre_migrate.bak\n",
            encoding="utf-8",
        )
        changed.append("CMakeLists.migrate_extras.txt")

    return ApplyResult(
        "rewrite_cmake_setup_host",
        True,
        "Wrote setup-host CMakeLists.txt (backup .pre_migrate.bak)",
        changed,
    )


def op_emit_packager(root: Path, options: MigrateOptions) -> ApplyResult:
    tokens = _resolve_tokens(root, options)
    dst = root / "scripts" / "package_setup_release.sh"
    if dst.is_file() and not options.force:
        return ApplyResult("emit_packager", True, "Packager already present", [])
    _fill(templates_dir() / "package_setup_release.sh.in", dst, tokens, options.dry_run)
    if not options.dry_run:
        dst.chmod(dst.stat().st_mode | 0o111)
    return ApplyResult(
        "emit_packager",
        True,
        "Wrote scripts/package_setup_release.sh",
        ["scripts/package_setup_release.sh"],
    )


def op_emit_ci_workflow(root: Path, options: MigrateOptions) -> ApplyResult:
    tokens = _resolve_tokens(root, options)
    src = ci_setup_release_template(root)
    if src is None:
        return ApplyResult(
            "emit_ci_workflow",
            False,
            "Cannot find docs/ci/templates/setup-release.yml (need psxrecomp submodule)",
            [],
        )
    dst = root / ".github" / "workflows" / "release.yml"
    if dst.is_file() and not options.force and "YOUR_ZIP_PREFIX" not in dst.read_text(
        encoding="utf-8", errors="replace"
    ):
        return ApplyResult("emit_ci_workflow", True, "release.yml already filled", [])
    _fill(src, dst, tokens, options.dry_run, ci=True)
    return ApplyResult(
        "emit_ci_workflow",
        True,
        "Wrote .github/workflows/release.yml (setup-host)",
        [".github/workflows/release.yml"],
    )


def op_annotate_legacy_packaging(root: Path, options: MigrateOptions) -> ApplyResult:
    note = root / "packaging" / "SETUP_HOST_MIGRATION.txt"
    text = (
        "This title is migrating to setup-host releases only.\n"
        "Do not ship prebuilt generated game C.\n"
        "Use scripts/package_setup_release.sh + .github/workflows/release.yml\n"
        "(see psxrecomp/docs/GAME_PROJECT_SETUP.md and docs/ci/HOST_ONLY_RELEASES.md).\n"
        "Legacy package_release scripts in this folder are obsolete for public releases.\n"
    )
    if (root / "packaging").is_dir():
        _write(note, text, options.dry_run)
        return ApplyResult(
            "annotate_legacy_packaging",
            True,
            "Wrote packaging/SETUP_HOST_MIGRATION.txt",
            ["packaging/SETUP_HOST_MIGRATION.txt"],
        )
    # tools-only legacy
    tools_note = root / "tools" / "SETUP_HOST_MIGRATION.txt"
    _write(tools_note, text, options.dry_run)
    return ApplyResult(
        "annotate_legacy_packaging",
        True,
        "Wrote tools/SETUP_HOST_MIGRATION.txt",
        ["tools/SETUP_HOST_MIGRATION.txt"],
    )


def op_probe_disc_refresh(root: Path, options: MigrateOptions) -> ApplyResult:
    if not options.disc:
        return ApplyResult(
            "probe_disc_refresh",
            False,
            "Pass --disc path/to/game.cue to refresh identity",
            [],
        )
    disc = Path(options.disc).expanduser().resolve()
    if not disc.is_file():
        return ApplyResult("probe_disc_refresh", False, f"Disc not found: {disc}", [])

    probe = toolkit_dir() / "probe_disc.py"
    if not probe.is_file():
        return ApplyResult("probe_disc_refresh", False, "probe_disc.py missing from toolkit", [])

    name = options.project_name or infer_project_name(root)
    players = options.players
    cmd = [
        sys.executable,
        str(probe),
        str(disc),
        "--write-game-toml",
        str(root / "game.toml"),
        "--write-catalog",
        str(root / "catalog_identity.json"),
        "--write-seeds",
        str(root / "seeds" / "ghidra_funcs.txt"),
        "--out-dir",
        "disc",
        "--disc-rel",
        "disc/" + disc.name,
        "--players",
        str(players),
        "--display-name",
        name,
    ]
    if options.dry_run:
        return ApplyResult(
            "probe_disc_refresh",
            True,
            "dry-run: " + " ".join(cmd),
            ["game.toml", "catalog_identity.json", "seeds/ghidra_funcs.txt"],
        )

    (root / "seeds").mkdir(parents=True, exist_ok=True)
    ok, out = _run(cmd, root, dry_run=False)
    if not ok:
        return ApplyResult("probe_disc_refresh", False, out, [])
    return ApplyResult(
        "probe_disc_refresh",
        True,
        out or "probe_disc completed",
        ["game.toml", "catalog_identity.json", "seeds/ghidra_funcs.txt"],
    )


def op_record_framework_pins(root: Path, options: MigrateOptions) -> ApplyResult:
    record = None
    for base in (root / "psxrecomp", root / "psxrecomp-v4"):
        cand = base / "tools" / "ci" / "record_pins.sh"
        if cand.is_file():
            record = cand
            break
    dst = root / "framework_pins.txt"
    if record is None:
        # Best-effort: git rev-parse in submodules
        lines = []
        for name in ("psxrecomp", "recomp-ui"):
            sub = root / name
            if not sub.is_dir():
                continue
            ok, out = _run(["git", "rev-parse", "HEAD"], sub, options.dry_run)
            if ok and out:
                short = out[:7] if not options.dry_run else "dryrun"
                lines.append(f"{name}={short} ({out})")
        if not lines:
            return ApplyResult(
                "record_framework_pins",
                False,
                "No psxrecomp submodule to record pins from",
                [],
            )
        text = "\n".join(lines) + "\n"
        _write(dst, text, options.dry_run)
        return ApplyResult("record_framework_pins", True, "Wrote framework_pins.txt", ["framework_pins.txt"])

    if options.dry_run:
        return ApplyResult(
            "record_framework_pins",
            True,
            f"dry-run: {record} --root {root}",
            ["framework_pins.txt"],
        )
    proc = subprocess.run(
        ["bash", str(record), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(root),
    )
    body = (proc.stdout or "").strip()
    if proc.returncode != 0 and not body:
        return ApplyResult(
            "record_framework_pins",
            False,
            (proc.stderr or f"exit {proc.returncode}").strip(),
            [],
        )
    if body:
        dst.write_text(body + "\n", encoding="utf-8")
    return ApplyResult(
        "record_framework_pins",
        True,
        "Wrote framework_pins.txt",
        ["framework_pins.txt"],
    )


_OPS = {
    "rename_psxrecomp_submodule": op_rename_psxrecomp_submodule,
    "ensure_psxrecomp_submodule": op_ensure_psxrecomp_submodule,
    "ensure_recomp_ui_submodule": op_ensure_recomp_ui_submodule,
    "emit_codegen_setup": op_emit_codegen_setup,
    "emit_version": op_emit_version,
    "emit_symbols_toml": op_emit_symbols_toml,
    "emit_sync_symbols": op_emit_sync_symbols,
    "merge_gitignore": op_merge_gitignore,
    "emit_mods_preloaded": op_emit_mods_preloaded,
    "relocate_boxart": op_relocate_boxart,
    "emit_boxart_stub": op_emit_boxart_stub,
    "rewrite_cmake_setup_host": op_rewrite_cmake_setup_host,
    "emit_packager": op_emit_packager,
    "emit_ci_workflow": op_emit_ci_workflow,
    "annotate_legacy_packaging": op_annotate_legacy_packaging,
    "probe_disc_refresh": op_probe_disc_refresh,
    "record_framework_pins": op_record_framework_pins,
}


def apply_plan(plan: Plan, *, selected: list[str] | None = None) -> list[ApplyResult]:
    root = Path(plan.root)
    options = plan.options
    results: list[ApplyResult] = []

    # Setup-host exclusive: never leave wizard off when CI/packager are applied
    if options.enable_ci or any(
        s.op_id in ("emit_ci_workflow", "emit_packager", "rewrite_cmake_setup_host")
        and s.selected
        for s in plan.steps
    ):
        options.enable_wizard = True
        options.enable_recomp_ui = True

    for step in plan.steps:
        if not step.selected:
            continue
        if selected is not None and step.op_id not in selected:
            continue
        fn = _OPS.get(step.op_id)
        if fn is None:
            results.append(
                ApplyResult(step.op_id, False, f"Unknown op: {step.op_id}", [])
            )
            continue
        try:
            results.append(fn(root, options))
        except Exception as exc:  # noqa: BLE001 — surface to CLI/GUI
            results.append(ApplyResult(step.op_id, False, f"{type(exc).__name__}: {exc}", []))
    return results


def list_ops() -> list[str]:
    return list(_OPS.keys())
