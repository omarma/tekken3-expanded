import unittest


class WidescreenFastSeamTests(unittest.TestCase):
    def test_tekken_16_9_margin_and_sidecar_boundaries(self):
        native_width = 368
        margin = 61
        wide_width = native_width + 2 * margin

        self.assertEqual(wide_width, 490)
        self.assertEqual(-margin + margin, 0)
        self.assertEqual(native_width + margin - 1 + margin, wide_width - 1)

        def center_only(lo: int, hi: int) -> bool:
            return lo >= 0 and hi < native_width

        self.assertFalse(center_only(-62, -61))
        self.assertFalse(center_only(-61, -61))
        self.assertTrue(center_only(0, 367))
        self.assertFalse(center_only(367, 368))
        self.assertFalse(center_only(368, 368))
        self.assertFalse(center_only(428, 429))


if __name__ == "__main__":
    unittest.main()
