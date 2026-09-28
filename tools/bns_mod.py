#!/usr/bin/env python3
"""Build guarded PSXRecomp packages from exact-size BNS overlays.

The stock BIN/CUE is never modified.  A package contains only the replacement
files supplied by the mod author plus a declarative manifest guarded by hashes
from the verified Tekken 3 (USA) data track.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

try:
    from tools import arc_tool, bns_tool
except ModuleNotFoundError:  # Direct execution: ``python tools/bns_mod.py``.
    import arc_tool  # type: ignore[no-redef]
    import bns_tool  # type: ignore[no-redef]


SUPPORTED_TRACK1_SIZE = 632_532_768
SUPPORTED_TRACK1_SHA256 = (
    "6b660e62748d02779e9e08362a5ed202540af7fad134de2ec0a2184ad78bb496"
)
CHUNK_SIZE = 1024 * 1024
PACKAGE_FORMAT_VERSION = 1
ID_PATTERN = re.compile(r"^[a-z0-9._-]{1,96}$")
VERSION_PATTERN = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?$"
)


class BnsModError(RuntimeError):
    """A validation or package-build error safe to show to the author."""


@dataclass(frozen=True)
class ReplacementSpec:
    """One requested numeric BNS record and its author-owned payload."""

    id: int
    path: Path


@dataclass(frozen=True)
class ArcReplacementSpec:
    """One exact-size member inside a strict top-level BNS ARC record."""

    id: int
    member_id: int
    path: Path


@dataclass(frozen=True)
class PreparedReplacement:
    """One fully validated overlay ready for manifest generation."""

    id: int
    path: Path
    size: int
    payload_sha256: str
    expected_sha256: str
    disc_user_offset: int
    member_id: int | None = None

    @property
    def feature_id(self) -> str:
        if self.member_id is None:
            return f"bns-{self.id:03d}"
        return f"bns-{self.id:03d}-arc-{self.member_id:03d}"

    @property
    def feature_name(self) -> str:
        if self.member_id is None:
            return f"BNS record {self.id:03d}"
        return f"BNS record {self.id:03d} ARC member {self.member_id:03d}"

    @property
    def feature_description(self) -> str:
        if self.member_id is None:
            subject = f"BNS record {self.id:03d}"
        else:
            subject = f"BNS record {self.id:03d} ARC member {self.member_id:03d}"
        return f"Exact-size replacement for verified {subject} ({self.size} bytes)."

    @property
    def relative_asset_path(self) -> str:
        # This is constructed rather than derived from an input filename, so a
        # replacement can never introduce an absolute or parent-relative path.
        if self.member_id is None:
            return f"assets/bns/{self.id:03d}.bin"
        return f"assets/bns/{self.id:03d}/arc/{self.member_id:03d}.bin"


@dataclass(frozen=True)
class BuildResult:
    output_directory: Path
    archive: Path | None
    replacements: tuple[PreparedReplacement, ...]
    track_sha256: str


def sha256_file(path: Path) -> str:
    """Hash a regular file without loading it into memory."""

    if not path.is_file():
        raise BnsModError(f"file does not exist or is not a regular file: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(CHUNK_SIZE):
                digest.update(chunk)
    except OSError as exc:
        raise BnsModError(f"cannot read {path}: {exc}") from exc
    return digest.hexdigest()


def parse_replacements(
    values: Iterable[str], *, required: bool = True
) -> list[ReplacementSpec]:
    """Parse repeated ``ID=FILE`` arguments, rejecting ambiguity."""

    replacements: list[ReplacementSpec] = []
    seen_ids: set[int] = set()
    for value in values:
        if "=" not in value:
            raise BnsModError(
                f"replacement must use ID=FILE syntax, got {value!r}"
            )
        raw_id, raw_path = value.split("=", 1)
        raw_id = raw_id.strip()
        raw_path = raw_path.strip()
        if not raw_id.isascii() or not raw_id.isdecimal():
            raise BnsModError(f"replacement ID is not a decimal integer: {raw_id!r}")
        entry_id = int(raw_id, 10)
        if not 0 <= entry_id < bns_tool.TABLE_ENTRY_COUNT:
            raise BnsModError(
                f"replacement ID {entry_id} is outside 0-{bns_tool.TABLE_ENTRY_COUNT - 1}"
            )
        if entry_id in seen_ids:
            raise BnsModError(f"replacement ID {entry_id} was supplied more than once")
        if not raw_path:
            raise BnsModError(f"replacement ID {entry_id} has an empty file path")
        seen_ids.add(entry_id)
        replacements.append(ReplacementSpec(entry_id, Path(raw_path)))

    if required and not replacements:
        raise BnsModError("at least one --replacement ID=FILE is required")
    return sorted(replacements, key=lambda item: item.id)


def parse_arc_replacements(
    values: Iterable[str], *, required: bool = True
) -> list[ArcReplacementSpec]:
    """Parse repeated ``BNS_ID:MEMBER=FILE`` arguments safely."""

    replacements: list[ArcReplacementSpec] = []
    seen_ids: set[tuple[int, int]] = set()
    for value in values:
        if "=" not in value:
            raise BnsModError(
                f"ARC replacement must use BNS_ID:MEMBER=FILE syntax, got {value!r}"
            )
        raw_selector, raw_path = value.split("=", 1)
        selector_parts = raw_selector.strip().split(":")
        if (
            len(selector_parts) != 2
            or not all(part.isascii() and part.isdecimal() for part in selector_parts)
        ):
            raise BnsModError(
                f"ARC replacement selector must be decimal BNS_ID:MEMBER, got "
                f"{raw_selector!r}"
            )
        entry_id, member_id = (int(part, 10) for part in selector_parts)
        if not 0 <= entry_id < bns_tool.TABLE_ENTRY_COUNT:
            raise BnsModError(
                f"ARC replacement BNS ID {entry_id} is outside "
                f"0-{bns_tool.TABLE_ENTRY_COUNT - 1}"
            )
        key = (entry_id, member_id)
        if key in seen_ids:
            raise BnsModError(
                f"ARC replacement {entry_id:03d}:{member_id:03d} was supplied more than once"
            )
        raw_path = raw_path.strip()
        if not raw_path:
            raise BnsModError(
                f"ARC replacement {entry_id:03d}:{member_id:03d} has an empty file path"
            )
        seen_ids.add(key)
        replacements.append(ArcReplacementSpec(entry_id, member_id, Path(raw_path)))

    if required and not replacements:
        raise BnsModError(
            "at least one --arc-replacement BNS_ID:MEMBER=FILE is required"
        )
    return sorted(replacements, key=lambda item: (item.id, item.member_id))


def _validate_metadata(
    package_id: str,
    version: str,
    name: str,
    author: str,
    license_name: str,
) -> None:
    if not ID_PATTERN.fullmatch(package_id) or package_id.endswith("."):
        raise BnsModError(
            "package ID must be 1-96 lowercase letters, digits, dots, dashes, "
            "or underscores, and may not start or end with a dot"
        )
    if not VERSION_PATTERN.fullmatch(version):
        raise BnsModError(
            "version must be three numeric components with an optional safe "
            "prerelease suffix (for example 1.0.0 or 1.0.0-beta.1)"
        )
    for label, value in (
        ("package name", name),
        ("author", author),
        ("license", license_name),
    ):
        if not value.strip():
            raise BnsModError(f"{label} must not be empty")
        if "\x00" in value:
            raise BnsModError(f"{label} must not contain a NUL character")


def _toml_string(value: str) -> str:
    """Return a TOML basic string using the compatible JSON escape subset."""

    return json.dumps(value, ensure_ascii=False)


def _render_manifest(
    *,
    package_id: str,
    version: str,
    name: str,
    author: str,
    license_name: str,
    description: str,
    replacements: Sequence[PreparedReplacement],
) -> str:
    lines = [
        f"format_version = {PACKAGE_FORMAT_VERSION}",
        f"id = {_toml_string(package_id)}",
        f"version = {_toml_string(version)}",
        f"name = {_toml_string(name)}",
        f"author = {_toml_string(author)}",
        f"description = {_toml_string(description)}",
        f"license = {_toml_string(license_name)}",
        'resolver = "declarative"',
        'save_compatibility = "shared"',
        "",
        "[[target]]",
        f"game_id = {_toml_string(bns_tool.GAME_ID)}",
        f"exe_sha256 = {_toml_string(bns_tool.US_EXE_SHA256)}",
        f"disc_sha256 = {_toml_string(SUPPORTED_TRACK1_SHA256)}",
    ]

    for replacement in replacements:
        lines.extend(
            [
                "",
                "[[feature]]",
                f"id = {_toml_string(replacement.feature_id)}",
                f"name = {_toml_string(replacement.feature_name)}",
                f"description = {_toml_string(replacement.feature_description)}",
                'group = "BNS replacements"',
                "default_enabled = false",
                "",
                "[[overlay]]",
                f"feature = {_toml_string(replacement.feature_id)}",
                'target = "disc_user"',
                f"offset = {replacement.disc_user_offset}",
                f"file = {_toml_string(replacement.relative_asset_path)}",
                f"sha256 = {_toml_string(replacement.payload_sha256)}",
                f"expected_sha256 = {_toml_string(replacement.expected_sha256)}",
            ]
        )
    return "\n".join(lines) + "\n"


def _validate_output_targets(output_directory: Path, archive: Path | None) -> None:
    if output_directory.exists():
        raise BnsModError(
            f"refusing to overwrite existing package source: {output_directory}"
        )
    if archive is not None and archive.exists():
        raise BnsModError(f"refusing to overwrite existing archive: {archive}")
    if archive is not None and archive.suffix.casefold() != ".psxmod":
        raise BnsModError("archive output must use the .psxmod extension")
    if archive is not None:
        output_resolved = output_directory.resolve(strict=False)
        archive_resolved = archive.resolve(strict=False)
        if archive_resolved.is_relative_to(output_resolved):
            raise BnsModError(
                "archive output must not be inside the package source directory"
            )


def _prepare_replacements(
    *,
    exe_path: Path,
    track_path: Path,
    specifications: Sequence[ReplacementSpec],
    arc_specifications: Sequence[ArcReplacementSpec],
) -> tuple[list[PreparedReplacement], str]:
    try:
        track_size = track_path.stat().st_size
    except OSError as exc:
        raise BnsModError(f"cannot inspect data Track 1 {track_path}: {exc}") from exc
    if track_size != SUPPORTED_TRACK1_SIZE:
        raise BnsModError(
            "data Track 1 size does not match supported Tekken 3 USA "
            f"SLUS-00402 (expected {SUPPORTED_TRACK1_SIZE}, got {track_size})"
        )

    track_sha256 = sha256_file(track_path)
    if track_sha256 != SUPPORTED_TRACK1_SHA256:
        raise BnsModError(
            "data Track 1 SHA-256 does not match supported Tekken 3 USA "
            f"SLUS-00402 (expected {SUPPORTED_TRACK1_SHA256}, got {track_sha256})"
        )

    entries, exe_sha256, table_sha256 = bns_tool.load_us_table(exe_path)
    source = bns_tool.open_bns_source(track_path, "track")
    with source:
        inventory = bns_tool.build_inventory(
            source,
            entries,
            exe_path=exe_path,
            exe_sha256=exe_sha256,
            table_sha256=table_sha256,
        )

    metadata = inventory.get("source")
    if not isinstance(metadata, dict):
        raise BnsModError("BNS inventory has no source metadata")
    extent_lba = metadata.get("iso_extent_lba")
    if not isinstance(extent_lba, int) or extent_lba < 0:
        raise BnsModError("BNS inventory did not discover a valid ISO extent LBA")
    if metadata.get("physical_sector_size") != 2352:
        raise BnsModError("supported data Track 1 must use raw 2352-byte sectors")

    inventory_entries = inventory.get("entries")
    if not isinstance(inventory_entries, list) or len(inventory_entries) != len(entries):
        raise BnsModError("BNS inventory has an invalid entry list")
    inventory_by_id = {item["id"]: item for item in inventory_entries}

    prepared: list[PreparedReplacement] = []
    for specification in specifications:
        entry = entries[specification.id]
        item = inventory_by_id[specification.id]
        if entry.size == 0:
            raise BnsModError(
                f"BNS record {entry.id:03d} is empty and cannot receive an overlay"
            )
        if not specification.path.is_file():
            raise BnsModError(
                f"replacement for BNS record {entry.id:03d} is not a regular file: "
                f"{specification.path}"
            )
        try:
            replacement_size = specification.path.stat().st_size
        except OSError as exc:
            raise BnsModError(
                f"cannot inspect replacement for BNS record {entry.id:03d}: {exc}"
            ) from exc
        if replacement_size == 0:
            raise BnsModError(
                f"replacement for BNS record {entry.id:03d} is empty"
            )
        if replacement_size != entry.size:
            raise BnsModError(
                f"replacement for BNS record {entry.id:03d} has {replacement_size} "
                f"bytes; exact stock size {entry.size} is required"
            )

        stock_sha256 = item.get("sha256")
        if not isinstance(stock_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", stock_sha256
        ):
            raise BnsModError(
                f"inventory hash for BNS record {entry.id:03d} is invalid"
            )
        disc_user_offset = (extent_lba + entry.sector) * bns_tool.LOGICAL_SECTOR_SIZE
        prepared.append(
            PreparedReplacement(
                id=entry.id,
                path=specification.path,
                size=entry.size,
                payload_sha256=sha256_file(specification.path),
                expected_sha256=stock_sha256,
                disc_user_offset=disc_user_offset,
            )
        )

    arc_cache: dict[int, arc_tool.ArcArchive] = {}
    if arc_specifications:
        with source:
            for specification in arc_specifications:
                entry = entries[specification.id]
                item = inventory_by_id[specification.id]
                if item.get("kind") != "ARC":
                    raise BnsModError(
                        f"BNS record {entry.id:03d} is not a strict ARC container"
                    )
                archive = arc_cache.get(entry.id)
                if archive is None:
                    record_data = source.read_at(entry.offset, entry.size)
                    try:
                        archive = arc_tool.parse_archive(record_data)
                    except arc_tool.ArcToolError as exc:
                        raise BnsModError(
                            f"BNS record {entry.id:03d} failed strict ARC validation: {exc}"
                        ) from exc
                    arc_cache[entry.id] = archive

                if not 0 <= specification.member_id < len(archive.members):
                    raise BnsModError(
                        f"BNS record {entry.id:03d} ARC member {specification.member_id} "
                        f"is outside 0-{len(archive.members) - 1}"
                    )
                member = archive.members[specification.member_id]
                if member.size == 0:
                    raise BnsModError(
                        f"BNS record {entry.id:03d} ARC member "
                        f"{member.id:03d} is empty and cannot receive an overlay"
                    )
                if not specification.path.is_file():
                    raise BnsModError(
                        f"replacement for BNS record {entry.id:03d} ARC member "
                        f"{member.id:03d} is not a regular file: {specification.path}"
                    )
                try:
                    replacement_size = specification.path.stat().st_size
                except OSError as exc:
                    raise BnsModError(
                        f"cannot inspect replacement for BNS record {entry.id:03d} "
                        f"ARC member {member.id:03d}: {exc}"
                    ) from exc
                if replacement_size == 0:
                    raise BnsModError(
                        f"replacement for BNS record {entry.id:03d} ARC member "
                        f"{member.id:03d} is empty"
                    )
                if replacement_size != member.size:
                    raise BnsModError(
                        f"replacement for BNS record {entry.id:03d} ARC member "
                        f"{member.id:03d} has {replacement_size} bytes; exact stock "
                        f"size {member.size} is required"
                    )

                stock_payload = archive.data[member.offset : member.end_offset]
                disc_user_offset = (
                    (extent_lba + entry.sector) * bns_tool.LOGICAL_SECTOR_SIZE
                    + member.offset
                )
                prepared.append(
                    PreparedReplacement(
                        id=entry.id,
                        member_id=member.id,
                        path=specification.path,
                        size=member.size,
                        payload_sha256=sha256_file(specification.path),
                        expected_sha256=hashlib.sha256(stock_payload).hexdigest(),
                        disc_user_offset=disc_user_offset,
                    )
                )

    return sorted(
        prepared,
        key=lambda item: (
            item.id,
            item.member_id is not None,
            -1 if item.member_id is None else item.member_id,
        ),
    ), track_sha256


def _write_deterministic_archive(source: Path, output: Path) -> None:
    files = sorted(path for path in source.rglob("*") if path.is_file())
    with zipfile.ZipFile(
        output, "w", zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in files:
            relative = path.relative_to(source).as_posix()
            if relative.startswith("/") or ".." in Path(relative).parts:
                raise BnsModError(f"unsafe generated archive path: {relative}")
            info = zipfile.ZipInfo(relative)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)


def build_package(
    *,
    exe_path: Path,
    track_path: Path,
    replacement_specs: Sequence[ReplacementSpec],
    package_id: str,
    version: str,
    name: str,
    author: str,
    license_name: str,
    description: str | None,
    output_directory: Path,
    archive: Path | None = None,
    arc_replacement_specs: Sequence[ArcReplacementSpec] = (),
) -> BuildResult:
    """Validate inputs and atomically publish a package source and archive."""

    _validate_metadata(package_id, version, name, author, license_name)
    if not replacement_specs and not arc_replacement_specs:
        raise BnsModError("at least one replacement is required")
    replacement_ids = [item.id for item in replacement_specs]
    if len(set(replacement_ids)) != len(replacement_ids):
        raise BnsModError("replacement IDs must be unique")
    invalid_ids = sorted(
        item for item in replacement_ids if not 0 <= item < bns_tool.TABLE_ENTRY_COUNT
    )
    if invalid_ids:
        raise BnsModError(
            "replacement ID(s) outside supported range: "
            + ", ".join(str(item) for item in invalid_ids)
        )
    arc_keys = [(item.id, item.member_id) for item in arc_replacement_specs]
    if len(set(arc_keys)) != len(arc_keys):
        raise BnsModError("ARC replacement BNS/member IDs must be unique")
    invalid_arc_ids = sorted(
        item.id
        for item in arc_replacement_specs
        if not 0 <= item.id < bns_tool.TABLE_ENTRY_COUNT
    )
    if invalid_arc_ids:
        raise BnsModError(
            "ARC replacement BNS ID(s) outside supported range: "
            + ", ".join(str(item) for item in invalid_arc_ids)
        )
    overlapping_ids = sorted(set(replacement_ids) & {item.id for item in arc_replacement_specs})
    if overlapping_ids:
        raise BnsModError(
            "a package cannot replace a complete BNS record and members inside "
            "the same record: " + ", ".join(f"{item:03d}" for item in overlapping_ids)
        )
    _validate_output_targets(output_directory, archive)
    prepared, track_sha256 = _prepare_replacements(
        exe_path=exe_path,
        track_path=track_path,
        specifications=sorted(replacement_specs, key=lambda item: item.id),
        arc_specifications=sorted(
            arc_replacement_specs, key=lambda item: (item.id, item.member_id)
        ),
    )

    actual_description = description or (
        f"Exact-size Tekken 3 BNS overlay pack with {len(prepared)} "
        f"independently selectable replacement{'s' if len(prepared) != 1 else ''}."
    )
    if "\x00" in actual_description:
        raise BnsModError("description must not contain a NUL character")
    manifest = _render_manifest(
        package_id=package_id,
        version=version,
        name=name,
        author=author,
        license_name=license_name,
        description=actual_description,
        replacements=prepared,
    )

    output_directory.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output_directory.name}.",
            suffix=".tmp",
            dir=output_directory.parent,
        )
    )
    archive_temporary: Path | None = None
    try:
        (staging / "assets" / "bns").mkdir(parents=True)
        (staging / "manifest.toml").write_text(manifest, encoding="utf-8", newline="\n")
        for replacement in prepared:
            destination = staging / Path(replacement.relative_asset_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(replacement.path, destination)
            # Recheck after copying to catch a replacement modified during the
            # build instead of publishing a manifest/payload mismatch.
            copied_sha256 = sha256_file(destination)
            if copied_sha256 != replacement.payload_sha256:
                raise BnsModError(
                    f"replacement {replacement.feature_name} changed during build"
                )

        if archive is not None:
            archive.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                prefix=f".{archive.name}.",
                suffix=".tmp",
                dir=archive.parent,
                delete=False,
            ) as handle:
                archive_temporary = Path(handle.name)
            _write_deterministic_archive(staging, archive_temporary)

        os.replace(staging, output_directory)
        if archive is not None and archive_temporary is not None:
            os.replace(archive_temporary, archive)
            archive_temporary = None
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        if archive_temporary is not None:
            archive_temporary.unlink(missing_ok=True)
        # Keep a successfully published source directory if the final archive
        # rename alone failed; it is valid and can be packed again.
        raise

    return BuildResult(
        output_directory=output_directory,
        archive=archive,
        replacements=tuple(prepared),
        track_sha256=track_sha256,
    )


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a guarded .psxmod package source from exact-size, author-owned "
            "Tekken 3 USA BNS record or strict ARC-member replacements without "
            "modifying the disc"
        )
    )
    parser.add_argument(
        "--exe",
        type=Path,
        default=Path("disc/SLUS_004.02"),
        help="verified US boot executable (default: disc/SLUS_004.02)",
    )
    parser.add_argument(
        "--track",
        type=Path,
        default=Path("disc/Tekken 3 (USA) (Track 1).bin"),
        help="verified raw US data Track 1",
    )
    parser.add_argument("--package-id", required=True, help="stable lowercase package ID")
    parser.add_argument("--version", required=True, help="semantic version such as 1.0.0")
    parser.add_argument("--name", required=True, help="package display name")
    parser.add_argument("--author", required=True, help="mod author display name")
    parser.add_argument(
        "--license",
        dest="license_name",
        default="LicenseRef-Proprietary",
        help="replacement asset license (default: LicenseRef-Proprietary)",
    )
    parser.add_argument("--description", help="optional package description")
    parser.add_argument(
        "--replacement",
        action="append",
        metavar="ID=FILE",
        help="numeric BNS ID and exact-size author-owned replacement; repeat as needed",
    )
    parser.add_argument(
        "--arc-replacement",
        action="append",
        metavar="BNS_ID:MEMBER=FILE",
        help=(
            "strict ARC member and exact-size author-owned payload; repeat as needed"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="new package source directory",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        help="optional new .psxmod archive",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    replacements = parse_replacements(args.replacement or (), required=False)
    arc_replacements = parse_arc_replacements(
        args.arc_replacement or (), required=False
    )
    result = build_package(
        exe_path=args.exe,
        track_path=args.track,
        replacement_specs=replacements,
        package_id=args.package_id,
        version=args.version,
        name=args.name,
        author=args.author,
        license_name=args.license_name,
        description=args.description,
        output_directory=args.output,
        archive=args.archive,
        arc_replacement_specs=arc_replacements,
    )
    records = ", ".join(item.feature_name for item in result.replacements)
    message = (
        f"Built guarded package source {result.output_directory} for {records}."
    )
    if result.archive is not None:
        message += f" Archive: {result.archive}."
    print(message)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (BnsModError, bns_tool.BnsToolError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
