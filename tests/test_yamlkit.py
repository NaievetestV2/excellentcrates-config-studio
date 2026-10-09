import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ecstudio import yamlkit as y

try:
    import yaml as _pyyaml
except ImportError:  # pragma: no cover
    _pyyaml = None


GOLDEN = Path("/tmp/opencode/armor_crate.yml")


class EmitTests(unittest.TestCase):
    def test_scalars_and_types(self):
        tree = y.Mapping(
            [
                ("int", y.Scalar(600)),
                ("float", y.Scalar(22.5)),
                ("bool_t", y.Scalar(True)),
                ("bool_f", y.Scalar(False)),
                ("nothing", y.Scalar(None)),
                ("word", y.Scalar("default")),
                ("looks_bool", y.Scalar("yes")),
                ("looks_int", y.Scalar("123")),
                ("empty", y.Scalar("")),
                ("quote", y.Scalar("it's")),
                ("colon", y.Scalar("minecraft:stone")),
            ]
        )
        text = y.emit(tree)
        back = y.parse(text)
        self.assertTrue(y.values_equal(tree, back), text)
        self.assertEqual(back.get("looks_bool").value, "yes")
        self.assertEqual(back.get("looks_int").value, "123")

    def test_comments_are_written_above_keys(self):
        tree = y.Mapping(
            [
                (
                    "Name",
                    y.Scalar(
                        "&aCrate",
                        comment=["Shown in menus.", "Use '&' codes.", ""],
                    ),
                )
            ]
        )
        text = y.emit(tree)
        self.assertEqual(
            text,
            "# Shown in menus.\n# Use '&' codes.\n#\nName: '&aCrate'\n",
        )
        self.assertTrue(y.values_equal(tree, y.parse(text)))

    def test_bukkit_indentless_sequences(self):
        tree = y.Mapping(
            [
                (
                    "Block",
                    y.Mapping(
                        [
                            ("Positions", y.Sequence([y.Scalar("1,2,3,world")])),
                            ("Pushback", y.Mapping([("Enabled", y.Scalar(True))])),
                        ]
                    ),
                )
            ]
        )
        text = y.emit(tree)
        self.assertIn("  Positions:\n  - '1,2,3,world'\n", text)
        self.assertTrue(y.values_equal(tree, y.parse(text)))

    def test_empty_collections(self):
        tree = y.Mapping(
            [
                ("empty_list", y.Sequence([])),
                ("empty_map", y.Mapping([])),
                ("nested", y.Mapping([("l", y.Sequence([]))])),
            ]
        )
        text = y.emit(tree)
        self.assertIn("empty_list: []", text)
        self.assertIn("empty_map: {}", text)
        self.assertTrue(y.values_equal(tree, y.parse(text)))

    @unittest.skipIf(_pyyaml is None, "pyyaml not installed")
    def test_pyyaml_agrees(self):
        tree = y.Mapping(
            [
                ("_dataver", y.Scalar(600)),
                ("Name", y.Scalar("&aMy Crate", comment=["c"])),
                ("Description", y.Sequence([y.Scalar("a"), y.Scalar("no")])),
                ("Weight", y.Scalar(25.0)),
                ("Flag", y.Scalar(False)),
                ("Nums", y.Scalar("42")),
                ("List", y.Mapping([("0", y.Scalar("zero key"))])),
                ("Nested", y.Mapping([("A", y.Mapping([("b", y.Scalar("c"))]))])),
            ]
        )
        text = y.emit(tree)
        self.assertEqual(_pyyaml.safe_load(text), y.to_plain(tree))


class ParseTests(unittest.TestCase):
    def test_rejects_unsupported(self):
        for bad in (
            "a: |\n  text\n",
            "a: >\n  text\n",
            "a: &anchor 1\n",
            "a: *ref\n",
            "a: 1\na: 2\n",
            "a: !!python/object []\n",
        ):
            with self.assertRaises(y.YamlError, msg=repr(bad)):
                y.parse(bad)

    def test_comment_stripping_outside_quotes(self):
        node = y.parse("a: 'has # inside'\nb: plain # trailing\nc: '#nope'\n")
        self.assertEqual(node.get("a").value, "has # inside")
        self.assertEqual(node.get("b").value, "plain")
        self.assertEqual(node.get("c").value, "#nope")

    def test_flow_values(self):
        node = y.parse("a: []\nb: {}\nc: [1, 2]\nd: {x: 'y'}\n")
        self.assertEqual(y.to_plain(node)["c"], [1, 2])
        self.assertEqual(y.to_plain(node)["d"], {"x": "y"})

    def test_yaml11_resolution(self):
        node = y.parse("t: true\nf: no\non: on\nnul: null\ntilde: ~\n")
        plain = y.to_plain(node)
        self.assertIs(plain["t"], True)
        self.assertIs(plain["f"], False)
        self.assertIs(plain["on"], True)
        self.assertIsNone(plain["nul"])
        self.assertIsNone(plain["tilde"])

    @unittest.skipIf(not GOLDEN.exists(), "golden fixture missing")
    def test_golden_fixture_parses_like_pyyaml(self):
        text = GOLDEN.read_text()
        node = y.parse(text)
        if _pyyaml is not None:
            self.assertEqual(y.to_plain(node), _pyyaml.safe_load(text))

    @unittest.skipIf(not GOLDEN.exists(), "golden fixture missing")
    def test_golden_fixture_round_trip(self):
        node = y.parse(GOLDEN.read_text())
        text2 = y.emit(node)
        self.assertTrue(y.values_equal(node, y.parse(text2)), "golden re-emit mismatch")


if __name__ == "__main__":
    unittest.main()
