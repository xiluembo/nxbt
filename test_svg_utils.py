import unittest

from nxbt.qt.svg_utils import recolor_pro_controller_svg


class SvgUtilsTests(unittest.TestCase):
    def test_recolor_pro_controller_svg_rewrites_body_and_button_fills(self):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg">'
            "<defs><style>.cls-1{fill:#dadada;}.cls-2{fill:#191f28;}</style></defs>"
            '<path class="cls-1" d="M0 0"/>'
            '<circle class="cls-2" cx="5" cy="5" r="2"/>'
            "</svg>"
        )

        recolored = recolor_pro_controller_svg(
            svg,
            body_color=(1, 2, 3),
            button_color=(10, 20, 30),
        )

        self.assertIn('fill="#010203"', recolored)
        self.assertIn('fill="#0a141e"', recolored)
        self.assertNotIn("cls-1", recolored)
        self.assertNotIn("cls-2", recolored)
        self.assertNotIn("<style>", recolored)


if __name__ == "__main__":
    unittest.main()
