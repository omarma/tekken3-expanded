"""Static guards for Tekken 3's built-in true-widescreen package."""

from pathlib import Path
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]


class WidescreenModTests(unittest.TestCase):
    def test_game_policy_is_native_wide_with_exact_fallback(self) -> None:
        with (ROOT / "game.toml").open("rb") as source:
            config = tomllib.load(source)
        self.assertEqual(config["video"]["aspect_ratio"], "16:9")
        self.assertEqual(config["video"]["supersampling"], 3)
        self.assertTrue(config["video"]["antialiasing"])
        self.assertEqual(config["video"]["texture_filtering"], "nearest")
        self.assertTrue(config["video"]["perspective_texturing"])
        self.assertFalse(config["video"]["geometry_correction"])
        widescreen = config["widescreen"]
        self.assertTrue(widescreen["native_wide"])
        self.assertFalse(widescreen["full_2d"])
        self.assertFalse(widescreen["nw_2d_edge_fill"])
        self.assertFalse(widescreen["nw_backdrop"])
        self.assertFalse(widescreen["nw_flat_backdrop"])
        self.assertTrue(widescreen["nw_full_mirror"])
        self.assertFalse(widescreen["nw_hud_corners"])
        self.assertNotIn("auto_ui_squash", widescreen)
        self.assertNotIn("nw_left_hud_packet_lo", widescreen)
        self.assertNotIn("nw_left_hud_packet_hi", widescreen)
        self.assertNotIn("nw_hud_packet2_lo", widescreen)
        self.assertNotIn("nw_hud_packet2_hi", widescreen)
        cull = widescreen["cull"]
        self.assertFalse(cull["auto_screen_x"])
        self.assertEqual(cull["screen_w_imms"], ["0x170"])
        self.assertEqual(cull["screen_h_imms"], ["0x1E0"])
        self.assertEqual(cull["screen_x_expected"], 0x2C420170)
        self.assertEqual(
            cull["screen_x_sites"],
            [
                "0x80049438", "0x80049454", "0x80049470", "0x8004948C",
                "0x80049D84", "0x80049DA0", "0x80049DBC", "0x80049DD4",
            ],
        )
        self.assertNotIn("dome", widescreen)
        self.assertNotIn("shell", widescreen)
        self.assertNotIn("native_patch", widescreen)
        self.assertEqual(widescreen["nw_ui_stretch_min_ot"], 0)
        self.assertEqual(widescreen["camera_zoom_num"], 1)
        self.assertEqual(widescreen["camera_zoom_den"], 1)
        self.assertEqual(cull["background_guard_pixels"], 0)
        self.assertEqual(cull["angle"], [
            {"address": "0x8006D1C4", "expected": "0x24040258", "full_angle": True},
            {"address": "0x8006D24C", "expected": "0x2404030C", "full_angle": True},
        ])
        # These branch operands contain packed-vertex Y, not screen X.
        for y_site in ("0x8006CCE4", "0x8006CCEC", "0x8006CCF4", "0x8006CCFC",
                       "0x8006CF24", "0x8006CF2C", "0x8006CF34", "0x8006CF3C"):
            self.assertNotIn(y_site, cull["bltz_sites"])
        self.assertFalse(widescreen["offer"])
        self.assertFalse(widescreen["offer_ultrawide"])

    def test_package_selects_native_visibility_and_defaults_on(self) -> None:
        package = (
            ROOT
            / "mods/preloaded/packages/tekken3.enhancement.true-widescreen/1.0.0"
        )
        with (package / "manifest.toml").open("rb") as source:
            manifest = tomllib.load(source)
        self.assertEqual(manifest["format_version"], 5)
        self.assertEqual(manifest["target"][0]["game_id"], "SLUS-00402")
        self.assertTrue(manifest["feature"][0]["default_enabled"])
        self.assertEqual(
            manifest["plugin"][0]["id"], "tekken3.true-widescreen"
        )
        self.assertNotIn("patch", manifest)
        self.assertEqual(
            sorted(path.name for path in package.iterdir()),
            ["README.md", "manifest.toml"],
        )

    def test_visibility_path_cannot_dirty_the_generator_code_page(self) -> None:
        package = ROOT / (
            "mods/preloaded/packages/"
            "tekken3.enhancement.true-widescreen/1.0.0/manifest.toml"
        )
        with package.open("rb") as source:
            manifest = tomllib.load(source)
        self.assertNotIn("patch", manifest)
        emitter = (ROOT / "psxrecomp/recompiler/src/code_generator.cpp").read_text(
            encoding="utf-8"
        )
        self.assertIn("psx_ws_full_angle_widen", emitter)

    def test_static_plugin_selects_only_fixed_16_by_9(self) -> None:
        source = (ROOT / "src/tekken3_widescreen_mod.c").read_text(
            encoding="utf-8"
        )
        self.assertIn("psx_mod_set_fixed_display_aspect(16u, 9u)", source)
        self.assertIn('"tekken3.true-widescreen"', source)
        self.assertNotIn("psx_mod_write_", source)


if __name__ == "__main__":
    unittest.main()
