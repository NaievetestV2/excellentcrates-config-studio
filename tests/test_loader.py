"""Import tests: plugin-authored YAML -> model -> regenerated YAML."""

import unittest
from pathlib import Path

from ecstudio import yamlkit as y
from ecstudio.generator import generate_crate, generate_key
from ecstudio.loader import LoadError, load_crate, load_key

GOLDEN = Path("/tmp/opencode/armor_crate.yml")

MINIMAL = """\
Name: 'Test Crate'
Description:
- 'Hello'
ItemProvider:
  Provider: vanilla
  Data:
    Value: '{count:1,id:"minecraft:chest"}'
Rewards:
  List:
    dirt:
      Weight: 10.0
      Rarity: common
      Type: ITEM
      ItemsData:
        '0':
          Provider: vanilla
          Data:
            Value: '{count:4,id:"minecraft:dirt"}'
"""


class MinimalCrateTests(unittest.TestCase):
    def test_load_minimal(self):
        crate = load_crate(MINIMAL).config
        self.assertEqual(crate.name, "Test Crate")
        self.assertEqual(crate.description, ["Hello"])
        self.assertEqual(crate.item.material, "CHEST")
        reward = crate.reward_by_id("dirt")
        self.assertIsNotNone(reward)
        self.assertEqual(reward.weight, 10.0)
        self.assertEqual(reward.items[0].material, "DIRT")
        self.assertEqual(reward.items[0].amount, 4)

    def test_generate_keeps_raw_snbt(self):
        crate = load_crate(MINIMAL).config
        out = generate_crate(crate)
        self.assertIn('Value: \'{count:1,id:"minecraft:chest"}\'', out)
        self.assertIn('Value: \'{count:4,id:"minecraft:dirt"}\'', out)

    def test_unknown_top_level_preserved(self):
        text = MINIMAL + "\nFutureOption: 42\n"
        result = load_crate(text)
        self.assertTrue(any("FutureOption" in w for w in result.warnings))
        out = generate_crate(result.config)
        self.assertIn("FutureOption: 42", out)

    def test_legacy_item_key_rejected(self):
        with self.assertRaises(LoadError):
            load_crate("Item:\n  Type: CHEST\nName: 'x'\n")

    def test_unparseable_snbt_rejected(self):
        text = MINIMAL.replace('{count:4,id:"minecraft:dirt"}', "{broken")
        with self.assertRaises(LoadError):
            load_crate(text)

    def test_command_reward_fields(self):
        text = """\
Name: 'Cmd'
Rewards:
  List:
    say:
      Type: COMMAND
      Name: '&6Hello'
      Description:
      - 'line'
      Commands:
      - 'say hi'
      Weight: 1.0
      Rarity: common
"""
        reward = load_crate(text).config.reward_by_id("say")
        self.assertEqual(reward.type, "COMMAND")
        self.assertEqual(reward.name, "&6Hello")
        self.assertEqual(reward.description, ["line"])
        self.assertEqual(reward.commands, ["say hi"])

    def test_particle_legacy_rename(self):
        text = """\
Name: 'P'
Block:
  Effect:
    Model: HELIX
    Particle:
      Name: REDSTONE
      Color: '49,225,136'
      Size: 1.0
Rewards:
  List:
    dirt:
      Weight: 1.0
      Rarity: common
      Type: ITEM
      ItemsData:
        '0':
          Provider: vanilla
          Data:
            Value: '{count:1,id:"minecraft:dirt"}'
"""
        crate = load_crate(text).config
        self.assertEqual(crate.particle.name, "DUST")
        self.assertEqual(crate.particle.color, "49,225,136")

    def test_extra_nbt_preserved_until_edited(self):
        value = (
            '{count:1,id:"minecraft:diamond_sword",'
            'components:{"minecraft:enchantments":{levels:{"minecraft:sharpness":5}}}}'
        )
        text = MINIMAL.replace('{count:4,id:"minecraft:dirt"}', value)
        crate = load_crate(text).config
        out = generate_crate(crate)
        self.assertIn(value, out)

        # editing the item drops the raw value (ItemDialog behavior) -> component gone
        item = crate.reward_by_id("dirt").items[0]
        item.material = "DIAMOND"
        item.raw_value = None
        out2 = generate_crate(crate)
        self.assertNotIn("minecraft:sharpness", out2)


@unittest.skipUnless(GOLDEN.exists(), "golden fixture missing")
class GoldenCrateTests(unittest.TestCase):
    def test_golden_import_semantics(self):
        text = GOLDEN.read_text()
        result = load_crate(text)
        crate = result.config
        self.assertEqual(crate.name, "&a&lArmor Crate")
        self.assertEqual(len(crate.rewards), 20)
        self.assertEqual(crate.positions, ["14,2,1,world"])
        self.assertEqual(crate.particle.name, "DUST")
        link = crate.key_cost()
        self.assertIsNotNone(link)
        self.assertEqual(link.type, "key")
        self.assertTrue(link.key_id)

        out = generate_crate(crate)
        data = y.to_plain(y.parse(out))
        # plugin-written DataVersion beside Data.Value survives import
        self.assertEqual(data["ItemProvider"]["Data"]["DataVersion"], 4556)
        # unknown runtime keys preserved
        self.assertIn("Last_Opener", data)
        # raw reward item SNBT untouched
        first = next(iter(data["Rewards"]["List"].values()))
        self.assertEqual(
            first["ItemsData"]["0"]["Data"]["Value"],
            next(iter(y.to_plain(y.parse(text))["Rewards"]["List"].values()))
            ["ItemsData"]["0"]["Data"]["Value"],
        )
        # unread legacy reward names on ITEM rewards are not re-emitted
        self.assertNotIn("Name", first)
        # safe defaults added back
        self.assertIn("OpeningLimits", data)
        self.assertIn("Post-Open", data)


class KeyTests(unittest.TestCase):
    def test_key_roundtrip(self):
        text = """\
Name: '&bArmor Key'
Virtual: false
ItemData:
  Provider: vanilla
  Data:
    Value: '{count:1,id:"minecraft:tripwire_hook"}'
ItemStackable: true
"""
        key = load_key(text).config
        self.assertEqual(key.name, "&bArmor Key")
        self.assertEqual(key.item.material, "TRIPWIRE_HOOK")
        out = generate_key(key)
        data = y.to_plain(y.parse(out))
        self.assertEqual(data["Name"], "&bArmor Key")
        self.assertIn("ItemData", data)

    def test_key_legacy_item_rejected(self):
        with self.assertRaises(LoadError):
            load_key("Name: 'x'\nItem:\n  Type: TRIPWIRE_HOOK\n")


if __name__ == "__main__":
    unittest.main()
