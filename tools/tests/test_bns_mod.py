from __future__ import annotations

import hashlib
import struct
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tools import bns_mod, bns_tool


def make_iso_record(name: bytes, extent: int, size: int, *, directory: bool) -> bytes:
    length = 33 + len(name)
    if length % 2:
        length += 1
    record = bytearray(length)
    record[0] = length
    struct.pack_into("<I", record, 2, extent)
    struct.pack_into(">I", record, 6, extent)
    struct.pack_into("<I", record, 10, size)
    struct.pack_into(">I", record, 14, size)
    record[25] = 0x02 if directory else 0x00
    struct.pack_into("<H", record, 28, 1)
    struct.pack_into(">H", record, 30, 1)
    record[32] = len(name)
    record[33 : 33 + len(name)] = name
    return bytes(record)


def make_raw_track(path: Path, payload: bytes) -> None:
    sector_size = 2352
    user_offset = 24
    payload_sectors = (len(payload) + 2047) // 2048
    image = bytearray(max(32, 30 + payload_sectors) * sector_size)

    def put_user_sector(sector: int, data: bytes) -> None:
        physical = sector * sector_size
        image[physical : physical + 12] = b"\x00" + b"\xFF" * 10 + b"\x00"
        image[physical + 15] = 2
        start = physical + user_offset
        image[start : start + len(data)] = data

    root_record = make_iso_record(b"\x00", 20, 2048, directory=True)
    pvd = bytearray(2048)
    pvd[:7] = b"\x01CD001\x01"
    pvd[156 : 156 + len(root_record)] = root_record
    put_user_sector(16, pvd)

    root = bytearray(2048)
    records = (
        make_iso_record(b"\x00", 20, 2048, directory=True),
        make_iso_record(b"\x01", 20, 2048, directory=True),
        make_iso_record(b"TEKKEN3", 21, 2048, directory=True),
    )
    position = 0
    for record in records:
        root[position : position + len(record)] = record
        position += len(record)
    put_user_sector(20, root)

    subdirectory = bytearray(2048)
    records = (
        make_iso_record(b"\x00", 21, 2048, directory=True),
        make_iso_record(b"\x01", 20, 2048, directory=True),
        make_iso_record(b"TEKKEN3.BNS;1", 30, len(payload), directory=False),
    )
    position = 0
    for record in records:
        subdirectory[position : position + len(record)] = record
        position += len(record)
    put_user_sector(21, subdirectory)
    for index in range(payload_sectors):
        put_user_sector(30 + index, payload[index * 2048 : (index + 1) * 2048])
    path.write_bytes(image)


def make_executable(path: Path, record_size: int) -> str:
    data = bytearray(
        bns_tool.TABLE_FILE_OFFSET
        + bns_tool.TABLE_ENTRY_COUNT * bns_tool.TABLE_ENTRY_SIZE
    )
    data[:8] = b"PS-X EXE"
    struct.pack_into("<I", data, 0x10, 0x80079C70)
    struct.pack_into("<II", data, 0x18, 0x80010000, 0x00121000)
    struct.pack_into("<II", data, bns_tool.TABLE_FILE_OFFSET, 0, record_size)
    for entry_id in range(1, bns_tool.TABLE_ENTRY_COUNT):
        struct.pack_into(
            "<II",
            data,
            bns_tool.TABLE_FILE_OFFSET + entry_id * bns_tool.TABLE_ENTRY_SIZE,
            1,
            0,
        )
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def make_arc(payloads: list[bytes]) -> bytes:
    directory_size = 4 + len(payloads) * 8
    # The small verified ARC records use four bytes of 0xFF directory padding.
    data_offset = directory_size + 4
    directory = bytearray(struct.pack("<I", len(payloads)))
    offset = data_offset
    for payload in payloads:
        if len(payload) % 4:
            raise ValueError("synthetic ARC members must be four-byte aligned")
        directory.extend(struct.pack("<II", offset, len(payload)))
        offset += len(payload)
    directory.extend(b"\xFF" * 4)
    return bytes(directory) + b"".join(payloads)


class PackageFixture:
    def __init__(self, root: Path, stock_record: bytes = b"stock-BNS-record") -> None:
        self.root = root
        self.stock_record = stock_record
        archive = bytearray(2048)
        archive[: len(stock_record)] = stock_record
        self.track = root / "Track 1.bin"
        make_raw_track(self.track, bytes(archive))
        self.track_sha256 = hashlib.sha256(self.track.read_bytes()).hexdigest()
        self.exe = root / "SLUS_004.02"
        self.exe_sha256 = make_executable(self.exe, len(stock_record))

    def supported_revision(self):
        return mock.patch.multiple(
            bns_mod,
            SUPPORTED_TRACK1_SIZE=self.track.stat().st_size,
            SUPPORTED_TRACK1_SHA256=self.track_sha256,
        )

    def supported_executable(self):
        return mock.patch.object(bns_tool, "US_EXE_SHA256", self.exe_sha256)

    def build(
        self,
        replacement: Path,
        output: Path,
        archive: Path | None = None,
        record_id: int = 0,
    ) -> bns_mod.BuildResult:
        with self.supported_revision(), self.supported_executable():
            return bns_mod.build_package(
                exe_path=self.exe,
                track_path=self.track,
                replacement_specs=[bns_mod.ReplacementSpec(record_id, replacement)],
                package_id="example.bns-pack",
                version="1.2.3",
                name="Example BNS Pack",
                author="Test Author",
                license_name="CC0-1.0",
                description=None,
                output_directory=output,
                archive=archive,
            )


class ReplacementParsingTests(unittest.TestCase):
    def test_repeated_id_file_syntax_is_sorted(self) -> None:
        parsed = bns_mod.parse_replacements(["71=second.bin", "3=first.bin"])
        self.assertEqual([item.id for item in parsed], [3, 71])
        self.assertEqual(parsed[0].path, Path("first.bin"))

    def test_duplicate_and_unsafe_ids_are_rejected(self) -> None:
        with self.assertRaisesRegex(bns_mod.BnsModError, "more than once"):
            bns_mod.parse_replacements(["7=a.bin", "007=b.bin"])
        with self.assertRaisesRegex(bns_mod.BnsModError, "outside"):
            bns_mod.parse_replacements(["303=a.bin"])
        with self.assertRaisesRegex(bns_mod.BnsModError, "ID=FILE"):
            bns_mod.parse_replacements(["7:a.bin"])

    def test_arc_selector_is_sorted_and_rejects_duplicates(self) -> None:
        parsed = bns_mod.parse_arc_replacements(
            ["73:4=last.bin", "73:1=first.bin"]
        )
        self.assertEqual([(item.id, item.member_id) for item in parsed], [(73, 1), (73, 4)])
        with self.assertRaisesRegex(bns_mod.BnsModError, "more than once"):
            bns_mod.parse_arc_replacements(["73:1=a.bin", "073:01=b.bin"])
        with self.assertRaisesRegex(bns_mod.BnsModError, "BNS_ID:MEMBER"):
            bns_mod.parse_arc_replacements(["73/1=a.bin"])


class PackageBuildTests(unittest.TestCase):
    def test_builds_guarded_source_and_deterministic_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture = PackageFixture(root)
            replacement = root / "replacement.bin"
            replacement.write_bytes(fixture.stock_record)
            output = root / "package-source"
            archive = root / "example.psxmod"

            result = fixture.build(replacement, output, archive)

            self.assertEqual(result.track_sha256, fixture.track_sha256)
            with (output / "manifest.toml").open("rb") as handle:
                manifest = tomllib.load(handle)
            self.assertEqual(manifest["target"][0]["game_id"], "SLUS-00402")
            self.assertEqual(manifest["target"][0]["disc_sha256"], fixture.track_sha256)
            self.assertEqual(manifest["target"][0]["exe_sha256"], fixture.exe_sha256)
            self.assertEqual(manifest["feature"][0]["id"], "bns-000")
            self.assertFalse(manifest["feature"][0]["default_enabled"])
            overlay = manifest["overlay"][0]
            self.assertEqual(overlay["feature"], "bns-000")
            self.assertEqual(overlay["target"], "disc_user")
            self.assertEqual(overlay["offset"], 30 * 2048)
            self.assertEqual(overlay["file"], "assets/bns/000.bin")
            self.assertEqual(
                overlay["sha256"], hashlib.sha256(fixture.stock_record).hexdigest()
            )
            self.assertEqual(
                overlay["expected_sha256"],
                hashlib.sha256(fixture.stock_record).hexdigest(),
            )
            self.assertEqual(
                (output / "assets" / "bns" / "000.bin").read_bytes(),
                fixture.stock_record,
            )
            with zipfile.ZipFile(archive) as package:
                self.assertEqual(
                    package.namelist(), ["assets/bns/000.bin", "manifest.toml"]
                )
                self.assertTrue(
                    all(
                        not name.startswith("/") and ".." not in Path(name).parts
                        for name in package.namelist()
                    )
                )

            second_output = root / "second-source"
            second_archive = root / "second.psxmod"
            fixture.build(replacement, second_output, second_archive)
            self.assertEqual(archive.read_bytes(), second_archive.read_bytes())

    def test_exact_size_nonempty_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture = PackageFixture(root)
            wrong = root / "wrong.bin"
            wrong.write_bytes(b"short")
            with self.assertRaisesRegex(bns_mod.BnsModError, "exact stock size"):
                fixture.build(wrong, root / "wrong-output")

            empty = root / "empty.bin"
            empty.write_bytes(b"")
            with self.assertRaisesRegex(bns_mod.BnsModError, "is empty"):
                fixture.build(empty, root / "empty-output")

            nonempty = root / "nonempty.bin"
            nonempty.write_bytes(b"x")
            with self.assertRaisesRegex(bns_mod.BnsModError, "record 001 is empty"):
                fixture.build(nonempty, root / "zero-record-output", record_id=1)

    def test_arc_member_package_contains_only_authored_member_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            stock_arc = make_arc([b"AAAA", b"STOCK123"])
            fixture = PackageFixture(root, stock_record=stock_arc)
            replacement = root / "authored-member.bin"
            replacement.write_bytes(b"NEWW")
            output = root / "arc-package-source"
            package_path = root / "arc-member.psxmod"

            with fixture.supported_revision(), fixture.supported_executable():
                result = bns_mod.build_package(
                    exe_path=fixture.exe,
                    track_path=fixture.track,
                    replacement_specs=[],
                    arc_replacement_specs=[
                        bns_mod.ArcReplacementSpec(0, 0, replacement)
                    ],
                    package_id="example.arc-member",
                    version="1.0.0",
                    name="Example ARC Member",
                    author="Test Author",
                    license_name="CC0-1.0",
                    description=None,
                    output_directory=output,
                    archive=package_path,
                )

            self.assertEqual(len(result.replacements), 1)
            prepared = result.replacements[0]
            self.assertEqual(prepared.feature_id, "bns-000-arc-000")
            self.assertEqual(prepared.relative_asset_path, "assets/bns/000/arc/000.bin")
            with (output / "manifest.toml").open("rb") as handle:
                manifest = tomllib.load(handle)
            overlay = manifest["overlay"][0]
            self.assertEqual(overlay["offset"], 30 * 2048 + 24)
            self.assertEqual(overlay["sha256"], hashlib.sha256(b"NEWW").hexdigest())
            self.assertEqual(
                overlay["expected_sha256"], hashlib.sha256(b"AAAA").hexdigest()
            )
            with zipfile.ZipFile(package_path) as package:
                self.assertEqual(
                    package.namelist(),
                    ["assets/bns/000/arc/000.bin", "manifest.toml"],
                )
                self.assertEqual(
                    package.read("assets/bns/000/arc/000.bin"), b"NEWW"
                )
                self.assertNotIn("STOCK123", package.read("manifest.toml").decode("utf-8"))

    def test_arc_member_requires_strict_arc_and_exact_member_size(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture = PackageFixture(root, stock_record=make_arc([b"AAAA"]))
            wrong = root / "wrong.bin"
            wrong.write_bytes(b"TOO-LONG")
            with fixture.supported_revision(), fixture.supported_executable():
                with self.assertRaisesRegex(bns_mod.BnsModError, "exact stock size"):
                    bns_mod.build_package(
                        exe_path=fixture.exe,
                        track_path=fixture.track,
                        replacement_specs=[],
                        arc_replacement_specs=[
                            bns_mod.ArcReplacementSpec(0, 0, wrong)
                        ],
                        package_id="example.arc-member",
                        version="1.0.0",
                        name="Example",
                        author="Author",
                        license_name="CC0-1.0",
                        description=None,
                        output_directory=root / "wrong-output",
                    )

    def test_wrong_track_hash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture = PackageFixture(root)
            replacement = root / "replacement.bin"
            replacement.write_bytes(fixture.stock_record)
            with mock.patch.object(
                bns_mod, "SUPPORTED_TRACK1_SIZE", fixture.track.stat().st_size
            ):
                with self.assertRaisesRegex(bns_mod.BnsModError, "SHA-256 does not match"):
                    bns_mod.build_package(
                        exe_path=fixture.exe,
                        track_path=fixture.track,
                        replacement_specs=[bns_mod.ReplacementSpec(0, replacement)],
                        package_id="example.bns-pack",
                        version="1.0.0",
                        name="Example",
                        author="Author",
                        license_name="CC0-1.0",
                        description=None,
                        output_directory=root / "output",
                    )

    def test_existing_outputs_and_invalid_metadata_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture = PackageFixture(root)
            replacement = root / "replacement.bin"
            replacement.write_bytes(fixture.stock_record)
            existing = root / "existing"
            existing.mkdir()
            with self.assertRaisesRegex(bns_mod.BnsModError, "overwrite"):
                fixture.build(replacement, existing)

            with self.assertRaisesRegex(bns_mod.BnsModError, "package ID"):
                with fixture.supported_revision(), fixture.supported_executable():
                    bns_mod.build_package(
                        exe_path=fixture.exe,
                        track_path=fixture.track,
                        replacement_specs=[bns_mod.ReplacementSpec(0, replacement)],
                        package_id="Unsafe Package ID",
                        version="1.0.0",
                        name="Example",
                        author="Author",
                        license_name="CC0-1.0",
                        description=None,
                        output_directory=root / "invalid-output",
                    )


if __name__ == "__main__":
    unittest.main()
