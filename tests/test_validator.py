import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ecstudio.model import (
    CrateConfig,
    KeyConfig,
    CostEntry,
    CostOption,
    Milestone,
    Reward,
)
from ecstudio.snbt import ItemSpec
from ecstudio.validator import (
    has_errors,
    validate_crate,
    validate_key,
    MATERIALS,
    PARTICLES,
)


def good_crate() -> CrateConfig:
    c = CrateConfig(id="armor", name="&aArmor Crate")
    c.rewards = [Reward(id="dirt", items=[ItemSpec(material="DIRT")])]
    c.costs = [
        CostOption(id="key_armor", entries=[CostEntry(type="key", key_id="armor", amount=1)])
    ]
    c.positions = ["14,2,1,world"]
    return c


def errors(problems):
    return [p for p in problems if p.level == "error"]


def find(problems, path_fragment, level=None):
    return [
        p for p in problems
        if path_fragment in p.path and (level is None or p.level == level)
    ]


class DataFilesTests(unittest.TestCase):
    def test_materials_and_particles_loaded(self):
        self.assertGreater(len(MATERIALS), 1000)
        self.assertIn("DIAMOND", MATERIALS)
        self.assertIn("CLOUD", PARTICLES)
        self.assertIn("DUST", PARTICLES)


class CrateValidationTests(unittest.TestCase):
    def test_valid_crate_and_key_have_no_errors(self):
        crate = good_crate()
        key = KeyConfig(id="armor", name="Armor Key")
        self.assertFalse(has_errors(validate_crate(crate, key)))
        self.assertFalse(has_errors(validate_key(key)))

    def test_bad_id(self):
        crate = good_crate()
        crate.id = "Armor Crate"
        problems = validate_crate(crate)
        errs = find(problems, "id (crates", "error")
        self.assertTrue(errs)
        self.assertIn("armor_crate", errs[0].hint)

    def test_missing_name_and_rewards(self):
        crate = good_crate()
        crate.name = "  "
        crate.rewards = []
        problems = validate_crate(crate)
        self.assertTrue(find(problems, "Name", "error"))
        self.assertTrue(find(problems, "Rewards.List", "error"))

    def test_default_animation_is_error(self):
        crate = good_crate()
        crate.animation_id = "default"
        problems = validate_crate(crate)
        self.assertTrue(find(problems, "Animation.Id", "error"))

    def test_unknown_builtin_animation_warns(self):
        crate = good_crate()
        crate.animation_id = "fancy_custom"
        problems = validate_crate(crate)
        self.assertFalse(has_errors(problems))
        self.assertTrue(find(problems, "Animation.Id", "warning"))

    def test_weight_must_be_positive(self):
        crate = good_crate()
        crate.rewards[0].weight = 0
        problems = validate_crate(crate)
        self.assertTrue(find(problems, "Weight", "error"))

    def test_unknown_rarity_warns_with_snippet(self):
        crate = good_crate()
        crate.rewards[0].rarity = "legendary"
        problems = validate_crate(crate)
        warns = find(problems, "Rarity", "warning")
        self.assertTrue(warns)
        self.assertIn("Rewards:", warns[0].hint)
        self.assertIn("legendary:", warns[0].hint)

    def test_bad_material(self):
        crate = good_crate()
        crate.rewards[0].items[0].material = "NOT_A_MATERIAL"
        problems = validate_crate(crate)
        self.assertTrue(find(problems, "ItemsData.0", "error"))

    def test_command_slash_rejected(self):
        crate = good_crate()
        crate.rewards = [
            Reward(id="cmd", type="COMMAND", commands=["/give %player_name% diamond"])
        ]
        problems = validate_crate(crate)
        self.assertTrue(find(problems, "Commands[0]", "error"))

    def test_command_ok_but_info_about_server(self):
        crate = good_crate()
        crate.rewards = [
            Reward(id="cmd", type="COMMAND", commands=["give %player_name% diamond"])
        ]
        problems = validate_crate(crate)
        self.assertFalse(has_errors(problems))
        self.assertTrue(find(problems, "Commands[0]", "info"))

    def test_position_format(self):
        crate = good_crate()
        crate.positions = ["14 2 1 world"]
        problems = validate_crate(crate)
        self.assertTrue(find(problems, "Block.Positions[0]", "error"))

    def test_milestone_unknown_reward(self):
        crate = good_crate()
        crate.milestones = [Milestone(reward_id="ghost", openings=5)]
        problems = validate_crate(crate)
        self.assertTrue(find(problems, "Reward_Id", "error"))

    def test_key_link_mismatch_warns(self):
        crate = good_crate()  # links to key 'armor'
        key = KeyConfig(id="other_key", name="Other")
        problems = validate_crate(crate, key)
        self.assertTrue(find(problems, "Key", "warning"))
        self.assertTrue(find(problems, "CostOptions", "warning"))

    def test_crate_without_key_cost_warns_when_key_given(self):
        crate = good_crate()
        crate.costs = []
        key = KeyConfig(id="armor", name="Armor Key")
        problems = validate_crate(crate, key)
        warns = find(problems, "CostOptions", "warning")
        self.assertTrue(warns)
        self.assertIn("will not open it", warns[0].message)

    def test_unknown_particle_warns(self):
        crate = good_crate()
        crate.particle.name = "REDSTONE"  # removed from the enum in 1.21.3
        problems = validate_crate(crate)
        self.assertTrue(find(problems, "Particle.Name", "warning"))
        self.assertFalse(has_errors(problems))

    def test_dust_requires_color(self):
        crate = good_crate()
        crate.particle.name = "DUST"
        crate.particle.color = ""
        problems = validate_crate(crate)
        self.assertTrue(find(problems, "Particle.Color", "error"))

    def test_unsupported_particle_warns(self):
        crate = good_crate()
        crate.particle.name = "VIBRATION"
        problems = validate_crate(crate)
        self.assertTrue(find(problems, "Particle.Name", "warning"))

    def test_opening_limit_minimum(self):
        crate = good_crate()
        crate.opening_limit_amount = 0
        problems = validate_crate(crate)
        self.assertTrue(find(problems, "OpeningLimits.Amount", "error"))

    def test_unknown_effect_model_warns(self):
        crate = good_crate()
        crate.effect_model = "disco"
        problems = validate_crate(crate)
        self.assertTrue(find(problems, "Block.Effect.Model", "warning"))

    def test_sorted_errors_first(self):
        crate = good_crate()
        crate.animation_id = "default"
        crate.positions = ["bad"]
        problems = validate_crate(crate)
        levels = [p.level for p in problems]
        self.assertEqual(levels, sorted(levels, key=lambda l: {"error": 0, "warning": 1, "info": 2}[l]))


class KeyValidationTests(unittest.TestCase):
    def test_key_errors(self):
        key = KeyConfig(id="", name="")
        key.item.material = "BOGUS"
        problems = validate_key(key)
        self.assertTrue(has_errors(problems))
        paths = {p.path for p in problems if p.level == "error"}
        self.assertIn("id (keys/<id>.yml)", paths)
        self.assertIn("Name", paths)


if __name__ == "__main__":
    unittest.main()
