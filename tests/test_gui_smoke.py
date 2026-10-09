"""GUI smoke tests: drive the Tkinter app headlessly against the real model.

Skipped automatically when tkinter or a display is unavailable.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import tkinter  # noqa: F401

    _HAVE_TK = True
except ImportError:
    _HAVE_TK = False

HAVE_DISPLAY = _HAVE_TK and bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

GOLDEN = Path("/tmp/opencode/armor_crate.yml")


@unittest.skipUnless(HAVE_DISPLAY, "tkinter/display unavailable")
class GuiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ecstudio import gui

        cls.gui = gui

    def setUp(self):
        self.app = self.gui.Studio()
        self.app.last_crates = ""
        self.app.last_keys = ""
        self.app._save_state = lambda: None  # never touch the user's state file
        self.app.withdraw()  # keep the window off-screen where possible
        self.app.update_idletasks()

    def tearDown(self):
        self.app.destroy()

    def _drive_preview(self):
        # run one preview/validation cycle without rescheduling the timer loop
        with mock.patch.object(self.app, "after"):
            self.app._tick()

    def test_preview_and_validation_render(self):
        self._drive_preview()
        preview = self.app.preview.get("1.0", "end")
        self.assertIn("ExcellentCrates crate configuration", preview)
        self.assertIn("Name:", preview)
        children = self.app.valid_tree.get_children()
        self.assertGreaterEqual(len(children), 0)

    def test_editing_model_updates_preview(self):
        self._drive_preview()
        before = self.app.preview.get("1.0", "end")
        self.app.crate.name = "Renamed Crate"
        self._drive_preview()
        after = self.app.preview.get("1.0", "end")
        self.assertNotEqual(before, after)
        self.assertIn("Renamed Crate", after)

    def test_reward_add_remove(self):
        self.assertEqual(len(self.app.crate.rewards), 1)
        self.app._rw_add("COMMAND")
        self.assertEqual(len(self.app.crate.rewards), 2)
        self.assertEqual(self.app.crate.rewards[-1].type, "COMMAND")
        self.app.rw_list.selection_set(1)
        self.app._rw_select()
        self.app._rw_remove()
        self.assertEqual(len(self.app.crate.rewards), 1)

    def test_cost_link_to_key(self):
        self.app._cost_add("key")
        self.assertEqual(len(self.app.crate.costs), 1)
        entry = self.app.crate.costs[0].entries[0]
        self.assertEqual(entry.type, "key")
        self.assertEqual(entry.key_id, self.app.key.id)

    def test_save_both_writes_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            crates = Path(tmp) / "crates"
            keys = Path(tmp) / "keys"
            crates.mkdir()
            keys.mkdir()
            directories = iter([str(crates), str(keys)])
            with mock.patch.object(
                self.gui.filedialog, "askdirectory", side_effect=lambda **_k: next(directories)
            ), mock.patch.object(self.gui.messagebox, "showinfo"), mock.patch.object(
                self.gui.messagebox, "showerror"
            ) as error:
                self.app.save_both()
            error.assert_not_called()
            crate_file = crates / f"{self.app.crate.id}.yml"
            key_file = keys / f"{self.app.key.id}.yml"
            self.assertTrue(crate_file.exists())
            self.assertTrue(key_file.exists())
            self.assertIn("ExcellentCrates crate configuration", crate_file.read_text())

    def test_save_blocked_on_errors(self):
        self.app.crate.rewards.clear()
        with mock.patch.object(self.gui.messagebox, "showerror") as error, mock.patch.object(
            self.gui.filedialog, "askdirectory"
        ) as askdir:
            self.app.save_both()
        error.assert_called()
        askdir.assert_not_called()

    @unittest.skipUnless(GOLDEN.exists(), "golden fixture missing")
    def test_open_crate_golden(self):
        with mock.patch.object(
            self.gui.filedialog, "askopenfilename", return_value=str(GOLDEN)
        ), mock.patch.object(self.gui.messagebox, "showerror") as error:
            self.app.open_crate()
        error.assert_not_called()
        self.assertEqual(self.app.crate.name, "&a&lArmor Crate")
        self.assertEqual(len(self.app.crate.rewards), 20)
        self._drive_preview()
        preview = self.app.preview.get("1.0", "end")
        self.assertIn("Armor Crate", preview)

    def test_tabs_sorted_by_relevancy(self):
        tabs = self.app.notebook.tabs()
        texts = [self.app.notebook.tab(t, "text") for t in tabs]
        self.assertIn("Basics", texts[0])
        self.assertLess(texts.index(texts[0]), texts.index(
            [t for t in texts if "Advanced" in t][0]
        ))


if __name__ == "__main__":
    unittest.main()
