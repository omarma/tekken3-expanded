from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import catalog_assets


FORBIDDEN_LITERAL_SAMPLE_KEYS = {
    "bytes",
    "content",
    "content_hex",
    "contents",
    "data",
    "entropy_blocks",
    "offset_references",
    "payload",
    "payload_bytes",
    "payload_data",
    "payload_hex",
    "prefix_hex",
    "raw_bytes",
    "raw_data",
    "rows",
    "words_hex",
    "words_u32",
}
FORBIDDEN_HOST_PATH_KEYS = {
    "executable_path",
    "input_path",
    "output_path",
    "path",
    "source_path",
    "track_path",
}


def assert_payload_free(test: unittest.TestCase, value: object, location: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold()
            test.assertNotIn(
                normalized,
                FORBIDDEN_LITERAL_SAMPLE_KEYS,
                f"literal retail sample field at {location}.{key}",
            )
            test.assertNotIn(
                normalized,
                FORBIDDEN_HOST_PATH_KEYS,
                f"host path field at {location}.{key}",
            )
            assert_payload_free(test, child, f"{location}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            assert_payload_free(test, child, f"{location}[{index}]")
    else:
        test.assertNotIsInstance(
            value,
            (bytes, bytearray, memoryview),
            f"literal binary value at {location}",
        )


class OutputTests(unittest.TestCase):
    def test_output_is_preserved_without_force_and_inputs_are_protected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "catalog.json"
            output.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(catalog_assets.CatalogAssetsError, "overwrite"):
                catalog_assets._preflight_output(output, force=False)
            catalog_assets._preflight_output(output, force=True)
            with self.assertRaisesRegex(catalog_assets.CatalogAssetsError, "protected"):
                catalog_assets._preflight_output(output, force=True, protected_paths=[output])

    def test_atomic_json_is_deterministic(self) -> None:
        value = {"schema_version": 1, "rows": [{"id": 2}, {"id": 4}]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, second = root / "a.json", root / "b.json"
            catalog_assets._atomic_write_json(first, value)
            catalog_assets._atomic_write_json(second, value)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(json.loads(first.read_text(encoding="utf-8")), value)


class CatalogTests(unittest.TestCase):
    def test_payload_free_catalog_shape_and_hash(self) -> None:
        source = mock.Mock()
        source.__enter__ = mock.Mock(return_value=source)
        source.__exit__ = mock.Mock(return_value=None)
        source.kind = "raw_track_2352_mode2"
        source.extent_sector = 250156
        source.logical_size = 38_150_144
        source.path = Path("Track 1.bin")
        source.path_stat = mock.Mock()

        entries = [mock.Mock(id=index) for index in range(303)]
        descriptors = [mock.Mock(id=index) for index in range(50)]
        bns_catalog = {"record_count": 303, "records": []}
        vab_catalog = {"pair_count": 48, "pairs": []}
        xas_catalog = {"xa_stream_count": 50, "movie_region_count": 22}
        fake_stat = mock.Mock(st_size=632_532_768)

        with (
            mock.patch.object(
                catalog_assets,
                "_load_executable_once",
                return_value=(entries, descriptors, "exe", "bns-table", "xas-table"),
            ),
            mock.patch.object(catalog_assets.bns_tool, "open_bns_source", return_value=source),
            mock.patch.object(catalog_assets, "_require_track_source"),
            mock.patch.object(catalog_assets.xas_tool, "_hash_file", return_value=catalog_assets.xas_tool.TRACK_SHA256),
            mock.patch.object(catalog_assets.bns_tool, "validate_source_capacity"),
            mock.patch.object(catalog_assets, "_build_bns_catalog", return_value=bns_catalog),
            mock.patch.object(catalog_assets, "_build_vab_catalog", return_value=vab_catalog),
            mock.patch.object(catalog_assets, "_build_xas_catalog", return_value=xas_catalog),
            mock.patch.object(catalog_assets, "_optional_model_catalog", return_value=(None, "not installed")),
            mock.patch.object(Path, "stat", return_value=fake_stat),
        ):
            catalog = catalog_assets.build_catalog(
                Path("disc/SLUS_004.02"), Path("disc/Track 1.bin")
            )
            moved_catalog = catalog_assets.build_catalog(
                Path("Z:/another-library/SLUS_004.02"),
                Path("Z:/another-library/Track 1.bin"),
            )

        self.assertEqual(catalog, moved_catalog)
        self.assertEqual(catalog["catalog_sha256"], moved_catalog["catalog_sha256"])
        self.assertNotIn("executable_path", catalog["source_identity"])
        self.assertNotIn("track_path", catalog["source_identity"])
        self.assertTrue(catalog["payload_policy"]["metadata_only"])
        self.assertFalse(catalog["payload_policy"]["retail_payloads_extracted"])
        self.assertEqual(set(catalog["analyzers"]), {"bns", "vab", "xas"})
        self.assertEqual(catalog["optional_analyzers"]["models"]["reason"], "not installed")
        digest_input = dict(catalog)
        digest = digest_input.pop("catalog_sha256")
        self.assertEqual(digest, catalog_assets._sha256_json(digest_input))
        assert_payload_free(self, catalog)

    def test_optional_model_api_is_used_or_cleanly_reported(self) -> None:
        with mock.patch.object(
            catalog_assets.importlib,
            "import_module",
            side_effect=ModuleNotFoundError("missing", name=catalog_assets.MODEL_MODULE_NAME),
        ):
            inventory, note = catalog_assets._optional_model_catalog(
                mock.Mock(), [], exe_path=Path("exe"), exe_sha256="x", table_sha256="t"
            )
        self.assertIsNone(inventory)
        self.assertIn("not installed", note)

        module = mock.Mock()
        module.scan_models.return_value = ["record"]
        module.build_inventory.return_value = {
            "schema_version": 1,
            "scan": {"model_records_found": 1},
            "records": [
                {
                    "id": 1,
                    "profile": "synthetic",
                    "header": {"words_u32": [0x11223344]},
                    "rows": [{"words_hex": ["0x11223344"]}],
                    "entropy_blocks": [{"prefix_hex": "11223344"}],
                    "offset_references": [{"actual_offset": 12}],
                    "sections": [
                        {
                            "id": 0,
                            "name": "header",
                            "offset": 0,
                            "end_offset": 4,
                            "size": 4,
                            "sha256": "a" * 64,
                            "prefix_hex": "11223344",
                            "payload_hex": "11223344",
                        }
                    ],
                }
            ],
        }
        with mock.patch.object(catalog_assets.importlib, "import_module", return_value=module):
            inventory, note = catalog_assets._optional_model_catalog(
                mock.Mock(), [], exe_path=Path("exe"), exe_sha256="x", table_sha256="t"
            )
        self.assertEqual(
            inventory["records"],
            [
                {
                    "id": 1,
                    "profile": "synthetic",
                    "sections": [
                        {
                            "id": 0,
                            "name": "header",
                            "offset": 0,
                            "end_offset": 4,
                            "size": 4,
                            "sha256": "a" * 64,
                        }
                    ],
                }
            ],
        )
        self.assertIn("dedicated model_map.py", inventory["detail_note"])
        assert_payload_free(self, inventory)
        self.assertIsNone(note)
        module.scan_models.assert_called_once()
        module.build_inventory.assert_called_once()


if __name__ == "__main__":
    unittest.main()
