from __future__ import annotations

import xml.etree.ElementTree as ET


SVG_NAMESPACE = "http://www.w3.org/2000/svg"


def recolor_pro_controller_svg(
    svg_text: str,
    *,
    body_color: tuple[int, int, int],
    button_color: tuple[int, int, int],
) -> str:
    root = ET.fromstring(svg_text)
    body_hex = _rgb_to_hex(body_color)
    button_hex = _rgb_to_hex(button_color)

    for style in root.findall(f".//{{{SVG_NAMESPACE}}}style"):
        parent = _find_parent(root, style)
        if parent is not None:
            parent.remove(style)

    for element in root.iter():
        css_class = element.attrib.get("class")
        if css_class == "cls-1":
            element.set("fill", body_hex)
            del element.attrib["class"]
        elif css_class == "cls-2":
            element.set("fill", button_hex)
            del element.attrib["class"]

    return ET.tostring(root, encoding="unicode")


def _find_parent(root, child):
    for parent in root.iter():
        for candidate in list(parent):
            if candidate is child:
                return parent
    return None


def _rgb_to_hex(color: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color)
