import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ecstudio import snbt
from ecstudio.snbt import ItemSpec


class ItemSnbtTests(unittest.TestCase):
    def test_minimal_item(self):
        value = snbt.item_snbt(ItemSpec(material="CHEST"))
        self.assertEqual(value, '{count:1,id:"minecraft:chest"}')
        data = snbt.parse_snbt(value)
        self.assertEqual(data["id"], "minecraft:chest")
        self.assertNotIn("components", data)

    def test_amount(self):
        data = snbt.parse_snbt(snbt.item_snbt(ItemSpec(material="DIAMOND", amount=16)))
        self.assertEqual(data["count"], 16)

    def test_named_item_components(self):
        spec = ItemSpec(material="TRIPWIRE_HOOK", name="&a&lKey", lore=["&7line one", "plain"])
        data = snbt.parse_snbt(snbt.item_snbt(spec))
        name = data["components"]["minecraft:custom_name"]
        self.assertEqual(name["text"], "Key")
        self.assertEqual(name["color"], "#55FF55")
        self.assertIs(name["bold"], True)
        self.assertIs(name["italic"], False)
        lore = data["components"]["minecraft:lore"]
        self.assertEqual(len(lore), 2)
        self.assertEqual(lore[0]["text"], "line one")
        self.assertEqual(lore[1]["text"], "plain")
        self.assertIs(lore[1]["italic"], False)

    def test_gradient_splits_into_extra(self):
        spec = ItemSpec(material="PAPER", name="&#FF0000A&#00FF00B")
        data = snbt.parse_snbt(snbt.item_snbt(spec))
        name = data["components"]["minecraft:custom_name"]
        self.assertEqual(name["text"], "A")
        self.assertEqual(name["color"], "#FF0000")
        self.assertEqual(name["extra"][0]["text"], "B")
        self.assertEqual(name["extra"][0]["color"], "#00FF00")

    def test_head_texture(self):
        spec = ItemSpec(material="PLAYER_HEAD", texture="eyJ0ZXh0dXJlcyI6fX0=")
        data = snbt.parse_snbt(snbt.item_snbt(spec))
        profile = data["components"]["minecraft:profile"]
        self.assertEqual(profile["properties"][0]["name"], "textures")
        self.assertEqual(profile["properties"][0]["value"], "eyJ0ZXh0dXJlcyI6fX0=")

    def test_bad_material_rejected(self):
        with self.assertRaises(snbt.SnbtError):
            snbt.item_snbt(ItemSpec(material="Not A Material"))

    def test_write_item_provider(self):
        node = snbt.write_item_provider(ItemSpec(material="CHEST"))
        self.assertEqual(node["Provider"], "vanilla")
        self.assertTrue(node["Data"]["Value"].startswith("{count:1"))
        custom = snbt.write_item_provider(
            ItemSpec(provider="nexo", custom_id="ruby_sword", amount=2)
        )
        self.assertEqual(
            custom, {"Provider": "nexo", "Data": {"ID": "ruby_sword", "Amount": 2}}
        )

    def test_extract_round_trip(self):
        spec = ItemSpec(
            material="PLAYER_HEAD",
            name="&bHead &7of &cGlory",
            lore=["&8line", "plain"],
            texture="eyJhIjoxfQ==",
        )
        back = snbt.extract_item(snbt.item_snbt(spec))
        self.assertIsNotNone(back)
        self.assertEqual(back.material, "PLAYER_HEAD")
        self.assertEqual(back.name, spec.name)
        self.assertEqual(back.lore, spec.lore)
        self.assertEqual(back.texture, spec.texture)

    def test_extract_plain_item(self):
        back = snbt.extract_item('{count:4,id:"minecraft:diamond"}')
        self.assertEqual(back.material, "DIAMOND")
        self.assertEqual(back.amount, 4)
        self.assertEqual(back.name, "")


class LegacyTextTests(unittest.TestCase):
    def test_codes(self):
        parts = snbt.legacy_to_components("&aHello &lWorld")
        self.assertEqual(parts[0]["text"], "Hello ")
        self.assertEqual(parts[0]["color"], "#55FF55")
        self.assertEqual(parts[1]["text"], "World")
        self.assertIs(parts[1]["bold"], True)
        self.assertIs(parts[1]["italic"], False)

    def test_color_resets_styles(self):
        parts = snbt.legacy_to_components("&lBold&cPlain")
        self.assertIs(parts[0]["bold"], True)
        self.assertNotIn("bold", parts[1])
        self.assertEqual(parts[1]["color"], "#FF5555")

    def test_reset_and_section_sign(self):
        parts = snbt.legacy_to_components("§cRed§rNormal")
        self.assertEqual(parts[0]["color"], "#FF5555")
        self.assertNotIn("color", parts[1])

    def test_style_off_via_false_flag(self):
        legacy = snbt.components_to_legacy({"text": "x", "italic": False})
        self.assertEqual(legacy, "x")

    def test_round_trip_fixed_point(self):
        original = "&aGreen &lBold text"
        comps = snbt.legacy_to_components(original)
        legacy = snbt.components_to_legacy(comps)
        self.assertEqual(snbt.legacy_to_components(legacy), comps)
        self.assertEqual(legacy, "&aGreen &a&lBold text")


class SnbtParserTests(unittest.TestCase):
    def test_types(self):
        self.assertEqual(
            snbt.parse_snbt('{a:1,b:0b,c:1.5f,d:"str",e:[1,2],f:{g:2}}'),
            {"a": 1, "b": False, "c": 1.5, "d": "str", "e": [1, 2], "f": {"g": 2}},
        )

    def test_quoted_keys(self):
        data = snbt.parse_snbt('{"minecraft:custom_name":{text:"x"}}')
        self.assertEqual(data["minecraft:custom_name"]["text"], "x")

    def test_golden_head_value(self):
        golden = (
            '{components:{"minecraft:profile":{properties:[{name:"textures",'
            'value:"eyJ0ZXh0dXJlcyI6fX0="}]}},count:1,id:"minecraft:player_head"}'
        )
        data = snbt.parse_snbt(golden)
        self.assertEqual(data["id"], "minecraft:player_head")
        self.assertEqual(data["count"], 1)
        props = data["components"]["minecraft:profile"]["properties"]
        self.assertEqual(props[0]["value"], "eyJ0ZXh0dXJlcyI6fX0=")

    def test_trailing_garbage_rejected(self):
        with self.assertRaises(snbt.SnbtError):
            snbt.parse_snbt("{a:1} junk")


if __name__ == "__main__":
    unittest.main()
