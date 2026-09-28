#!/usr/bin/env python3
"""Build a deterministic, payload-free asset catalog for Tekken 3 USA.

This one-command orchestrator reuses the strict BNS, VAB and XAS analyzers.
It reads the exact retail source but writes metadata only: no extracted model,
texture, sound, XA or STR payload is copied into the output catalog.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Sequence, TextIO

try:
    from tools import bns_tool, vab_tool, xas_tool
except ModuleNotFoundError:  # Direct execution: python tools/catalog_assets.py.
    import bns_tool  # type: ignore[no-redef]
    import vab_tool  # type: ignore[no-redef]
    import xas_tool  # type: ignore[no-redef]


SCHEMA_VERSION = 1
TOOL_VERSION = 1
MODEL_MODULE_NAME = "tools.model_map"
MODEL_DIRECT_MODULE_NAME = "model_map"


class CatalogAssetsError(RuntimeError):
    """A user-facing verification, analyzer, or output error."""


def _path_key(path: Path) -> str:
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        resolved = path.absolute()
    return os.path.normcase(str(resolved))


def _preflight_output(
    output: Path, *, force: bool, protected_paths: Sequence[Path] = ()
) -> None:
    output_key = _path_key(output)
    if output_key in {_path_key(path) for path in protected_paths}:
        raise CatalogAssetsError(f"output would overwrite a protected input: {output}")
    if output.exists() and not force:
        raise CatalogAssetsError(
            f"refusing to overwrite existing output: {output}; use --force"
        )


def _atomic_write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, indent=2, sort_keys=False)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _sha256_json(value: object) -> str:
    canonical = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _require_track_source(source: bns_tool.BnsSource) -> None:
    if source.kind != "raw_track_2352_mode2":
        raise CatalogAssetsError(
            "the complete catalog requires the exact raw 2352-byte Track 1; "
            "a standalone BNS or cooked ISO cannot prove XAS raw sectors"
        )
    if source.path.stat().st_size != xas_tool.TRACK_SIZE:
        raise CatalogAssetsError(
            f"Track 1 size must be {xas_tool.TRACK_SIZE} bytes, "
            f"got {source.path.stat().st_size}"
        )
    if (source.extent_sector, source.logical_size) != (250156, 38_150_144):
        raise CatalogAssetsError(
            "TEKKEN3.BNS ISO extent does not match the supported US revision"
        )


def _load_executable_once(
    exe_path: Path,
) -> tuple[
    list[bns_tool.TableEntry],
    list[xas_tool.XaDescriptor],
    str,
    str,
    str,
]:
    try:
        data = exe_path.read_bytes()
    except OSError as exc:
        raise CatalogAssetsError(f"cannot read executable {exe_path}: {exc}") from exc
    exe_sha256 = hashlib.sha256(data).hexdigest()
    if exe_sha256 != bns_tool.US_EXE_SHA256 or exe_sha256 != xas_tool.US_EXE_SHA256:
        raise CatalogAssetsError(
            "executable SHA-256 does not match Tekken 3 USA SLUS-00402 "
            f"(expected {bns_tool.US_EXE_SHA256}, got {exe_sha256})"
        )
    entries = bns_tool.parse_table_bytes(data)
    descriptors = xas_tool.parse_descriptor_table_bytes(data)
    bns_table = data[
        bns_tool.TABLE_FILE_OFFSET : bns_tool.TABLE_FILE_OFFSET
        + bns_tool.TABLE_ENTRY_COUNT * bns_tool.TABLE_ENTRY_SIZE
    ]
    xas_table = data[
        xas_tool.XAS_TABLE_FILE_OFFSET : xas_tool.XAS_TABLE_FILE_OFFSET
        + xas_tool.XAS_TABLE_ENTRY_COUNT * xas_tool.XAS_TABLE_ENTRY_SIZE
    ]
    bns_table_sha256 = hashlib.sha256(bns_table).hexdigest()
    xas_table_sha256 = hashlib.sha256(xas_table).hexdigest()
    if xas_table_sha256 != xas_tool.XAS_TABLE_SHA256:
        raise CatalogAssetsError("XAS descriptor table hash does not match the supported revision")
    return entries, descriptors, exe_sha256, bns_table_sha256, xas_table_sha256


def _build_bns_catalog(
    source: bns_tool.BnsSource,
    entries: Sequence[bns_tool.TableEntry],
    *,
    exe_path: Path,
    exe_sha256: str,
    table_sha256: str,
) -> dict[str, object]:
    inventory = bns_tool.build_inventory(
        source,
        entries,
        exe_path=exe_path,
        exe_sha256=exe_sha256,
        table_sha256=table_sha256,
    )
    records = inventory["entries"]
    counts = Counter(item["kind"] for item in records)  # type: ignore[index]
    return {
        "schema_version": bns_tool.SCHEMA_VERSION,
        "table": inventory["table"],
        "record_count": len(records),  # type: ignore[arg-type]
        "kind_counts": dict(sorted(counts.items())),
        "records": records,
    }


def _build_vab_catalog(
    source: bns_tool.BnsSource,
    entries: Sequence[bns_tool.TableEntry],
    *,
    exe_path: Path,
    exe_sha256: str,
    table_sha256: str,
) -> dict[str, object]:
    audit = vab_tool.build_audit_manifest(
        source,
        entries,
        exe_path=exe_path,
        exe_sha256=exe_sha256,
        table_sha256=table_sha256,
    )
    pairs = audit["pairs"]
    compact_pairs: list[dict[str, object]] = []
    total_samples = 0
    for pair in pairs:  # type: ignore[assignment]
        header = pair["vab_header"]
        total_samples += header["vag_count"]
        compact_pairs.append(
            {
                "vh_id": pair["vh_id"],
                "arc_id": pair["arc_id"],
                "vb_member_index": pair["vb_member_index"],
                "proof": pair["proof"],
                "vh": pair["vh"],
                "arc": pair["arc"],
                "vb": pair["vb"],
                "vab_header": {
                    key: header[key]
                    for key in (
                        "version",
                        "bank_id",
                        "header_size",
                        "declared_total_size",
                        "program_count",
                        "tone_count",
                        "vag_count",
                        "master_volume",
                        "master_pan",
                    )
                },
                "reconstructed_vab": pair["reconstructed_vab"],
            }
        )
    return {
        "schema_version": vab_tool.SCHEMA_VERSION,
        "pair_count": len(compact_pairs),
        "total_vag_samples": total_samples,
        "pairs": compact_pairs,
    }


def _build_xas_catalog(
    source_path: Path,
    descriptors: Sequence[xas_tool.XaDescriptor],
    *,
    exe_path: Path,
    exe_sha256: str,
    table_sha256: str,
    track_sha256: str,
) -> dict[str, object]:
    source = xas_tool.XasSource(
        source_path, xas_tool.XAS_EXTENT_LBA, xas_tool.XAS_SECTOR_COUNT
    )
    with source:
        scan = xas_tool.scan_xas(
            source,
            descriptors,
            expected_submode_counts=xas_tool.EXPECTED_SUBMODE_COUNTS,
        )
        movies = xas_tool.discover_movie_regions(
            scan.str_sectors, expected_count=xas_tool.EXPECTED_MOVIE_COUNT
        )
        inventory = xas_tool.build_inventory(
            source,
            descriptors,
            scan,
            movies,
            exe_path=exe_path,
            exe_sha256=exe_sha256,
            table_sha256=table_sha256,
            track_sha256=track_sha256,
        )
    return {
        "schema_version": xas_tool.SCHEMA_VERSION,
        "descriptor_table": inventory["descriptor_table"],
        "source": {
            key: inventory["source"][key]  # type: ignore[index]
            for key in (
                "iso_path",
                "iso_extent_lba",
                "iso_logical_size",
                "raw_sector_count",
                "raw_sector_span_sha256",
                "submode_counts",
            )
        },
        "xa_stream_count": len(inventory["xa_streams"]),  # type: ignore[arg-type]
        "movie_region_count": len(inventory["movie_regions"]),  # type: ignore[arg-type]
        "xa_streams": inventory["xa_streams"],
        "movie_regions": inventory["movie_regions"],
    }


def _optional_model_catalog(
    source: bns_tool.BnsSource,
    entries: Sequence[bns_tool.TableEntry],
    *,
    exe_path: Path,
    exe_sha256: str,
    table_sha256: str,
) -> tuple[dict[str, object] | None, str | None]:
    """Use model_map's documented public functions when that module is present."""

    module_name = MODEL_MODULE_NAME if __package__ else MODEL_DIRECT_MODULE_NAME
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            return None, "optional tools/model_map.py is not installed"
        raise
    scan_models = getattr(module, "scan_models", None)
    build_inventory = getattr(module, "build_inventory", None)
    if not callable(scan_models) or not callable(build_inventory):
        return None, "tools/model_map.py has no stable scan_models/build_inventory API"
    records = scan_models(source, entries)
    inventory = build_inventory(
        records,
        source=source,
        exe_path=exe_path,
        exe_sha256=exe_sha256,
        table_sha256=table_sha256,
    )
    if not isinstance(inventory, dict) or "records" not in inventory:
        raise CatalogAssetsError("model_map returned an invalid inventory document")
    # model_map's full research document intentionally contains large decoded
    # row/entropy structures. The all-assets catalog keeps its stable record
    # identity and section map, while the dedicated model inventory remains the
    # detailed drill-down artifact.
    compact_records: list[dict[str, object]] = []
    for record in inventory["records"]:  # type: ignore[assignment]
        compact_sections = [
            {
                key: section[key]
                for key in (
                    "id",
                    "name",
                    "offset",
                    "end_offset",
                    "size",
                    "basis",
                    "sha256",
                    "entropy",
                    "zero_fraction",
                    "printable_ascii_fraction",
                )
                if key in section
            }
            for section in record.get("sections", [])
        ]
        compact_records.append(
            {
                **{
                    key: record[key]
                    for key in (
                        "id",
                        "profile",
                        "profile_confidence",
                        "sector",
                        "bns_offset",
                        "bns_end_offset",
                        "size",
                        "sha256",
                        "semantic_name",
                    )
                    if key in record
                },
                "sections": compact_sections,
            }
        )
    compact = {
        "schema_version": inventory.get("schema_version", 1),
        "tool_boundary": inventory.get("tool_boundary"),
        "scan": inventory.get("scan"),
        "records": compact_records,
        "detail_note": (
            "row tables, offset references and entropy blocks are available from "
            "the dedicated model_map.py inventory"
        ),
    }
    return compact, None


def build_catalog(
    exe_path: Path,
    source_path: Path,
    *,
    include_models: bool = True,
) -> dict[str, object]:
    """Verify once, run read-only analyzers, and return one metadata catalog."""

    (
        entries,
        descriptors,
        exe_sha256,
        bns_table_sha256,
        xas_table_sha256,
    ) = _load_executable_once(exe_path)

    bns_source = bns_tool.open_bns_source(source_path, "track")
    _require_track_source(bns_source)
    # Hash the exact raw Track 1 once. XAS sector parsing independently proves
    # the raw XAS span; it does not need to hash the whole container again.
    track_sha256 = xas_tool._hash_file(source_path)
    if track_sha256 != xas_tool.TRACK_SHA256:
        raise CatalogAssetsError(
            "Track 1 SHA-256 does not match the supported Tekken 3 USA image "
            f"(expected {xas_tool.TRACK_SHA256}, got {track_sha256})"
        )

    with bns_source:
        bns_tool.validate_source_capacity(bns_source, entries)
        bns_catalog = _build_bns_catalog(
            bns_source,
            entries,
            exe_path=exe_path,
            exe_sha256=exe_sha256,
            table_sha256=bns_table_sha256,
        )
        vab_catalog = _build_vab_catalog(
            bns_source,
            entries,
            exe_path=exe_path,
            exe_sha256=exe_sha256,
            table_sha256=bns_table_sha256,
        )
        models: dict[str, object] | None = None
        model_note: str | None = None
        if include_models:
            models, model_note = _optional_model_catalog(
                bns_source,
                entries,
                exe_path=exe_path,
                exe_sha256=exe_sha256,
                table_sha256=bns_table_sha256,
            )
        else:
            model_note = "model scan disabled by --no-models"

    xas_catalog = _build_xas_catalog(
        source_path,
        descriptors,
        exe_path=exe_path,
        exe_sha256=exe_sha256,
        table_sha256=xas_table_sha256,
        track_sha256=track_sha256,
    )
    analyzers: dict[str, object] = {
        "bns": bns_catalog,
        "vab": vab_catalog,
        "xas": xas_catalog,
    }
    if models is not None:
        analyzers["models"] = models

    result: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "game_id": bns_tool.GAME_ID,
        "source_identity": {
            "executable_role": "SLUS-00402 PS-X EXE",
            "executable_sha256": exe_sha256,
            "track_role": "raw Mode 2 data Track 1",
            "track_size": source_path.stat().st_size,
            "track_sha256": track_sha256,
        },
        "payload_policy": {
            "metadata_only": True,
            "retail_payloads_extracted": False,
        },
        "analyzers": analyzers,
    }
    if model_note is not None:
        result["optional_analyzers"] = {"models": {"included": False, "reason": model_note}}
    result["catalog_sha256"] = _sha256_json(result)
    return result


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build one payload-free Tekken 3 USA asset metadata catalog"
    )
    parser.add_argument("--version", action="version", version=f"catalog_assets {TOOL_VERSION}")
    parser.add_argument(
        "--exe",
        type=Path,
        default=Path("disc/SLUS_004.02"),
        help="verified Tekken 3 USA executable (default: disc/SLUS_004.02)",
    )
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="exact raw 2352-byte Mode 2 Track 1 image",
    )
    parser.add_argument("--output", type=Path, required=True, help="metadata JSON output path")
    parser.add_argument(
        "--no-models",
        action="store_true",
        help="skip optional tools/model_map.py integration",
    )
    parser.add_argument("--force", action="store_true", help="replace an existing output")
    return parser


def run(args: argparse.Namespace) -> int:
    _preflight_output(
        args.output, force=args.force, protected_paths=(args.exe, args.source)
    )
    catalog = build_catalog(args.exe, args.source, include_models=not args.no_models)
    _atomic_write_json(args.output, catalog)
    analyzers = catalog["analyzers"]
    model_text = ""
    if "models" in analyzers:  # type: ignore[operator]
        model_text = ", model scan included"
    elif "optional_analyzers" in catalog:
        reason = catalog["optional_analyzers"]["models"]["reason"]  # type: ignore[index]
        model_text = f", models omitted ({reason})"
    print(
        "Cataloged 303 BNS records, 48 VAB pairs, 50 XA streams and "
        f"22 STR movie regions{model_text}: {args.output}"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    try:
        return run(args)
    except (
        CatalogAssetsError,
        bns_tool.BnsToolError,
        vab_tool.VabToolError,
        xas_tool.XasToolError,
        OSError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
