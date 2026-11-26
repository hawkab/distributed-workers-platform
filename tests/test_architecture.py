import importlib.util
import hashlib
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("architecture", ROOT / "tools/render-architecture.py")
architecture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(architecture)


class ArchitectureTests(unittest.TestCase):
    def test_ownership_changes_without_changing_system_topology(self):
        reference = None
        for name in architecture.COMPONENTS:
            text = architecture.model(name)
            self.assertEqual(text.count("THIS REPOSITORY"), 2)  # component + legend
            edges = [line for line in text.splitlines() if " -> " in line]
            if reference is None:
                reference = edges
            self.assertEqual(edges, reference)
            for component in architecture.COMPONENTS:
                self.assertIn('"' + component + '" [', text)

    def test_svg_is_self_contained_accessible_and_has_one_owned_component(self):
        namespace = {"s": "http://www.w3.org/2000/svg"}
        with tempfile.TemporaryDirectory() as temp:
            for name in architecture.COMPONENTS:
                directory = Path(temp) / name
                architecture.render(name, directory)
                document = ET.fromstring((directory / "architecture.svg").read_bytes())
                self.assertEqual(document.attrib["role"], "img")
                self.assertIn(name, document.find("s:title", namespace).text)
                self.assertTrue(document.find("s:desc", namespace).text)
                self.assertFalse(document.findall(".//s:script", namespace))
                self.assertFalse(document.findall(".//s:image", namespace))
                self.assertFalse(document.findall(".//s:foreignObject", namespace))
                owned = [x for x in document.findall("s:rect", namespace) if x.get("stroke-width") == "2.5"]
                self.assertEqual(len(owned), 1)
                paths = document.findall("s:path", namespace)
                self.assertEqual(len(paths), 13)

    def test_checked_in_png_preview_matches_the_editable_svg(self):
        raw = (ROOT / "docs/architecture.png").read_bytes()
        self.assertEqual(raw[:8], b"\x89PNG\r\n\x1a\n")
        expected = b"fleet-svg-sha256\x00" + hashlib.sha256((ROOT / "docs/architecture.svg").read_bytes()).hexdigest().encode()
        self.assertIn(expected, raw)


if __name__ == "__main__":
    unittest.main()
