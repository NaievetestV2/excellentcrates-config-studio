"""Reusable Tkinter widgets for ExcellentCrates Config Studio."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

from .model import ItemSpec
from .validator import MATERIALS

__all__ = ["ListEditor", "ItemDialog", "edit_item", "ScrollFrame"]


class ScrollFrame(ttk.Frame):
    """Vertically scrollable container; build widgets into ``self.body``."""

    def __init__(self, master: tk.Misc, height: int = 0):
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0, height=height)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas)
        self.body.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.bind(
            "<Configure>",
            lambda _e: self.canvas.itemconfigure(self._window, width=self.canvas.winfo_width()),
        )
        self.body.bind(
            "<Enter>",
            lambda _e: self._bind_wheel(True),
        )
        self.body.bind(
            "<Leave>",
            lambda _e: self._bind_wheel(False),
        )

    def _bind_wheel(self, on: bool):
        sequence = "<MouseWheel>" if self.tk.call("tk", "windowingsystem") == "win32" else "<Button-4>"
        sequences = ("<MouseWheel>", "<Button-4>", "<Button-5>")
        for seq in sequences:
            if on:
                self.canvas.bind_all(seq, self._on_wheel, add="+")
            else:
                try:
                    self.canvas.unbind_all(seq)
                except tk.TclError:
                    pass

    def _on_wheel(self, event):
        if self.tk.call("tk", "windowingsystem") == "win32":
            delta = -1 if event.delta > 0 else 1
        else:
            delta = -1 if event.num == 4 else 1
        self.canvas.yview_scroll(delta, "units")


class ListEditor(ttk.Frame):
    """Entry + listbox for a list[str] field (description, lore, commands...)."""

    def __init__(
        self,
        master: tk.Misc,
        title: str = "",
        add_placeholder: str = "Add value…",
        width: int = 44,
        height: int = 6,
        on_change: Optional[Callable[[], None]] = None,
    ):
        super().__init__(master)
        self._on_change = on_change
        if title:
            ttk.Label(self, text=title).grid(row=0, column=0, columnspan=5, sticky="w")
        self.listbox = tk.Listbox(self, height=height, width=width, exportselection=False)
        self.listbox.grid(row=1, column=0, columnspan=5, sticky="nsew", pady=2)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.listbox.yview)
        scroll.grid(row=1, column=5, sticky="ns")
        self.listbox.configure(yscrollcommand=scroll.set)

        self.entry = ttk.Entry(self, width=width)
        self.entry.grid(row=2, column=0, columnspan=3, sticky="we", pady=2)
        self.entry.bind("<Return>", lambda _e: self.add())
        ttk.Button(self, text="Add", width=6, command=self.add).grid(
            row=2, column=3, padx=(4, 0)
        )
        ttk.Button(self, text="Remove", width=8, command=self.remove).grid(
            row=2, column=4, padx=(4, 0)
        )
        btns = ttk.Frame(self)
        btns.grid(row=3, column=0, columnspan=5, sticky="w")
        ttk.Button(btns, text="Up", width=4, command=lambda: self.move(-1)).pack(
            side="left", padx=(0, 4)
        )
        ttk.Button(btns, text="Down", width=5, command=lambda: self.move(1)).pack(
            side="left"
        )
        self._placeholder = add_placeholder
        self.entry.insert(0, add_placeholder)
        self.entry.bind("<FocusIn>", self._clear_placeholder)
        self.columnconfigure(0, weight=1)

    def _clear_placeholder(self, _event=None):
        if self.entry.get() == self._placeholder:
            self.entry.delete(0, "end")

    def add(self):
        value = self.entry.get().strip()
        if not value or value == self._placeholder:
            return
        self.listbox.insert("end", value)
        self.entry.delete(0, "end")
        self._changed()

    def remove(self):
        selection = self.listbox.curselection()
        if selection:
            self.listbox.delete(selection[0])
            self._changed()

    def move(self, delta: int):
        selection = self.listbox.curselection()
        if not selection:
            return
        index = selection[0]
        new = index + delta
        if new < 0 or new >= self.listbox.size():
            return
        text = self.listbox.get(index)
        self.listbox.delete(index)
        self.listbox.insert(new, text)
        self.listbox.selection_set(new)
        self._changed()

    def _changed(self):
        if self._on_change:
            self._on_change()

    def get(self) -> list[str]:
        return list(self.listbox.get(0, "end"))

    def set(self, values: list[str]) -> None:
        self.listbox.delete(0, "end")
        for value in values:
            self.listbox.insert("end", value)


class ItemDialog(tk.Toplevel):
    """Modal editor for one ItemSpec. Returns a fresh spec (raw_value cleared)."""

    def __init__(
        self,
        master: tk.Misc,
        spec: Optional[ItemSpec],
        title: str = "Edit item",
        on_change: Optional[Callable[[], None]] = None,
    ):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.result: Optional[ItemSpec] = None
        self._on_change = on_change

        source = spec or ItemSpec()
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        self.provider = tk.StringVar(value=source.provider)
        self.material = tk.StringVar(value=source.material if source.is_vanilla() else "")
        self.custom_id = tk.StringVar(value=source.custom_id)
        self.amount = tk.IntVar(value=max(1, source.amount))
        self.name = tk.StringVar(value=source.name)
        self.texture = tk.StringVar(value=source.texture)

        ttk.Label(body, text="Provider").grid(row=0, column=0, sticky="w", pady=2)
        provider_box = ttk.Combobox(
            body, textvariable=self.provider, values=["vanilla", "nexo", "oraxen"],
            state="readonly", width=22,
        )
        provider_box.grid(row=0, column=1, sticky="we", pady=2)
        provider_box.bind("<<ComboboxSelected>>", lambda _e: self._provider_changed())

        ttk.Label(body, text="Material").grid(row=1, column=0, sticky="w", pady=2)
        self.material_box = ttk.Combobox(body, textvariable=self.material, width=22)
        self.material_box.grid(row=1, column=1, sticky="we", pady=2)
        self._material_values_set = False

        ttk.Label(body, text="Custom item id").grid(row=2, column=0, sticky="w", pady=2)
        ttk.Entry(body, textvariable=self.custom_id, width=24).grid(
            row=2, column=1, sticky="we", pady=2
        )

        ttk.Label(body, text="Amount").grid(row=3, column=0, sticky="w", pady=2)
        ttk.Spinbox(body, from_=1, to=64, textvariable=self.amount, width=6).grid(
            row=3, column=1, sticky="w", pady=2
        )

        ttk.Label(body, text="Display name").grid(row=4, column=0, sticky="nw", pady=2)
        ttk.Entry(body, textvariable=self.name, width=40).grid(
            row=4, column=1, sticky="we", pady=2
        )
        ttk.Label(body, text="('&' color codes; '&#RRGGBB' hex allowed)").grid(
            row=5, column=1, sticky="w"
        )

        ttk.Label(body, text="Head texture").grid(row=6, column=0, sticky="nw", pady=2)
        ttk.Entry(body, textvariable=self.texture, width=40).grid(
            row=6, column=1, sticky="we", pady=2
        )
        ttk.Label(body, text="(base64 textures value, PLAYER_HEAD only)").grid(
            row=7, column=1, sticky="w"
        )

        if source.raw_value and source.is_vanilla():
            ttk.Label(
                body,
                text="Note: this item carries NBT this editor does not model.\n"
                "Saving without edits keeps it byte-for-byte; editing rebuilds it.",
                foreground="#8a6d00",
            ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))

        buttons = ttk.Frame(body)
        buttons.grid(row=9, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="left", padx=4)
        ttk.Button(buttons, text="OK", command=self._ok).pack(side="left")

        self._provider_changed()
        self.grab_set()
        self.bind("<Escape>", lambda _e: self.destroy())

    def _provider_changed(self):
        custom = self.provider.get() != "vanilla"
        state = "disabled" if custom else "normal"
        try:
            self.material_box.configure(state=state)
        except tk.TclError:
            pass
        if custom and not self._material_values_set:
            pass

    def _ok(self):
        provider = self.provider.get() or "vanilla"
        spec = ItemSpec(provider=provider)
        if provider == "vanilla":
            material = (self.material.get() or "CHEST").upper()
            if material not in MATERIALS and MATERIALS:
                if not messagebox.askyesno(
                    "Unknown material",
                    f"'{material}' is not a Bukkit Material name in 1.21.10.\n"
                    "Save it anyway?",
                    parent=self,
                ):
                    return
            spec.material = material
        else:
            spec.custom_id = self.custom_id.get().strip()
        try:
            spec.amount = max(1, int(self.amount.get()))
        except (ValueError, tk.TclError):
            spec.amount = 1
        spec.name = self.name.get()
        spec.texture = self.texture.get().strip()
        spec.raw_value = None  # edited -> rebuild
        spec.raw_data_version = None
        self.result = spec
        if self._on_change:
            self._on_change()
        self.destroy()


def edit_item(
    master: tk.Misc,
    spec: Optional[ItemSpec],
    title: str = "Edit item",
    on_done: Optional[Callable[[Optional[ItemSpec]], None]] = None,
) -> None:
    """Open the modal item editor; ``on_done(spec)`` fires with None on cancel."""

    def _opened():
        dialog = ItemDialog(master, spec, title=title)

        def _poll():
            if dialog.winfo_exists():
                dialog.after(50, _poll)
            elif on_done:
                on_done(dialog.result)

        dialog.after(50, _poll)

    _opened()
