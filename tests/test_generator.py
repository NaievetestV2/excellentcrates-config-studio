import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ecstudio import generator as gen
from ecstudio import yamlkit as y
from ecstudio.model import (
    CrateConfig,
    KeyConfig,
    CostEntry,
    CostOption,
    Milestone,
    Reward,
)
from ecstudio.snbt import ItemSpec

try:
    import yaml as _pyyaml
except ImportError:  # pragma: no cover
    _pyyaml = None


def make_full_crate() -> CrateConfig:
    c = CrateConfig(id="armor", name="&a&lArmor Crate")
    c.description = ["&7Best armor on the server!"]
    c.item = ItemSpec(material="CHEST", name="&aArmor Crate", lore=["&7Open me"])
    c.rewards = [
        Reward(
            id="netherite_helmet",
            type="ITEM",
            rarity="common",
            weight=25.0,
            items=[ItemSpec(material="NETHERITE_HELMET")],
        ),
        Reward(
            id="give_coins",
            type="COMMAND",
            rarity="rare",
            weight=5.0,
            name="Coins",
            description=["&6100 coins"],
            commands=["eco give %player_name% 100"],
        ),
    ]
    c.costs = [
        CostOption(
            id="key_armor",
            name="Armor Key",
            icon=ItemSpec(material="TRIAL_KEY"),
            entries=[CostEntry(type="key", key_id="armor", amount=1)],
        )
    ]
    c.positions = ["14,2,1,world"]
    c.post_open_commands = ["say %player_name% opened the armor crate"]
    c.milestones = [Milestone(reward_id="netherite_helmet", openings=10)]
    return c


class CrateGenerationTests(unittest.TestCase):
    def setUp(self):
        self.crate = make_full_crate()
        self.text = gen.generate_crate(self.crate)

    def test_parses_and_round_trips(self):
        node = y.parse(self.text)
        self.assertTrue(y.values_equal(gen.build_crate_tree(self.crate), node))

    @unittest.skipIf(_pyyaml is None, "pyyaml not installed")
    def test_pyyaml_sees_expected_types(self):
        data = _pyyaml.safe_load(self.text)
        self.assertIs(type(data["_dataver"]), int)
        self.assertEqual(data["_dataver"], 600)
        self.assertIs(type(data["ItemStackable"]), bool)
        self.assertIs(type(data["Rewards"]["List"]["netherite_helmet"]["Weight"]), float)
        self.assertIs(type(data["Rewards"]["List"]["netherite_helmet"]["Rarity"]), str)

    @unittest.skipIf(_pyyaml is None, "pyyaml not installed")
    def test_schema_keys_only(self):
        data = _pyyaml.safe_load(self.text)
        self.assertEqual(
            set(data),
            {
                "_dataver",
                "Name",
                "Description",
                "ItemProvider",
                "ItemStackable",
                "Rewards",
                "CostOptions",
                "Permission_Required",
                "Preview",
                "Animation",
                "OpeningCooldown",
                "OpeningLimits",
                "Block",
                "Post-Open",
                "Milestones",
            },
        )
        reward = data["Rewards"]["List"]["netherite_helmet"]
        self.assertEqual(
            set(reward),
            {
                "Type",
                "Rarity",
                "Weight",
                "ItemsData",
                "PreviewData",
                "Custom_Preview",
                "Placeholder_Apply",
                "Broadcast",
                "Required_Permissions",
                "Ignored_For_Permissions",
                "Limits",
            },
        )
        command = data["Rewards"]["List"]["give_coins"]
        self.assertEqual(set(command), {
            "Type", "Rarity", "Weight", "Name", "Description", "Commands",
            "PreviewData", "Broadcast", "Required_Permissions",
            "Ignored_For_Permissions", "Limits",
        })
        self.assertNotIn("ItemsData", command)
        self.assertNotIn("Name", reward)  # unread for ITEM rewards
        self.assertEqual(
            set(data["Block"]), {"Positions", "Pushback", "Hologram", "Effect"}
        )
        self.assertEqual(
            set(data["CostOptions"]["key_armor"]),
            {"Enabled", "Name", "Icon", "Entries"},
        )

    @unittest.skipIf(_pyyaml is None, "pyyaml not installed")
    def test_no_legacy_keys_anywhere(self):
        data = _pyyaml.safe_load(self.text)
        # top-level legacy migrations (Crate.load / RewardFactory.load)
        for legacy_top in ("Item", "Key", "Key.Ids", "Opening", "Preview_Config",
                           "Animation_Config"):
            self.assertNotIn(legacy_top, data)
        # legacy item shape + legacy reward keys, anywhere in the tree
        banned = {"ItemTag", "Handler", "ItemId", "Win_Limits", "Preview_Config",
                  "Animation_Config"}
        reward_banned = {"Preview", "Win_Limits"}

        def walk(node, path=""):
            if isinstance(node, dict):
                for k, v in node.items():
                    self.assertNotIn(k, banned, f"legacy key {k!r} at {path}")
                    if path.startswith("Rewards.List"):
                        self.assertNotIn(k, reward_banned, f"legacy key {k!r} at {path}")
                    walk(v, f"{path}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{path}[{i}]")

        walk(data)

    @unittest.skipIf(_pyyaml is None, "pyyaml not installed")
    def test_cost_and_milestone_shapes(self):
        data = _pyyaml.safe_load(self.text)
        entry = data["CostOptions"]["key_armor"]["Entries"]["0"]
        self.assertEqual(entry, {"Type": "key", "Key": "armor", "Amount": 1})
        milestone = data["Milestones"]["List"]["0"]
        self.assertEqual(milestone, {"Reward_Id": "netherite_helmet", "Openings": 10})
        self.assertEqual(data["Block"]["Positions"], ["14,2,1,world"])

    def test_comments_present_and_safe(self):
        self.assertIn("# ExcellentCrates crate configuration.", self.text)
        self.assertIn("# ", self.text)
        for line in self.text.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue  # comments are fine — Bukkit ignores them

    def test_animation_default_is_valid(self):
        self.assertIn("Id: simple_roll", self.text)

    def test_key_file(self):
        key = KeyConfig(id="armor", name="&6Armor Key")
        text = gen.generate_key(key)
        data = _pyyaml.safe_load(text)
        self.assertEqual(set(data), {"Name", "Virtual", "ItemData", "ItemStackable"})
        self.assertEqual(data["Name"], "&6Armor Key")
        self.assertIs(data["Virtual"], False)
        self.assertEqual(data["ItemData"]["Provider"], "vanilla")
        self.assertIn("tripwire_hook", data["ItemData"]["Data"]["Value"])

    def test_free_crate_omits_costoptions(self):
        c = CrateConfig(id="freebie", name="Free")
        c.rewards = [Reward(id="dirt", items=[ItemSpec(material="DIRT")])]
        text = gen.generate_crate(c)
        self.assertNotIn("CostOptions", _pyyaml.safe_load(text))

    def test_currency_cost_shape(self):
        c = make_full_crate()
        c.costs.append(
            CostOption(
                id="eco_main",
                entries=[CostEntry(type="currency", currency="vault", amount=100.0)],
            )
        )
        data = _pyyaml.safe_load(gen.generate_crate(c))
        entry = data["CostOptions"]["eco_main"]["Entries"]["0"]
        self.assertEqual(entry, {"Type": "currency", "Currency": "vault", "Amount": 100.0})

    def test_particle_dust_writes_color_and_size(self):
        c = make_full_crate()
        c.particle.name = "DUST"
        c.particle.color = "255,128,0"
        c.particle.size = 1.5
        data = _pyyaml.safe_load(gen.generate_crate(c))
        particle = data["Block"]["Effect"]["Particle"]
        self.assertEqual(particle["Name"], "DUST")
        self.assertEqual(particle["Color"], "255,128,0")
        self.assertEqual(particle["Size"], 1.5)

    def test_generate_refuses_on_roundtrip_mismatch(self):
        # defensive: monkeypatch parse to disagree
        import ecstudio.yamlkit as kit
        original = kit.parse
        kit.parse = lambda text: y.Mapping([])
        try:
            with self.assertRaises(RuntimeError):
                gen.generate_crate(self.crate)
        finally:
            kit.parse = original


if __name__ == "__main__":
    unittest.main()
