#!/usr/bin/env python3
"""Reconstruct verified System 12 ROM regions and probe model-format overlap.

This is an offline research tool, not a fighter importer. Region offsets are
not CPU addresses; signature hits do not establish character identity or EOF.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zipfile
import zlib
from pathlib import Path

try:
    from . import arc_tool, bns_tool, model_map
except ImportError:
    import bns_tool
    import arc_tool
    import model_map


MANIFEST = Path(__file__).with_name("data") / "namcos12_model_sources.json"
LAYOUTS = {"ROM_LOAD": (1, 1), "ROM_LOAD16_BYTE": (1, 2),
           "ROM_LOAD32_BYTE": (1, 4), "ROM_LOAD32_WORD": (2, 4),
           "ROM_LOAD16_WORD_SWAP": (2, 2)}


class ProbeError(ValueError):
    pass


def digest(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def place_rom(target: bytearray, occupied: bytearray, data: bytes, spec: dict) -> None:
    """Apply MAME's group/skip layout; reject overlapping or out-of-range loads."""
    operation = spec["operation"]
    if operation not in LAYOUTS:
        raise ProbeError(f"unsupported ROM operation: {operation}")
    group, stride = LAYOUTS[operation]
    offset = spec["offset"]
    if not data or len(data) % group or offset < 0:
        raise ProbeError("empty, unaligned, or negative ROM load")
    count = len(data) // group
    end = offset + (count - 1) * stride + group
    if end > len(target) or len(occupied) != len(target):
        raise ProbeError("ROM load exceeds region bounds")
    for lane in range(group):
        if any(occupied[offset + lane:end:stride]):
            raise ProbeError("overlapping ROM loads")
    for lane in range(group):
        source_lane = 1 - lane if operation == "ROM_LOAD16_WORD_SWAP" else lane
        target[offset + lane:end:stride] = data[source_lane::group]
        occupied[offset + lane:end:stride] = b"\1" * count


def reconstruct(archive: Path, definition: dict) -> tuple[dict[str, bytes], list[dict]]:
    regions: dict[str, bytes] = {}
    files = []
    with zipfile.ZipFile(archive) as source:
        members = source.infolist()
        for region in definition["regions"]:
            size = region["size"]
            if not 0 < size <= 128 * 1024 * 1024:
                raise ProbeError("invalid ROM region size")
            target, occupied = bytearray(size), bytearray(size)
            for spec in region["loads"]:
                matches = [info for info in members
                           if not info.is_dir()
                           and Path(info.filename).name.casefold() == spec["name"].casefold()]
                # MAME sometimes corrects chip labels without changing their data.
                # A unique size+CRC match is still checked against the SHA-1 below.
                if not matches:
                    matches = [info for info in members if not info.is_dir()
                               and info.file_size == spec['size']
                               and f'{info.CRC:08x}' == spec['crc32']]
                if len(matches) != 1:
                    raise ProbeError(f"expected one {spec['name']}, found {len(matches)}")
                info = matches[0]
                if info.file_size != spec["size"]:
                    raise ProbeError(f"wrong size for {spec['name']}")
                data = source.read(info)
                crc = f"{zlib.crc32(data) & 0xffffffff:08x}"
                sha1 = hashlib.sha1(data).hexdigest()
                if crc != spec["crc32"] or sha1 != spec["sha1"]:
                    raise ProbeError(f"checksum mismatch for {spec['name']}")
                place_rom(target, occupied, data, spec)
                files.append({"name": spec["name"], "zip_member": info.filename,
                              "region": region["name"], "size": len(data),
                              "sha1": sha1, "sha256": digest(data), "crc32": crc})
            # Unpopulated ROM space is explicitly zero-filled, never treated as an asset.
            regions[region["name"]] = bytes(target)
    return regions, files


def occurrences(data: bytes, needle: bytes):
    offset = data.find(needle)
    while offset >= 0:
        yield offset
        offset = data.find(needle, offset + 1)


def scan_3dmk(data: bytes) -> dict:
    """Check the PS1-observed envelope using only the containing region as a bound."""
    candidates, rejected = [], []
    for magic_offset in occurrences(data, b"3DMK"):
        start = magic_offset - 8
        try:
            if start < 0 or start % 4 or start + 24 > len(data):
                raise ProbeError("unaligned or truncated header")
            count, opaque, _, reserved, payload_rel, reserved2 = struct.unpack_from("<6I", data, start)
            table_end = 24 + count * 56
            if not 1 <= count <= 512 or reserved or reserved2:
                raise ProbeError("header differs from PS1-observed profile")
            if payload_rel + 8 != table_end or start + table_end > len(data):
                raise ProbeError("row table does not match PS1-observed profile")
            references = []
            for row in range(count):
                words = struct.unpack_from("<14I", data, start + 24 + row * 56)
                if words[10] not in (0, 1) or words[11]:
                    raise ProbeError("row flags differ from PS1-observed profile")
                for column in (0, 1, 2, 12, 13):
                    value = words[column]
                    if value == 0 or (column == 12 and value == 2):
                        continue
                    relative = value + 8
                    if value % 4 or relative < table_end or start + relative > len(data):
                        raise ProbeError("observed offset column outside containing region")
                    references.append(relative)
            candidates.append({
                "region_offset": start, "magic_offset": magic_offset,
                "row_count": count, "unknown_u32_at_0x04": opaque,
                "row_table_end_relative": table_end,
                "row_table_sha256": digest(data[start + 24:start + table_end]),
                "largest_referenced_relative_offset": max(references, default=table_end),
                "semantic_name": None, "record_size": None,
                "status": "PS1-observed envelope matches; record boundary and semantics unproved",
            })
        except ProbeError as exc:
            rejected.append({"magic_offset": magic_offset, "reason": str(exc)})
    return {"magic_hits": len(candidates) + len(rejected),
            "candidates": candidates, "rejected": rejected}


def reference_comparison(data: bytes, records: list[model_map.ModelRecord]) -> dict:
    matches = []
    for record in records:
        if record.parsed.profile != model_map.PROFILE_3DMK:
            continue
        payload = record.parsed.data
        hits = list(occurrences(data, payload))
        if hits:
            matches.append({"ps1_bns_id": record.entry.id, "size": len(payload),
                            "sha256": digest(payload), "region_offsets": hits,
                            "semantic_name": None})
    return {"kind": "exact entire PS1 BNS record bytes",
            "matches": matches,
            "note": "Absence of an exact match does not disprove format compatibility."}


def find_model_archives(data: bytes) -> list[tuple[int, arc_tool.ArcArchive]]:
    """Locate canonical ARC directories whose first member is a model candidate.

    Unlike signature slicing, the directory proves every member's exact span.
    """
    found = {}
    for candidate in scan_3dmk(data)["candidates"]:
        first = candidate["region_offset"]
        for start in range(max(0, first - 4 - 255 * 8 - 15) & ~3, first, 4):
            if start + 12 > len(data):
                continue
            count, first_rel = struct.unpack_from("<II", data, start)
            if not 1 <= count <= 255 or first_rel + start != first:
                continue
            directory_end = start + 4 + count * 8
            if directory_end > first:
                continue
            last, size = struct.unpack_from("<II", data, directory_end - 8)
            end = start + last + size
            if not first < end <= len(data):
                continue
            try:
                archive = arc_tool.parse_archive(data[start:end])
            except arc_tool.ArcToolError:
                continue
            found[start] = archive
    return sorted(found.items())


def extract_models(args: argparse.Namespace) -> int:
    if args.output.exists():
        raise ProbeError("output directory already exists; choose a fresh output path")
    data = args.region.read_bytes()
    archives = find_model_archives(data)
    if not archives:
        raise ProbeError("no canonical model ARC directories found")
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, "region_sha256": digest(data), "archives": [],
              "boundary": "Exact directory-bounded raw models; semantic names remain unassigned."}
    model_count = 0
    for start, archive in archives:
        group = {"region_offset": start, "size": len(archive.data),
                 "sha256": archive.sha256, "member_count": len(archive.members), "models": []}
        directory = args.output / f"arc_{start:08x}"
        directory.mkdir()
        for member in archive.members:
            payload = archive.data[member.offset:member.end_offset]
            if payload[8:12] != b"3DMK":
                continue
            parsed = model_map.parse_3dmk(payload)
            filename = f"{member.id:03d}.3dm"
            with (directory / filename).open("xb") as handle:
                handle.write(payload)
            group["models"].append({"member_id": member.id, "file": filename,
                "region_offset": start + member.offset, "size": member.size,
                "sha256": digest(payload), "row_count": parsed.header["row_count"],
                "unknown_u32_at_0x04": parsed.header["unknown_u32_at_0x04"],
                "semantic_name": None})
            model_count += 1
        report["archives"].append(group)
    write_json(args.output / "models.json", report)
    print(f"Extracted {model_count} bounded raw models from {len(archives)} ARC directories")
    return 0


def identify_live_model(raw: bytes, ram: bytes, model_offset: int) -> list[int] | None:
    """Match every byte, allowing only the additive relocation observed in TTT1.

    This identifies a record, not a character name. A simultaneous game capture
    supplies that name. The relocation positions are evidence, not a general
    specification of all possible model fixups.
    """
    if model_offset < 0 or model_offset + len(raw) > len(ram) or len(raw) % 4:
        return None
    relocated_base = model_offset | 0x80000000
    relocations = []
    for offset in range(0, len(raw), 4):
        original = struct.unpack_from("<I", raw, offset)[0]
        current = struct.unpack_from("<I", ram, model_offset + offset)[0]
        if original == current:
            continue
        if (current - original) & 0xffffffff != relocated_base:
            return None
        relocations.append(offset)
    return relocations


def identify(args: argparse.Namespace) -> int:
    if args.output.exists():
        raise ProbeError("output already exists; choose a fresh output path")
    ram = args.ram.read_bytes()
    if len(ram) != 0x400000:
        raise ProbeError("expected a 4 MiB System 12 RAM dump starting at physical address zero")
    positions = [offset - 8 for offset in occurrences(ram, b"3DMK") if offset >= 8]
    matches = []
    for path in sorted(args.models.glob("arc_*/*.3dm")):
        raw = path.read_bytes()
        model_map.parse_3dmk(raw)
        for position in positions:
            relocations = identify_live_model(raw, ram, position)
            if relocations is None:
                continue
            matches.append({"model_file": str(path.relative_to(args.models)),
                "size": len(raw), "sha256": digest(raw), "ram_model_offset": position,
                "observed_relocation_base": position | 0x80000000,
                "relocation_word_offsets": relocations,
                "semantic_name": None,
                "match": "all bytes match after reversing the listed additive relocations"})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, {"schema_version": 1, "ram_sha256": digest(ram),
        "matches": matches, "boundary": "Use the simultaneous game screen to establish character identity."})
    print(f"Found {len(matches)} complete model matches in live RAM")
    return 0


def write_json(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2)
        handle.write("\n")


def prepare(args: argparse.Namespace) -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if args.set not in manifest["sets"]:
        raise ProbeError("unsupported set: " + args.set)
    if args.output.exists():
        raise ProbeError("output directory already exists; choose a fresh output path")
    definition = manifest["sets"][args.set]
    if args.regions:
        wanted = set(args.regions.split(","))
        selected = [r for r in definition["regions"] if r["name"] in wanted]
        if {r["name"] for r in selected} != wanted:
            raise ProbeError("unknown region requested")
        definition = {"regions": selected}
    regions, files = reconstruct(args.romset, definition)
    report = {"schema_version": 1, "set": args.set,
              "archive_sha256": digest(args.romset.read_bytes()),
              "mame_reference": manifest["source"], "verified_files": files,
              "boundary": "ROM reconstruction and structural candidates only; no fighter identified",
              "regions": []}
    args.output.mkdir(parents=True, exist_ok=False)
    for name, data in regions.items():
        filename = name.replace(":", "_") + ".bin"
        with (args.output / filename).open("xb") as handle:
            handle.write(data)
        result = {"name": name, "file": filename, "size": len(data), "sha256": digest(data)}
        if name in ("maincpu:rom", "bankedroms"):
            result["model_probe"] = scan_3dmk(data)
        report["regions"].append(result)
    write_json(args.output / "rom-report.json", report)
    print(f"Verified {len(files)} ROM chips; reconstructed {len(regions)} regions in {args.output}")
    for region in report["regions"]:
        if "model_probe" in region:
            probe = region["model_probe"]
            print(f"{region['name']}: {probe['magic_hits']} 3DMK hits; {len(probe['candidates'])} envelope candidates")
    return 0


def compare(args: argparse.Namespace) -> int:
    if args.output.exists():
        raise ProbeError("output already exists; choose a fresh output path")
    entries, exe_sha256, table_sha256 = bns_tool.load_us_table(args.ps1_exe)
    with bns_tool.open_bns_source(args.ps1_source) as source:
        records = model_map.scan_models(source, entries)
    data = args.region.read_bytes()
    result = {"schema_version": 1, "region_sha256": digest(data),
              "ps1_exe_sha256": exe_sha256, "ps1_table_sha256": table_sha256,
              "ps1_source": str(args.ps1_source), "ps1_models_scanned": len(records),
              "model_probe": scan_3dmk(data), "exact_comparison": reference_comparison(data, records)}
    result["ps1_reference_models"] = [
        {"bns_id": r.entry.id, "size": r.entry.size, "sha256": digest(r.parsed.data),
         "row_count": r.parsed.header["row_count"],
         "unknown_u32_at_0x04": r.parsed.header["unknown_u32_at_0x04"],
         "semantic_name": None}
        for r in records if r.parsed.profile == model_map.PROFILE_3DMK]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, result)
    print(f"Compared {len(result['ps1_reference_models'])} PS1 model records; "
          f"{len(result['exact_comparison']['matches'])} exact records matched")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    first = commands.add_parser("prepare", help="verify local ZIP and reconstruct System 12 regions")
    first.add_argument("--romset", type=Path, required=True)
    first.add_argument("--set", required=True)
    first.add_argument("--regions", help="comma-separated subset (default: all regions)")
    first.add_argument("--output", type=Path, required=True)
    second = commands.add_parser("compare", help="probe a region against actual PS1 model records")
    second.add_argument("--region", type=Path, required=True)
    second.add_argument("--ps1-exe", type=Path, required=True)
    second.add_argument("--ps1-source", type=Path, required=True)
    second.add_argument("--output", type=Path, required=True)
    third = commands.add_parser("extract-models", help="extract exact models from validated ARC directories")
    third.add_argument("--region", type=Path, required=True)
    third.add_argument("--output", type=Path, required=True)
    fourth = commands.add_parser("identify-live", help="match extracted models to a System 12 RAM capture")
    fourth.add_argument("--ram", type=Path, required=True)
    fourth.add_argument("--models", type=Path, required=True)
    fourth.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        return {"prepare": prepare, "compare": compare, "extract-models": extract_models,
                "identify-live": identify}[args.command](args)
    except (OSError, ValueError, zipfile.BadZipFile, bns_tool.BnsToolError, model_map.ModelMapError, arc_tool.ArcToolError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
