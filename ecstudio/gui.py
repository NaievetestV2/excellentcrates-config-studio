"""ExcellentCrates Config Studio — Tkinter GUI.

Layout
------
* toolbar: crate/key ids, open/save actions
* left notebook, sorted by relevancy (required first, deep options last):
  Basics -> Rewards -> Costs & key -> World & effects -> Advanced
* right: live YAML preview (top) + validation panel (bottom)
"""

from __future__ import annotations

import json
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional

from .generator import generate_crate, generate_key
from .loader import LoadError, load_crate, load_key
from .model import (
    CostEntry,
    CostOption,
    CrateConfig,
    ItemSpec,
    KeyConfig,
    Milestone,
    PluginDefaults,
    Reward,
    default_crate_item,
    default_key_item,
    is_var_style,
)
from .validator import MATERIALS, Problem, has_errors, validate_crate, validate_key
from .widgets import ItemDialog, ListEditor, ScrollFrame

__all__ = ["Studio"]

_STATE_FILE = Path.home() / ".ecstudio.json"
_PREVIEW_MS = 400
_LEVEL_TAG = {"error": "err", "warning": "warn", "info": "info"}


def _example_reward() -> Reward:
    """A ready-to-save reward so a fresh crate passes validation."""
    reward = Reward(id="example_dirt", type="ITEM", rarity="common", weight=10.0)
    reward.items.append(ItemSpec(material="DIRT", amount=4, name="&7Dirt"))
    return reward


def _item_label(spec: Optional[ItemSpec]) -> str:
    if spec is None:
        return "(none)"
    if spec.is_vanilla():
        text = f"{spec.material} x{spec.amount}"
    else:
        text = f"{spec.provider}:{spec.custom_id} x{spec.amount}"
    return f"{text}  {spec.name}".rstrip()


class Studio(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ExcellentCrates Config Studio")
        self.geometry("1400x880")
        self.minsize(940, 600)

        self.crate = CrateConfig(item=default_crate_item("My Crate"))
        self.crate.rewards.append(_example_reward())
        self.key = KeyConfig(item=default_key_item("My Key"))
        self.import_warnings: list[str] = []
        self.last_crates = ""
        self.last_keys = ""
        self._sashes_fixed = False
        self._started_at = time.monotonic()
        self._load_state()
        self._problems_cache: list[Problem] = []
        self._last_preview = ""

        self.protocol("WM_DELETE_WINDOW", self._quit)
        self._build_style()
        self._build_menu()
        self._build_toolbar()
        self._build_main()
        self._build_statusbar()
        self.rebuild_tabs()
        self.after(200, self._tick)

    # ------------------------------------------------------------------ chrome

    def _build_style(self):
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TNotebook.Tab", padding=(12, 4))
        style.configure("Header.TLabel", font=("TkDefaultFont", 10, "bold"))
        style.configure("Err.TLabel", foreground="#b00020")
        style.configure("Warn.TLabel", foreground="#8a6d00")

    def _build_menu(self):
        menubar = tk.Menu(self)
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="New crate", command=self.new_crate, accelerator="Ctrl+N")
        filemenu.add_command(label="New key", command=self.new_key)
        filemenu.add_separator()
        filemenu.add_command(label="Open crate…", command=self.open_crate, accelerator="Ctrl+O")
        filemenu.add_command(label="Open key…", command=self.open_key)
        filemenu.add_separator()
        filemenu.add_command(label="Save crate + key…", command=self.save_both, accelerator="Ctrl+S")
        filemenu.add_separator()
        filemenu.add_command(label="Quit", command=self._quit)
        menubar.add_cascade(label="File", menu=filemenu)

        helpmenu = tk.Menu(menubar, tearoff=0)
        helpmenu.add_command(label="About", command=self._about)
        helpmenu.add_command(label="Where do files go?", command=self._where)
        menubar.add_cascade(label="Help", menu=helpmenu)
        self.config(menu=menubar)

        self.bind("<Control-n>", lambda _e: self.new_crate())
        self.bind("<Control-o>", lambda _e: self.open_crate())
        self.bind("<Control-s>", lambda _e: self.save_both())

    def _build_toolbar(self):
        bar = ttk.Frame(self, padding=(8, 6))
        bar.pack(fill="x")

        ttk.Label(bar, text="Crate id:").pack(side="left")
        self.crate_id_var = tk.StringVar(value=self.crate.id)
        self.crate_id_var.trace_add("write", lambda *_: self._set_id("crate"))
        ttk.Entry(bar, textvariable=self.crate_id_var, width=13).pack(side="left", padx=(4, 14))

        ttk.Label(bar, text="Key id:").pack(side="left")
        self.key_id_var = tk.StringVar(value=self.key.id)
        self.key_id_var.trace_add("write", lambda *_: self._set_id("key"))
        ttk.Entry(bar, textvariable=self.key_id_var, width=13).pack(side="left", padx=(4, 14))

        ttk.Button(bar, text="Open crate", command=self.open_crate).pack(side="left", padx=2)
        ttk.Button(bar, text="Open key", command=self.open_key).pack(side="left", padx=2)
        ttk.Button(bar, text="Save…", command=self.save_both).pack(side="right", padx=2)
        ttk.Button(bar, text="Validate", command=self._tick).pack(side="right", padx=2)

    def _build_main(self):
        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=6, pady=(0, 4))
        self.main_paned = paned

        self.notebook = ttk.Notebook(paned)
        paned.add(self.notebook, weight=3)

        right = ttk.Panedwindow(paned, orient="vertical")
        paned.add(right, weight=3)
        self.right_paned = right

        preview_frame = ttk.Frame(right)
        right.add(preview_frame, weight=3)
        ttk.Label(preview_frame, text="Live YAML preview", style="Header.TLabel").pack(
            anchor="w", padx=4, pady=(2, 0)
        )
        self.preview = tk.Text(
            preview_frame, wrap="none", width=52, state="disabled",
            font=("monospace", 10), background="#1e1e1e", foreground="#d4d4d4",
            insertbackground="#d4d4d4", padx=6, pady=4,
        )
        scroll_y = ttk.Scrollbar(preview_frame, orient="vertical", command=self.preview.yview)
        self.preview.configure(yscrollcommand=scroll_y.set)
        scroll_y.pack(side="right", fill="y")
        self.preview.pack(fill="both", expand=True, padx=(4, 0), pady=(0, 4))

        valid_frame = ttk.Frame(right)
        right.add(valid_frame, weight=2)
        ttk.Label(valid_frame, text="Validation", style="Header.TLabel").pack(
            anchor="w", padx=4, pady=(2, 0)
        )
        columns = ("level", "path", "message")
        self.valid_tree = ttk.Treeview(
            valid_frame, columns=columns, show="headings", height=8, selectmode="browse"
        )
        self.valid_tree.heading("level", text="Level")
        self.valid_tree.heading("path", text="Path")
        self.valid_tree.heading("message", text="Message")
        self.valid_tree.column("level", width=70, stretch=False)
        self.valid_tree.column("path", width=200, stretch=True)
        self.valid_tree.column("message", width=380, stretch=True)
        self.valid_tree.tag_configure("err", foreground="#b00020")
        self.valid_tree.tag_configure("warn", foreground="#8a6d00")
        self.valid_tree.tag_configure("info", foreground="#336699")
        scroll_v = ttk.Scrollbar(valid_frame, orient="vertical", command=self.valid_tree.yview)
        self.valid_tree.configure(yscrollcommand=scroll_v.set)
        scroll_v.pack(side="right", fill="y", pady=(0, 4))
        self.valid_tree.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self.valid_tree.bind("<Double-1>", self._on_problem_double_click)

    def _build_statusbar(self):
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w").pack(
            fill="x", side="bottom"
        )

    # -------------------------------------------------------------------- tabs

    def rebuild_tabs(self):
        for name in (
            "basics", "rewards", "costs", "world", "advanced",
        ):
            getattr(self, f"tab_{name}", None) and self.notebook.forget(
                getattr(self, f"tab_{name}")
            )
        self.tab_basics = ttk.Frame(self.notebook)
        self.tab_rewards = ttk.Frame(self.notebook)
        self.tab_costs = ttk.Frame(self.notebook)
        self.tab_world = ttk.Frame(self.notebook)
        self.tab_advanced = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_basics, text=" 1. Basics ")
        self.notebook.add(self.tab_rewards, text=" 2. Rewards ")
        self.notebook.add(self.tab_costs, text=" 3. Costs & key ")
        self.notebook.add(self.tab_world, text=" 4. World ")
        self.notebook.add(self.tab_advanced, text=" 5. Advanced ")

        self._build_basics()
        self._build_rewards()
        self._build_costs()
        self._build_world()
        self._build_advanced()
        self.crate_id_var.set(self.crate.id)
        self.key_id_var.set(self.key.id)
        self.after(50, self._fix_sashes)

    def _fix_sashes(self, force: bool = False):
        """Initial sash positions (no-WM sessions start at extremes).

        Re-applied for the first ~1.5s: X Configure events during startup can
        reset panedwindow sashes. After that it stops, so the user's own
        dragging and tab rebuilds never fight the layout.
        """
        if self._sashes_fixed and not force:
            return
        try:
            self.main_paned.sashpos(0, 840)
            self.right_paned.sashpos(0, 470)
        except tk.TclError:
            return
        if time.monotonic() - self._started_at < 1.5:
            self.after(150, self._fix_sashes)
        else:
            self._sashes_fixed = True

    def _set_id(self, kind: str):
        if kind == "crate":
            self.crate.id = self.crate_id_var.get().strip()
        else:
            self.key.id = self.key_id_var.get().strip()

    # ------------------------------------------------------------------ basics

    def _build_basics(self):
        scroll = ScrollFrame(self.tab_basics)
        scroll.pack(fill="both", expand=True)
        body = ttk.Frame(scroll.body, padding=10)
        body.pack(fill="both", expand=True)

        # --- crate (required) ---
        ttk.Label(body, text="Crate", style="Header.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(body, text="Display name").grid(row=1, column=0, sticky="w", pady=2)
        name_var = tk.StringVar(value=self.crate.name)
        name_var.trace_add("write", lambda *_: setattr(self.crate, "name", name_var.get()))
        ttk.Entry(body, textvariable=name_var, width=44).grid(row=1, column=1, sticky="we", pady=2)

        ttk.Label(body, text="GUI item").grid(row=2, column=0, sticky="nw", pady=2)
        item_bar = ttk.Frame(body)
        item_bar.grid(row=2, column=1, sticky="we", pady=2)
        self.crate_item_label = ttk.Label(item_bar, text=_item_label(self.crate.item))
        self.crate_item_label.pack(side="left")
        ttk.Button(item_bar, text="Edit…", width=8, command=self._edit_crate_item).pack(
            side="left", padx=6
        )
        ttk.Label(body, text="Shown in the /crates menu.").grid(row=3, column=1, sticky="w")

        ttk.Label(body, text="Description").grid(row=4, column=0, sticky="nw", pady=2)
        desc = ListEditor(body, width=44, height=4)
        desc.grid(row=4, column=1, sticky="we")
        desc.set(self.crate.description)
        desc._on_change = lambda: setattr(self.crate, "description", desc.get())

        stack_var = tk.BooleanVar(value=self.crate.item_stackable)
        stack_var.trace_add("write", lambda *_: setattr(self.crate, "item_stackable", stack_var.get()))
        ttk.Checkbutton(body, text="Stackable (one slot can hold many crates)",
                        variable=stack_var).grid(row=5, column=1, sticky="w", pady=2)

        perm_var = tk.BooleanVar(value=self.crate.permission_required)
        perm_var.trace_add("write", lambda *_: setattr(self.crate, "permission_required", perm_var.get()))
        ttk.Checkbutton(
            body,
            text="Require permission excellentcrates.crate.<id> to open",
            variable=perm_var,
        ).grid(row=6, column=1, sticky="w", pady=2)

        # --- key (required if key-gated) ---
        ttk.Separator(body, orient="horizontal").grid(
            row=7, column=0, columnspan=3, sticky="we", pady=10
        )
        ttk.Label(body, text="Linked key", style="Header.TLabel").grid(
            row=8, column=0, columnspan=3, sticky="w"
        )
        ttk.Label(body, text="Key name").grid(row=9, column=0, sticky="w", pady=2)
        key_name_var = tk.StringVar(value=self.key.name)
        key_name_var.trace_add("write", lambda *_: setattr(self.key, "name", key_name_var.get()))
        ttk.Entry(body, textvariable=key_name_var, width=44).grid(row=9, column=1, sticky="we", pady=2)

        ttk.Label(body, text="Key item").grid(row=10, column=0, sticky="nw", pady=2)
        key_bar = ttk.Frame(body)
        key_bar.grid(row=10, column=1, sticky="we", pady=2)
        self.key_item_label = ttk.Label(key_bar, text=_item_label(self.key.item))
        self.key_item_label.pack(side="left")
        ttk.Button(key_bar, text="Edit…", width=8, command=self._edit_key_item).pack(
            side="left", padx=6
        )

        virtual_var = tk.BooleanVar(value=self.key.virtual)
        virtual_var.trace_add("write", lambda *_: setattr(self.key, "virtual", virtual_var.get()))
        ttk.Checkbutton(
            body, text="Virtual key (no item, pure counter)", variable=virtual_var
        ).grid(row=11, column=1, sticky="w", pady=2)
        ttk.Label(
            body,
            text="The crate's key cost (tab 3) must reference this key id.",
        ).grid(row=12, column=1, sticky="w")

        ttk.Label(
            body,
            text="Both files are saved together: crates/<crate id>.yml + keys/<key id>.yml",
            foreground="#555555",
        ).grid(row=13, column=0, columnspan=3, sticky="w", pady=(14, 0))

        body.columnconfigure(1, weight=1)

    def _edit_crate_item(self):
        def done(result: Optional[ItemSpec]):
            if result is not None:
                self.crate.item = result
                self.crate_item_label.configure(text=_item_label(result))

        self._open_item_dialog(self.crate.item, "Crate GUI item", done)

    def _edit_key_item(self):
        def done(result: Optional[ItemSpec]):
            if result is not None:
                self.key.item = result
                self.key_item_label.configure(text=_item_label(result))

        self._open_item_dialog(self.key.item, "Key item", done)

    def _open_item_dialog(self, spec: Optional[ItemSpec], title: str, on_done):
        dialog = ItemDialog(self, spec, title=title)

        def poll():
            if dialog.winfo_exists():
                dialog.after(50, poll)
            else:
                on_done(dialog.result)

        dialog.after(50, poll)

    # ----------------------------------------------------------------- rewards

    def _build_rewards(self):
        frame = self.tab_rewards
        left = ttk.Frame(frame, padding=8)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="Rewards", style="Header.TLabel").pack(anchor="w")
        self.rw_list = tk.Listbox(left, width=32, height=24, exportselection=False)
        self.rw_list.pack(fill="y", expand=True, pady=4)
        self.rw_list.bind("<<ListboxSelect>>", self._rw_select)

        btns = ttk.Frame(left)
        btns.pack(fill="x")
        ttk.Button(btns, text="+ item", width=8,
                   command=lambda: self._rw_add("ITEM")).pack(side="left", padx=1)
        ttk.Button(btns, text="+ command", width=10,
                   command=lambda: self._rw_add("COMMAND")).pack(side="left", padx=1)
        ttk.Button(btns, text="Remove", width=8, command=self._rw_remove).pack(side="left", padx=1)

        rw_scroll = ScrollFrame(frame)
        rw_scroll.pack(side="left", fill="both", expand=True)
        self.rw_form = ttk.Frame(rw_scroll.body, padding=8)
        self.rw_form.pack(fill="both", expand=True)
        self._rw_selected: Optional[int] = None
        self._rw_refresh(select=0 if self.crate.rewards else None)

    def _rw_refresh(self, select: Optional[int] = None):
        self.rw_list.delete(0, "end")
        for reward in self.crate.rewards:
            self.rw_list.insert(
                "end",
                f"{reward.id}   [{reward.type[:4]}] {reward.rarity} · w{reward.weight:g}",
            )
        if select is not None and 0 <= select < len(self.crate.rewards):
            self.rw_list.selection_clear(0, "end")
            self.rw_list.selection_set(select)
            self.rw_list.event_generate("<<ListboxSelect>>")
        elif select is None:
            self._rw_selected = None
            for child in self.rw_form.winfo_children():
                child.destroy()
            ttk.Label(self.rw_form, text="Select or add a reward.",
                      foreground="#555555").pack(anchor="w")

    def _rw_select(self, _event=None):
        selection = self.rw_list.curselection()
        if not selection:
            return
        index = selection[0]
        if index >= len(self.crate.rewards):
            return
        self._rw_selected = index
        for child in self.rw_form.winfo_children():
            child.destroy()
        self._rw_build_form(self.rw_form, self.crate.rewards[index], index)

    def _rw_add(self, rtype: str):
        base = "new_reward" if rtype == "ITEM" else "new_command"
        rid = base
        suffix = 1
        while self.crate.reward_by_id(rid) is not None:
            suffix += 1
            rid = f"{base}_{suffix}"
        reward = Reward(id=rid, type=rtype)
        if rtype == "ITEM":
            reward.items.append(ItemSpec(material="DIAMOND", amount=1, name="&bDiamond"))
        else:
            reward.name = rid.replace("_", " ").title()
            reward.commands.append(f"say {rid}")
        self.crate.rewards.append(reward)
        self._rw_refresh(select=len(self.crate.rewards) - 1)

    def _rw_remove(self):
        selection = self.rw_list.curselection()
        if not selection:
            return
        index = selection[0]
        if index < len(self.crate.rewards):
            del self.crate.rewards[index]
        self._rw_refresh(select=min(index, len(self.crate.rewards) - 1) if self.crate.rewards else None)

    def _rw_build_form(self, parent: ttk.Frame, reward: Reward, index: int):
        parent.columnconfigure(1, weight=1)

        def row(label: str, widget: tk.Widget, r: int):
            ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=2, padx=(0, 8))
            widget.grid(row=r, column=1, sticky="we", pady=2)

        id_var = tk.StringVar(value=reward.id)

        def rename(*_args):
            reward.id = id_var.get().strip()
            current = self.rw_list.get(index) if index < self.rw_list.size() else ""
            if current:
                # keep the list label in sync cheaply
                prefix = current.split("   ")[0]
                if prefix != reward.id:
                    self.rw_list.delete(index)
                    self.rw_list.insert(index, current.replace(prefix, reward.id, 1))

        id_var.trace_add("write", rename)
        row("Reward id", ttk.Entry(parent, textvariable=id_var, width=28), 0)

        ttk.Label(parent, text=f"Type: {reward.type}").grid(
            row=1, column=1, sticky="w", pady=2
        )

        rarity_var = tk.StringVar(value=reward.rarity)
        rarity_var.trace_add("write", lambda *_: setattr(reward, "rarity", rarity_var.get()))
        rarity_box = ttk.Combobox(
            parent, textvariable=rarity_var, values=list(PluginDefaults.DEFAULT_RARITIES),
            width=24,
        )
        row("Rarity", rarity_box, 2)

        weight_var = tk.DoubleVar(value=reward.weight)
        weight_var.trace_add("write", lambda *_: self._set_num(reward, "weight", weight_var))
        row("Weight", ttk.Spinbox(parent, from_=0.01, to=100000, increment=0.5,
                                  textvariable=weight_var, width=10), 3)

        broadcast_var = tk.BooleanVar(value=reward.broadcast)
        broadcast_var.trace_add(
            "write", lambda *_: setattr(reward, "broadcast", broadcast_var.get())
        )
        ttk.Checkbutton(parent, text="Broadcast opening to the whole server",
                        variable=broadcast_var).grid(row=4, column=1, sticky="w", pady=2)

        # preview item
        preview_bar = ttk.Frame(parent)
        row("Preview item", preview_bar, 5)
        preview_label = ttk.Label(preview_bar, text=_item_label(reward.preview))
        preview_label.pack(side="left")
        ttk.Button(
            preview_bar, text="Edit…", width=8,
            command=lambda: self._edit_reward_preview(reward, preview_label),
        ).pack(side="left", padx=4)
        ttk.Button(
            preview_bar, text="Clear", width=6,
            command=lambda: self._clear_reward_preview(reward, preview_label),
        ).pack(side="left")

        if reward.type == "ITEM":
            self._rw_build_item_section(parent, reward, 6)
            next_row = 10
        else:
            self._rw_build_command_section(parent, reward, 6)
            next_row = 11

        self._rw_build_permissions(parent, reward, next_row)

    def _edit_reward_preview(self, reward: Reward, label: ttk.Label):
        def done(result: Optional[ItemSpec]):
            reward.preview = result
            label.configure(text=_item_label(result))

        self._open_item_dialog(reward.preview, "Reward preview item", done)

    def _clear_reward_preview(self, reward: Reward, label: ttk.Label):
        reward.preview = None
        label.configure(text=_item_label(None))

    def _rw_build_item_section(self, parent: ttk.Frame, reward: Reward, r0: int):
        ttk.Label(parent, text="Reward items", style="Header.TLabel").grid(
            row=r0, column=0, columnspan=2, sticky="w", pady=(8, 2)
        )
        box_frame = ttk.Frame(parent)
        box_frame.grid(row=r0 + 1, column=0, columnspan=2, sticky="we")
        box_frame.columnconfigure(0, weight=1)
        items_box = tk.Listbox(box_frame, height=6, exportselection=False)
        items_box.grid(row=0, column=0, sticky="we", padx=(0, 6))
        side = ttk.Frame(box_frame)
        side.grid(row=0, column=1, sticky="n")

        def refresh_items(select: Optional[int] = None):
            items_box.delete(0, "end")
            for spec in reward.items:
                items_box.insert("end", _item_label(spec))
            if select is not None and select < len(reward.items):
                items_box.selection_set(select)

        def add_item():
            def done(result: Optional[ItemSpec]):
                if result is not None:
                    reward.items.append(result)
                    refresh_items(len(reward.items) - 1)

            self._open_item_dialog(None, "Add reward item", done)

        def edit_item():
            selection = items_box.curselection()
            if not selection:
                return
            index = selection[0]

            def done(result: Optional[ItemSpec]):
                if result is not None:
                    reward.items[index] = result
                    refresh_items(index)

            self._open_item_dialog(reward.items[index], "Edit reward item", done)

        def remove_item():
            selection = items_box.curselection()
            if selection and selection[0] < len(reward.items):
                del reward.items[selection[0]]
                refresh_items()

        ttk.Button(side, text="Add", width=7, command=add_item).pack(fill="x", pady=1)
        ttk.Button(side, text="Edit", width=7, command=edit_item).pack(fill="x", pady=1)
        ttk.Button(side, text="Remove", width=7, command=remove_item).pack(fill="x", pady=1)
        refresh_items()

        custom_var = tk.BooleanVar(value=reward.custom_preview)
        custom_var.trace_add(
            "write", lambda *_: setattr(reward, "custom_preview", custom_var.get())
        )
        ttk.Checkbutton(
            parent, text="Use preview item as the reward shown in menus",
            variable=custom_var,
        ).grid(row=r0 + 2, column=1, sticky="w", pady=2)

        ph_var = tk.BooleanVar(value=reward.placeholder_apply)
        ph_var.trace_add(
            "write", lambda *_: setattr(reward, "placeholder_apply", ph_var.get())
        )
        ttk.Checkbutton(
            parent, text="Apply placeholders to the item's name/lore",
            variable=ph_var,
        ).grid(row=r0 + 3, column=1, sticky="w", pady=2)

    def _rw_build_command_section(self, parent: ttk.Frame, reward: Reward, r0: int):
        ttk.Label(parent, text="Command reward", style="Header.TLabel").grid(
            row=r0, column=0, columnspan=2, sticky="w", pady=(8, 2)
        )
        ttk.Label(parent, text="Name").grid(row=r0 + 1, column=0, sticky="w", pady=2)
        name_var = tk.StringVar(value=reward.name)
        name_var.trace_add("write", lambda *_: setattr(reward, "name", name_var.get()))
        ttk.Entry(parent, textvariable=name_var, width=30).grid(
            row=r0 + 1, column=1, sticky="we", pady=2
        )

        ttk.Label(parent, text="Description").grid(row=r0 + 2, column=0, sticky="nw", pady=2)
        desc = ListEditor(parent, width=40, height=3)
        desc.grid(row=r0 + 2, column=1, sticky="we")
        desc.set(reward.description)

        ttk.Label(parent, text="Commands").grid(row=r0 + 3, column=0, sticky="nw", pady=2)
        cmds = ListEditor(
            parent, width=40, height=4, add_placeholder="command without / …"
        )
        cmds.grid(row=r0 + 3, column=1, sticky="we")
        cmds.set(reward.commands)

        desc._on_change = lambda: setattr(reward, "description", desc.get())
        cmds._on_change = lambda: setattr(reward, "commands", cmds.get())

    def _rw_build_permissions(self, parent: ttk.Frame, reward: Reward, r0: int):
        ttk.Label(parent, text="Permissions (optional)", style="Header.TLabel").grid(
            row=r0, column=0, columnspan=2, sticky="w", pady=(10, 2)
        )
        ttk.Label(parent, text="Required").grid(row=r0 + 1, column=0, sticky="nw", pady=2)
        required = ListEditor(parent, width=34, height=2,
                              add_placeholder="permission node…")
        required.grid(row=r0 + 1, column=1, sticky="we")
        required.set(reward.required_permissions)

        ttk.Label(parent, text="Ignored").grid(row=r0 + 2, column=0, sticky="nw", pady=2)
        ignored = ListEditor(parent, width=34, height=2,
                             add_placeholder="permission node…")
        ignored.grid(row=r0 + 2, column=1, sticky="we")
        ignored.set(reward.ignored_permissions)

        required._on_change = lambda: setattr(reward, "required_permissions", required.get())
        ignored._on_change = lambda: setattr(reward, "ignored_permissions", ignored.get())

    @staticmethod
    def _set_num(obj, attr: str, var, cast=float):
        """Numeric StringVar trace sink — tolerant of half-typed values."""
        try:
            setattr(obj, attr, cast(var.get()))
        except Exception:
            pass  # TclError while the user is mid-edit; poll retries

    # ------------------------------------------------------------------- costs

    def _build_costs(self):
        frame = self.tab_costs
        left = ttk.Frame(frame, padding=8)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="Cost options", style="Header.TLabel").pack(anchor="w")
        ttk.Label(left, text="(crate → key link lives here)",
                  foreground="#555555").pack(anchor="w")
        self.cost_list = tk.Listbox(left, width=30, height=18, exportselection=False)
        self.cost_list.pack(fill="y", expand=True, pady=4)
        self.cost_list.bind("<<ListboxSelect>>", self._cost_select)

        btns = ttk.Frame(left)
        btns.pack(fill="x")
        ttk.Button(btns, text="+ key", width=7,
                   command=lambda: self._cost_add("key")).pack(side="left", padx=1)
        ttk.Button(btns, text="+ money", width=8,
                   command=lambda: self._cost_add("currency")).pack(side="left", padx=1)
        ttk.Button(btns, text="Remove", width=8, command=self._cost_remove).pack(
            side="left", padx=1
        )

        cost_scroll = ScrollFrame(frame)
        cost_scroll.pack(side="left", fill="both", expand=True)
        self.cost_form = ttk.Frame(cost_scroll.body, padding=8)
        self.cost_form.pack(fill="both", expand=True)
        self._cost_selected: Optional[int] = None
        self._cost_refresh(select=0 if self.crate.costs else None)

    def _cost_refresh(self, select: Optional[int] = None):
        self.cost_list.delete(0, "end")
        for cost in self.crate.costs:
            kinds = ",".join(e.type[:1] for e in cost.entries) or "-"
            self.cost_list.insert("end", f"{cost.id}  ({len(cost.entries)}× {kinds})")
        if select is not None and 0 <= select < len(self.crate.costs):
            self.cost_list.selection_clear(0, "end")
            self.cost_list.selection_set(select)
            self.cost_list.event_generate("<<ListboxSelect>>")
        else:
            self._cost_selected = None
            for child in self.cost_form.winfo_children():
                child.destroy()
            ttk.Label(self.cost_form, text="Select or add a cost option.",
                      foreground="#555555").pack(anchor="w")

    def _cost_select(self, _event=None):
        selection = self.cost_list.curselection()
        if not selection or selection[0] >= len(self.crate.costs):
            return
        index = selection[0]
        self._cost_selected = index
        for child in self.cost_form.winfo_children():
            child.destroy()
        self._cost_build_form(self.cost_form, self.crate.costs[index], index)

    def _cost_add(self, entry_type: str):
        if entry_type == "key":
            cost_id = f"key_{self.key.id}"
            entry = CostEntry(type="key", key_id=self.key.id, amount=1)
        else:
            cost_id = "eco_vault"
            entry = CostEntry(type="currency", currency="vault", amount=100.0)
        if any(c.id == cost_id for c in self.crate.costs):
            cost_id = f"{cost_id}_2"
        cost = CostOption(id=cost_id, enabled=True, name=cost_id.replace("_", " ").title())
        cost.entries.append(entry)
        self.crate.costs.append(cost)
        self._cost_refresh(select=len(self.crate.costs) - 1)

    def _cost_remove(self):
        selection = self.cost_list.curselection()
        if not selection:
            return
        index = selection[0]
        if index < len(self.crate.costs):
            del self.crate.costs[index]
        self._cost_refresh(
            select=min(index, len(self.crate.costs) - 1) if self.crate.costs else None
        )

    def _cost_build_form(self, parent: ttk.Frame, cost: CostOption, index: int):
        parent.columnconfigure(1, weight=1)

        def row(label, widget, r):
            ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=2, padx=(0, 8))
            widget.grid(row=r, column=1, sticky="we", pady=2)

        id_var = tk.StringVar(value=cost.id)
        id_var.trace_add("write", lambda *_: setattr(cost, "id", id_var.get().strip()))
        row("Cost id", ttk.Entry(parent, textvariable=id_var, width=26), 0)

        name_var = tk.StringVar(value=cost.name)
        name_var.trace_add("write", lambda *_: setattr(cost, "name", name_var.get()))
        row("Menu name", ttk.Entry(parent, textvariable=name_var, width=30), 1)

        enabled_var = tk.BooleanVar(value=cost.enabled)
        enabled_var.trace_add("write", lambda *_: setattr(cost, "enabled", enabled_var.get()))
        ttk.Checkbutton(parent, text="Enabled", variable=enabled_var).grid(
            row=2, column=1, sticky="w", pady=2
        )

        icon_bar = ttk.Frame(parent)
        row("Icon", icon_bar, 3)
        icon_label = ttk.Label(icon_bar, text=_item_label(cost.icon))
        icon_label.pack(side="left")

        def edit_icon(result: Optional[ItemSpec]):
            if result is not None:
                cost.icon = result
                icon_label.configure(text=_item_label(result))

        ttk.Button(icon_bar, text="Edit…", width=8,
                   command=lambda: self._open_item_dialog(cost.icon, "Cost icon", edit_icon)
                   ).pack(side="left", padx=4)

        ttk.Label(parent, text="Entries", style="Header.TLabel").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(10, 2)
        )
        entries_box = tk.Listbox(parent, height=5, exportselection=False)
        entries_box.grid(row=5, column=0, columnspan=2, sticky="we")

        def refresh_entries(select: Optional[int] = None):
            entries_box.delete(0, "end")
            for entry in cost.entries:
                if entry.type == "key":
                    text = f"key  {entry.key_id}  x{entry.amount:g}"
                elif entry.type == "currency":
                    text = f"currency  {entry.currency}  {entry.amount:g}"
                else:
                    text = f"{entry.type}  {entry.amount:g}"
                entries_box.insert("end", text)
            if select is not None and select < len(cost.entries):
                entries_box.selection_set(select)

        form = ttk.Frame(parent)
        form.grid(row=6, column=0, columnspan=2, sticky="we", pady=4)
        form.columnconfigure(2, weight=1)

        type_var = tk.StringVar(value="key")
        type_box = ttk.Combobox(form, textvariable=type_var, values=["key", "currency"],
                                state="readonly", width=9)
        type_box.grid(row=0, column=0, padx=(0, 4))
        target_var = tk.StringVar(value=self.key.id)
        target_entry = ttk.Entry(form, textvariable=target_var, width=20)
        target_entry.grid(row=0, column=1, padx=(0, 4))
        amount_var = tk.DoubleVar(value=1.0)
        ttk.Spinbox(form, from_=0.0, to=1000000, increment=1, textvariable=amount_var,
                    width=9).grid(row=0, column=2, sticky="w")

        def sync_type_label(*_a):
            target_label.configure(
                text="key id:" if type_var.get() == "key" else "currency id:"
            )

        type_var.trace_add("write", sync_type_label)
        target_label = ttk.Label(form, text="key id:")
        target_label.grid(row=1, column=0, columnspan=2, sticky="w")
        sync_type_label()

        def current_entry() -> Optional[CostEntry]:
            selection = entries_box.curselection()
            if selection and selection[0] < len(cost.entries):
                return cost.entries[selection[0]]
            return None

        def entry_from_form(entry: CostEntry):
            entry.type = type_var.get()
            if entry.type == "key":
                entry.key_id = target_var.get().strip()
            else:
                entry.currency = target_var.get().strip()
            try:
                entry.amount = float(amount_var.get())
            except (ValueError, tk.TclError):
                pass

        def load_into_form(entry: CostEntry):
            type_var.set(entry.type if entry.type in ("key", "currency") else "key")
            target_var.set(entry.key_id if entry.type == "key" else entry.currency)
            amount_var.set(entry.amount)

        def add_entry():
            entry = CostEntry(type="key")
            entry_from_form(entry)
            cost.entries.append(entry)
            refresh_entries(len(cost.entries) - 1)

        def update_entry():
            entry = current_entry()
            if entry:
                entry_from_form(entry)
                refresh_entries(cost.entries.index(entry))

        def remove_entry():
            entry = current_entry()
            if entry is not None:
                cost.entries.remove(entry)
                refresh_entries()

        def on_select(_event):
            entry = current_entry()
            if entry:
                load_into_form(entry)

        entries_box.bind("<<ListboxSelect>>", on_select)

        bar = ttk.Frame(form)
        bar.grid(row=0, column=3, rowspan=2, padx=(8, 0), sticky="n")
        ttk.Button(bar, text="Add", width=7, command=add_entry).pack(fill="x", pady=1)
        ttk.Button(bar, text="Update", width=7, command=update_entry).pack(fill="x", pady=1)
        ttk.Button(bar, text="Delete", width=7, command=remove_entry).pack(fill="x", pady=1)

        ttk.Label(
            parent,
            text="Tip: a key entry is the crate→key link. Ids should match "
                 "key_<key id> / eco_<currency> by convention.",
            foreground="#555555",
            wraplength=420,
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(6, 0))

        refresh_entries(0 if cost.entries else None)

    # ------------------------------------------------------------- world tab

    def _build_world(self):
        scroll = ScrollFrame(self.tab_world)
        scroll.pack(fill="both", expand=True)
        body = ttk.Frame(scroll.body, padding=10)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        def row(r, label, widget, hint: str = "") -> int:
            """Label + widget in two columns; hint sits under the widget."""
            ttk.Label(body, text=label).grid(row=r, column=0, sticky="nw", pady=2, padx=(0, 8))
            widget.grid(row=r, column=1, sticky="we", pady=2)
            if hint:
                ttk.Label(body, text=hint, foreground="#555555").grid(
                    row=r + 1, column=1, sticky="w", pady=(0, 4)
                )
                return r + 2
            return r + 1

        def header(r, text) -> int:
            ttk.Label(body, text=text, style="Header.TLabel").grid(
                row=r, column=0, columnspan=2, sticky="w", pady=(4, 2)
            )
            return r + 1

        def sep(r) -> int:
            ttk.Separator(body, orient="horizontal").grid(
                row=r, column=0, columnspan=2, sticky="we", pady=8
            )
            return r + 1

        r = 0
        r = header(r, "Placed crate block")
        ttk.Label(body, text="Positions").grid(row=r, column=0, sticky="nw", pady=2, padx=(0, 8))
        positions = ListEditor(body, width=40, height=4, add_placeholder="x,y,z,world")
        positions.grid(row=r, column=1, sticky="we")
        positions.set(self.crate.positions)
        positions._on_change = lambda: setattr(self.crate, "positions", positions.get())
        r += 1
        ttk.Label(
            body,
            text="Format: x,y,z,world — the world name must match the server exactly.",
            foreground="#555555",
        ).grid(row=r, column=1, sticky="w", pady=(0, 4))
        r += 1

        push_var = tk.BooleanVar(value=self.crate.pushback_enabled)
        push_var.trace_add(
            "write", lambda *_: setattr(self.crate, "pushback_enabled", push_var.get())
        )
        ttk.Checkbutton(body, text="Push players back after opening",
                        variable=push_var).grid(row=r, column=1, sticky="w", pady=2)
        r += 1

        r = sep(r)
        r = header(r, "Hologram above the crate")
        holo_var = tk.BooleanVar(value=self.crate.hologram_enabled)
        holo_var.trace_add(
            "write", lambda *_: setattr(self.crate, "hologram_enabled", holo_var.get())
        )
        ttk.Checkbutton(body, text="Enabled", variable=holo_var).grid(
            row=r, column=1, sticky="w", pady=2
        )
        r += 1
        template_var = tk.StringVar(value=self.crate.hologram_template)
        template_var.trace_add(
            "write", lambda *_: setattr(self.crate, "hologram_template", template_var.get())
        )
        r = row(r, "Template", ttk.Entry(body, textvariable=template_var, width=28),
                "Hologram template id from the plugin's config.yml (default)")
        y_var = tk.DoubleVar(value=self.crate.hologram_y_offset)
        y_var.trace_add(
            "write", lambda *_: self._set_num(self.crate, "hologram_y_offset", y_var)
        )
        r = row(r, "Y offset",
                ttk.Spinbox(body, from_=-5.0, to=5.0, increment=0.1,
                            textvariable=y_var, width=8))

        r = sep(r)
        r = header(r, "Particle effect")
        eff_var = tk.BooleanVar(value=self.crate.effect_enabled)
        eff_var.trace_add(
            "write", lambda *_: setattr(self.crate, "effect_enabled", eff_var.get())
        )
        ttk.Checkbutton(body, text="Enabled", variable=eff_var).grid(
            row=r, column=1, sticky="w", pady=2
        )
        r += 1
        model_var = tk.StringVar(value=self.crate.effect_model)
        model_var.trace_add(
            "write", lambda *_: setattr(self.crate, "effect_model", model_var.get()))
        r = row(r, "Model",
                ttk.Combobox(body, textvariable=model_var,
                             values=list(PluginDefaults.EFFECT_MODELS),
                             state="readonly", width=16))

        particle = self.crate.particle
        name_var = tk.StringVar(value=particle.name)
        name_var.trace_add("write", lambda *_: setattr(particle, "name", name_var.get()))
        r = row(r, "Particle",
                ttk.Combobox(body, textvariable=name_var,
                             values=["CLOUD", "DUST", "FLAME", "HEART",
                                     "HAPPY_VILLAGER", "SNOWFLAKE", "EFFECT"],
                             width=20),
                "Bukkit Particle enum name (1.21+: DUST, not REDSTONE)")
        color_var = tk.StringVar(value=particle.color)
        color_var.trace_add("write", lambda *_: setattr(particle, "color", color_var.get()))
        r = row(r, "Color", ttk.Entry(body, textvariable=color_var, width=16),
                "Red,Green,Blue 0-255 (DUST particles)")
        size_var = tk.DoubleVar(value=particle.size)
        size_var.trace_add(
            "write", lambda *_: self._set_num(particle, "size", size_var))
        r = row(r, "Size",
                ttk.Spinbox(body, from_=0.0, to=10.0, increment=0.1,
                            textvariable=size_var, width=8),
                "DUST particles only")
        material_var = tk.StringVar(value=particle.material)
        material_var.trace_add(
            "write", lambda *_: setattr(particle, "material", material_var.get()))
        r = row(r, "Block material", ttk.Entry(body, textvariable=material_var, width=20),
                "For BLOCK / BLOCK_CRUMBLE style particles")

    # ------------------------------------------------------------ advanced tab

    def _build_advanced(self):
        scroll = ScrollFrame(self.tab_advanced)
        scroll.pack(fill="both", expand=True)
        body = ttk.Frame(scroll.body, padding=10)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        def row(r, label, widget, hint: str = "") -> int:
            ttk.Label(body, text=label).grid(row=r, column=0, sticky="w", pady=2, padx=(0, 8))
            widget.grid(row=r, column=1, sticky="we", pady=2)
            if hint:
                ttk.Label(body, text=hint, foreground="#555555").grid(
                    row=r + 1, column=1, sticky="w", pady=(0, 4)
                )
                return r + 2
            return r + 1

        def header(r, text) -> int:
            ttk.Label(body, text=text, style="Header.TLabel").grid(
                row=r, column=0, columnspan=2, sticky="w", pady=(4, 2)
            )
            return r + 1

        def sep(r) -> int:
            ttk.Separator(body, orient="horizontal").grid(
                row=r, column=0, columnspan=2, sticky="we", pady=8
            )
            return r + 1

        def check(r, text, variable) -> int:
            ttk.Checkbutton(body, text=text, variable=variable).grid(
                row=r, column=1, sticky="w", pady=2
            )
            return r + 1

        r = 0
        r = header(r, "Menus & timing")
        prev_var = tk.BooleanVar(value=self.crate.preview_enabled)
        prev_var.trace_add(
            "write", lambda *_: setattr(self.crate, "preview_enabled", prev_var.get()))
        r = check(r, "Preview menu enabled", prev_var)
        prev_id = tk.StringVar(value=self.crate.preview_id)
        prev_id.trace_add("write", lambda *_: setattr(self.crate, "preview_id", prev_id.get()))
        r = row(r, "Preview menu id", ttk.Entry(body, textvariable=prev_id, width=20),
                "usually 'default'")

        anim_var = tk.BooleanVar(value=self.crate.animation_enabled)
        anim_var.trace_add(
            "write", lambda *_: setattr(self.crate, "animation_enabled", anim_var.get()))
        r = check(r, "Opening animation (GUI) enabled", anim_var)
        anim_id = tk.StringVar(value=self.crate.animation_id)
        anim_id.trace_add("write", lambda *_: setattr(self.crate, "animation_id", anim_id.get()))
        r = row(r, "Animation id",
                ttk.Combobox(body, textvariable=anim_id,
                             values=list(PluginDefaults.OPENING_IDS),
                             width=18),
                "valid on a fresh server: " + ", ".join(PluginDefaults.OPENING_IDS))

        cool_var = tk.BooleanVar(value=self.crate.cooldown_enabled)
        cool_var.trace_add(
            "write", lambda *_: setattr(self.crate, "cooldown_enabled", cool_var.get()))
        r = check(r, "Opening cooldown enabled", cool_var)
        cool_val = tk.IntVar(value=self.crate.cooldown_value)
        cool_val.trace_add(
            "write", lambda *_: self._set_num(self.crate, "cooldown_value",
                                              cool_val, int))
        r = row(r, "Cooldown",
                ttk.Spinbox(body, from_=-1, to=86400, textvariable=cool_val, width=10),
                "seconds; -1 = once per player")

        amount_var = tk.IntVar(value=self.crate.opening_limit_amount)
        amount_var.trace_add(
            "write", lambda *_: self._set_num(self.crate, "opening_limit_amount",
                                              amount_var, int))
        r = row(r, "Openings per use",
                ttk.Spinbox(body, from_=1, to=64, textvariable=amount_var, width=8),
                "keys consumed / rolls per open (min 1)")

        r = sep(r)
        r = header(r, "Post-open commands")
        ttk.Label(body, text="Commands").grid(row=r, column=0, sticky="nw", pady=2, padx=(0, 8))
        cmds = ListEditor(body, width=44, height=3, add_placeholder="command without / …")
        cmds.grid(row=r, column=1, sticky="we")
        cmds.set(self.crate.post_open_commands)
        cmds._on_change = lambda: setattr(self.crate, "post_open_commands", cmds.get())
        r += 1

        r = sep(r)
        r = header(r, "Milestones (optional)")
        repeat_var = tk.BooleanVar(value=self.crate.milestones_repeatable)
        repeat_var.trace_add(
            "write", lambda *_: setattr(self.crate, "milestones_repeatable", repeat_var.get()))
        r = check(r, "Repeatable milestones", repeat_var)

        ms_box = tk.Listbox(body, height=4, exportselection=False)
        ms_box.grid(row=r, column=1, sticky="we")
        r += 1

        def refresh_ms(select: Optional[int] = None):
            ms_box.delete(0, "end")
            for milestone in self.crate.milestones:
                ms_box.insert(
                    "end", f"every {milestone.openings} openings → {milestone.reward_id}"
                )
            if select is not None and select < len(self.crate.milestones):
                ms_box.selection_set(select)

        ms_form = ttk.Frame(body)
        ms_form.grid(row=r, column=1, sticky="we", pady=2)
        r += 1
        reward_ids = [reward.id for reward in self.crate.rewards]
        self.ms_reward_box = ttk.Combobox(ms_form, values=reward_ids, width=22)
        if reward_ids:
            self.ms_reward_box.set(reward_ids[0])
        self.ms_reward_box.grid(row=0, column=0, padx=(0, 4))
        openings_var = tk.IntVar(value=10)
        ttk.Spinbox(ms_form, from_=1, to=1000000, textvariable=openings_var,
                    width=8).grid(row=0, column=1, padx=(0, 4))

        def ms_add():
            reward_id = self.ms_reward_box.get().strip() or (reward_ids[0] if reward_ids else "")
            if not reward_id:
                return
            try:
                openings = max(1, int(openings_var.get()))
            except (ValueError, tk.TclError):
                openings = 1
            self.crate.milestones.append(Milestone(reward_id=reward_id, openings=openings))
            refresh_ms(len(self.crate.milestones) - 1)

        def ms_remove():
            selection = ms_box.curselection()
            if selection and selection[0] < len(self.crate.milestones):
                del self.crate.milestones[selection[0]]
                refresh_ms()

        ttk.Button(ms_form, text="Add", width=6, command=ms_add).grid(row=0, column=2, padx=2)
        ttk.Button(ms_form, text="Remove", width=7, command=ms_remove).grid(row=0, column=3)

        ttk.Label(
            body,
            text="Requires Milestones.Enabled: true in the plugin's config.yml.",
            foreground="#555555",
        ).grid(row=r, column=1, sticky="w", pady=(2, 0))
        refresh_ms()

    # ----------------------------------------------------------- preview loop

    def _problems(self) -> list[Problem]:
        return validate_crate(self.crate, self.key) + validate_key(self.key)

    def _tick(self):
        problems = self._problems()
        self._problems_cache = problems
        self._update_validation(problems)

        try:
            text = generate_crate(self.crate) + "\n" + "=" * 40 + "\n" + generate_key(self.key)
        except RuntimeError as exc:
            text = f"# REFUSING TO WRITE: {exc}"
        if text != self._last_preview:
            self._last_preview = text
            self.preview.configure(state="normal")
            self.preview.delete("1.0", "end")
            self.preview.insert("1.0", text)
            self.preview.configure(state="disabled")

        errors = sum(1 for p in problems if p.level == "error")
        warnings = sum(1 for p in problems if p.level == "warning")
        base = f"{errors} error(s), {warnings} warning(s)"
        if self.import_warnings:
            base += f" · {len(self.import_warnings)} import note(s)"
        self.status_var.set(base)
        if self.ms_reward_box is not None:
            try:
                self.ms_reward_box.configure(values=[r.id for r in self.crate.rewards])
            except tk.TclError:
                pass
        self.after(_PREVIEW_MS, self._tick)

    def _update_validation(self, problems: list[Problem]):
        self.valid_tree.delete(*self.valid_tree.get_children())
        rows = list(problems) + [
            Problem("info", "import", w) for w in self.import_warnings
        ]
        for problem in rows:
            self.valid_tree.insert(
                "", "end",
                tags=(_LEVEL_TAG.get(problem.level, "info"),),
                values=(problem.level.upper(), problem.path, problem.message),
            )

    def _on_problem_double_click(self, _event):
        selection = self.valid_tree.selection()
        if not selection:
            return
        values = self.valid_tree.item(selection[0], "values")
        path = str(values[1]) if values else ""
        if path.startswith("Rewards.List"):
            reward_id = path.split(".")[2] if path.count(".") >= 2 else None
            if reward_id:
                for index, reward in enumerate(self.crate.rewards):
                    if reward.id == reward_id:
                        self.notebook.select(self.tab_rewards)
                        self.rw_list.selection_clear(0, "end")
                        self.rw_list.selection_set(index)
                        self._rw_select()
                        return
        if path.startswith("CostOptions") and "." in path:
            cost_id = path.split(".")[1]
            for index, cost in enumerate(self.crate.costs):
                if cost.id == cost_id:
                    self.notebook.select(self.tab_costs)
                    self.cost_list.selection_clear(0, "end")
                    self.cost_list.selection_set(index)
                    self._cost_select()
                    return

    # ------------------------------------------------------------------ files

    def new_crate(self):
        self.crate = CrateConfig(item=default_crate_item("My Crate"))
        self.crate.rewards.append(_example_reward())
        self.import_warnings = []
        self.rebuild_tabs()
        self.status_var.set("New crate created.")

    def new_key(self):
        self.key = KeyConfig(item=default_key_item("My Key"))
        self.import_warnings = []
        self.rebuild_tabs()
        self.status_var.set("New key created.")

    def open_crate(self):
        path = filedialog.askopenfilename(
            title="Open crate file",
            filetypes=[("YAML", "*.yml"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            result = load_crate(Path(path).read_text(encoding="utf-8"))
        except (OSError, LoadError) as exc:
            messagebox.showerror("Cannot open crate", str(exc), parent=self)
            return
        self.crate = result.config
        self.crate_id_var.set(self.crate.id)
        self.import_warnings = result.warnings
        self.rebuild_tabs()
        self.status_var.set(f"Loaded {path}")

    def open_key(self):
        path = filedialog.askopenfilename(
            title="Open key file",
            filetypes=[("YAML", "*.yml"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            result = load_key(Path(path).read_text(encoding="utf-8"))
        except (OSError, LoadError) as exc:
            messagebox.showerror("Cannot open key", str(exc), parent=self)
            return
        self.key = result.config
        self.key_id_var.set(self.key.id)
        self.import_warnings = result.warnings
        self.rebuild_tabs()
        self.status_var.set(f"Loaded {path}")

    def save_both(self):
        problems = self._problems()
        if has_errors(problems):
            first = [p for p in problems if p.level == "error"][:6]
            listing = "\n".join(f"• {p.path}: {p.message}" for p in first)
            messagebox.showerror(
                "Not saving — validation errors",
                "Fix these first:\n\n" + listing,
                parent=self,
            )
            return
        if not is_var_style(self.crate.id):
            messagebox.showerror(
                "Invalid crate id",
                "Crate id must match [a-z0-9_-] style (lowercase) — it becomes "
                "the file name.",
                parent=self,
            )
            return
        if not is_var_style(self.key.id):
            messagebox.showerror(
                "Invalid key id",
                "Key id must match [a-z0-9_-] style (lowercase).",
                parent=self,
            )
            return

        if self.last_crates and not Path(self.last_crates).is_dir():
            self.last_crates = ""
        if self.last_keys and not Path(self.last_keys).is_dir():
            self.last_keys = ""
        crates_dir = self.last_crates or filedialog.askdirectory(
            title="Select the plugin's crates/ folder"
        )
        if not crates_dir:
            return
        keys_dir = self.last_keys or filedialog.askdirectory(
            title="Select the plugin's keys/ folder"
        )
        if not keys_dir:
            return

        try:
            crate_text = generate_crate(self.crate)
            key_text = generate_key(self.key)
        except RuntimeError as exc:
            messagebox.showerror("Refusing to write", str(exc), parent=self)
            return

        try:
            crate_path = Path(crates_dir) / f"{self.crate.id}.yml"
            key_path = Path(keys_dir) / f"{self.key.id}.yml"
            crate_path.write_text(crate_text, encoding="utf-8")
            key_path.write_text(key_text, encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Write failed", str(exc), parent=self)
            return

        self.last_crates, self.last_keys = crates_dir, keys_dir
        self._save_state()
        self.status_var.set(f"Saved {crate_path} and {key_path}")
        messagebox.showinfo(
            "Saved",
            f"Wrote:\n  {crate_path}\n  {key_path}\n\n"
            "Drop them into plugins/ExcellentCrates/crates/ and .../keys/.",
            parent=self,
        )

    # ------------------------------------------------------------------ state

    def _load_state(self):
        try:
            data = json.loads(_STATE_FILE.read_text())
            self.last_crates = str(data.get("crates", ""))
            self.last_keys = str(data.get("keys", ""))
            geometry = str(data.get("geometry", ""))
            if geometry:
                self.geometry(geometry)
        except (OSError, ValueError):
            pass

    def _save_state(self):
        try:
            geometry = ""
            try:
                geometry = self.geometry()
            except tk.TclError:
                pass
            _STATE_FILE.write_text(
                json.dumps({
                    "crates": self.last_crates,
                    "keys": self.last_keys,
                    "geometry": geometry,
                })
            )
        except OSError:
            pass

    def _quit(self):
        self._save_state()
        self.destroy()

    def _about(self):
        messagebox.showinfo(
            "About",
            "ExcellentCrates Config Studio\n\n"
            "Generates crates/<id>.yml and keys/<id>.yml for the "
            "ExcellentCrates Spigot plugin.\n"
            "Validation mirrors the plugin's problem checks; comments in the "
            "output are ignored by Bukkit YAML.",
            parent=self,
        )

    def _where(self):
        messagebox.showinfo(
            "Where do files go?",
            "crates/<crate id>.yml  →  plugins/ExcellentCrates/crates/\n"
            "keys/<key id>.yml      →  plugins/ExcellentCrates/keys/\n\n"
            "Restart the server (or use /crates reload) after copying.",
            parent=self,
        )


def main() -> None:
    app = Studio()
    app.mainloop()
