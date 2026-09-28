"""Shared audit-config loader.

Reads a TOML config (BIOS or game) into a normalized object that the
psxrecomp audit tools can consume. See `bios/SCPH1001.toml` and
`TombaRecomp/game.toml` for the schema this module accepts.

Project root is auto-detected by walking up from the config file until a
directory containing `CMakeLists.txt` is found; this works for both
configs placed at project root (game.toml) and configs in a subdirectory
(bios/SCPH1001.toml). All paths in the config are resolved relative to
the detected root.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore


def _hex(s, field_name: str) -> int:
    if not isinstance(s, str):
        raise ValueError(f"{field_name}: expected hex string, got {type(s).__name__}")
    return int(s, 16)


@dataclass(frozen=True)
class Region:
    name: str
    rom_start: int        # byte offset into rom file
    rom_end: int          # exclusive
    vaddr_base: int       # virtual address of rom_start


@dataclass(frozen=True)
class Remap:
    description: str
    from_lo: int          # inclusive
    from_hi: int          # exclusive
    to_lo: int            # offset target start


@dataclass
class AuditConfig:
    # Provenance
    config_path: Path
    project_root: Path

    # Program info
    name: str
    rom: Path             # absolute path to ROM/exe
    load_address: int     # vaddr of rom_start of first code region
    text_size: int        # bytes of code segment (for derived bounds)

    # Generated artifacts (derived from rom stem + out_dir)
    out_dir: Path
    full_c: Path
    dispatch_c: Path

    # Audit-specific
    function_starts: Optional[Path]
    regions: List[Region]
    kseg_mask: int
    remaps: List[Remap] = field(default_factory=list)

    def normalize_addr(self, addr: int) -> int:
        """Mirror the dispatch-table normalization rules from the config."""
        phys = addr & self.kseg_mask
        for rm in self.remaps:
            if rm.from_lo <= phys < rm.from_hi:
                phys = phys - rm.from_lo + rm.to_lo
        return phys

    def is_in_code_region(self, vaddr: int) -> bool:
        """True if `vaddr` falls inside any declared code region."""
        for r in self.regions:
            region_end_vaddr = r.vaddr_base + (r.rom_end - r.rom_start)
            if r.vaddr_base <= vaddr < region_end_vaddr:
                return True
        return False


def _find_project_root(config_path: Path) -> Path:
    """Walk up from config_path until we find a root marker.

    Markers (any one is sufficient): `.gitignore`, `.git`, `CMakeLists.txt`.
    `.gitignore` is the most reliable — both psxrecomp and TombaRecomp
    have one at the repo root, while CMakeLists.txt only lives in subdirs
    of psxrecomp (recompiler/, runtime/).
    """
    cur = config_path.parent.resolve()
    for _ in range(8):  # bounded search
        for marker in (".gitignore", ".git", "CMakeLists.txt"):
            if (cur / marker).exists():
                return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    raise FileNotFoundError(
        f"could not locate project root (no .gitignore/.git/CMakeLists.txt) "
        f"walking up from {config_path}"
    )


def load(config_path) -> AuditConfig:
    config_path = Path(config_path).resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"audit config not found: {config_path}")

    root = _find_project_root(config_path)

    with open(config_path, "rb") as f:
        cfg = tomllib.load(f)

    # Program info: [program] (preferred) or [game] (legacy)
    prog = cfg.get("program") or cfg.get("game")
    if prog is None:
        raise KeyError(f"{config_path}: missing [program] or [game] block")

    name = prog["name"]
    rom_field = prog.get("rom") or prog.get("exe")
    if rom_field is None:
        raise KeyError(f"{config_path}: program/game block missing rom/exe path")
    rom = (root / rom_field).resolve()

    load_address = _hex(prog["load_address"], "load_address")
    text_size = _hex(prog["text_size"], "text_size")

    # Recompiler-derived paths
    recomp = cfg.get("recompiler", {})
    out_dir_field = recomp.get("out_dir", "generated")
    out_dir = (root / out_dir_field).resolve()

    # Output filename stem. Explicit override wins; otherwise strip a
    # known binary extension (.BIN/.EXE, case-insensitive) from the rom
    # name. Plain `Path.stem` is wrong here — it would turn "SCUS_942.36"
    # into "SCUS_942" because it treats `.36` as an extension.
    out_stem = recomp.get("out_stem")
    if not out_stem:
        rom_name = Path(rom_field).name
        upper = rom_name.upper()
        if upper.endswith(".BIN") or upper.endswith(".EXE"):
            out_stem = rom_name[:-4]
        else:
            out_stem = rom_name
    full_c = out_dir / f"{out_stem}_full.c"
    dispatch_c = out_dir / f"{out_stem}_dispatch.c"

    # Audit block
    audit = cfg.get("audit")
    if audit is None:
        raise KeyError(f"{config_path}: missing [audit] block")

    fs_field = audit.get("function_starts")
    function_starts = (root / fs_field).resolve() if fs_field else None

    regions = []
    for r in audit.get("regions", []):
        regions.append(Region(
            name=r["name"],
            rom_start=_hex(r["rom_start"], "rom_start"),
            rom_end=_hex(r["rom_end"], "rom_end"),
            vaddr_base=_hex(r["vaddr_base"], "vaddr_base"),
        ))
    if not regions:
        raise ValueError(f"{config_path}: [audit] must declare at least one region")

    norm = audit.get("normalize", {})
    kseg_mask = _hex(norm.get("kseg_mask", "0xFFFFFFFF"), "kseg_mask")

    remaps = []
    for rm in norm.get("remap", []):
        remaps.append(Remap(
            description=rm.get("description", ""),
            from_lo=_hex(rm["from_lo"], "from_lo"),
            from_hi=_hex(rm["from_hi"], "from_hi"),
            to_lo=_hex(rm["to_lo"], "to_lo"),
        ))

    return AuditConfig(
        config_path=config_path,
        project_root=root,
        name=name,
        rom=rom,
        load_address=load_address,
        text_size=text_size,
        out_dir=out_dir,
        full_c=full_c,
        dispatch_c=dispatch_c,
        function_starts=function_starts,
        regions=regions,
        kseg_mask=kseg_mask,
        remaps=remaps,
    )


def from_argv(argv, default_config: Optional[str] = None) -> AuditConfig:
    """CLI helper: parse `--config PATH` from argv and load.

    If `--config` is absent and `default_config` is provided, use that.
    Falls back to looking for `audit.toml` or `game.toml` in CWD.
    """
    config_path: Optional[str] = None
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--config" and i + 1 < len(argv):
            config_path = argv[i + 1]
            i += 2
        elif a.startswith("--config="):
            config_path = a.split("=", 1)[1]
            i += 1
        else:
            i += 1

    if config_path is None:
        config_path = default_config

    if config_path is None:
        for candidate in ("audit.toml", "game.toml"):
            p = Path.cwd() / candidate
            if p.exists():
                config_path = str(p)
                break

    if config_path is None:
        raise SystemExit(
            "usage: ... --config PATH (or place audit.toml/game.toml in CWD)"
        )

    return load(config_path)


if __name__ == "__main__":
    import sys
    cfg = from_argv(sys.argv)
    print(f"loaded {cfg.config_path}")
    print(f"  project_root  = {cfg.project_root}")
    print(f"  name          = {cfg.name}")
    print(f"  rom           = {cfg.rom}")
    print(f"  full_c        = {cfg.full_c}")
    print(f"  dispatch_c    = {cfg.dispatch_c}")
    print(f"  load_address  = 0x{cfg.load_address:08X}")
    print(f"  text_size     = 0x{cfg.text_size:08X}")
    print(f"  regions       = {len(cfg.regions)}")
    for r in cfg.regions:
        print(f"    - {r.name:8s}  rom 0x{r.rom_start:05X}..0x{r.rom_end:05X}  vaddr 0x{r.vaddr_base:08X}")
    print(f"  kseg_mask     = 0x{cfg.kseg_mask:08X}")
    print(f"  remaps        = {len(cfg.remaps)}")
    for rm in cfg.remaps:
        print(f"    - 0x{rm.from_lo:08X}..0x{rm.from_hi:08X} -> +0x{rm.to_lo:X}  ({rm.description})")
