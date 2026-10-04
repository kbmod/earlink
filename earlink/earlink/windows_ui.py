"""Windows desktop UI; Tk ships with the standard Windows Python installer."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from . import protocol, windows
from .catalog import looks_like_earbud, match_model
from .session import Snapshot, open_session


class EarWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Ear Link")
        root.geometry("780x720")
        root.minsize(650, 580)
        self.session = None
        self.model = None
        self.found = []
        self.busy = False
        self.closed = threading.Event()
        self.jobs = queue.Queue()
        self.results = queue.Queue()
        self.controls = []
        self.eq_choices = protocol.EQ_PRESETS
        self.status = tk.StringVar(value="Put the buds in pairing mode, pair in Windows Settings, then choose Scan.")
        self.show_all = tk.BooleanVar(value=False)
        self.title = tk.StringVar(value="Choose your earbuds")
        self.details = tk.StringVar(value="")
        frame = ttk.Frame(root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Ear Link", font=("Segoe UI", 22, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Nothing & CMF earbuds", font=("Segoe UI", 11)).pack(anchor="w", pady=(0, 12))
        bar = ttk.Frame(frame)
        bar.pack(fill="x")
        self.scan_button = ttk.Button(bar, text="Scan", command=lambda: self.scan(True))
        self.scan_button.pack(side="left")
        ttk.Button(bar, text="Pair / Bluetooth settings", command=windows.bluetooth_settings).pack(side="left", padx=8)
        ttk.Button(bar, text="Sound settings", command=windows.sound_settings).pack(side="left")
        ttk.Label(frame, text="Buds Neo: take both buds out, hold both touch controls for about 5 seconds until pairing starts, then release.",
                  wraplength=710).pack(anchor="w", pady=(8, 0))
        ttk.Checkbutton(frame, text="Show every nearby Bluetooth device", variable=self.show_all,
                        command=self.render_devices).pack(anchor="w", pady=8)
        self.devices = ttk.Treeview(frame, columns=("address", "state"), height=4, selectmode="browse")
        self.devices.heading("#0", text="Device")
        self.devices.heading("address", text="Address")
        self.devices.heading("state", text="Status")
        self.devices.column("#0", width=270)
        self.devices.column("address", width=165)
        self.devices.column("state", width=100)
        self.devices.pack(fill="x")
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=8)
        self.open_button = ttk.Button(actions, text="Connect controls", command=self.connect)
        self.open_button.pack(side="left")
        self.refresh_button = ttk.Button(actions, text="Refresh status", command=self.refresh)
        self.refresh_button.pack(side="left", padx=8)
        self.disconnect_button = ttk.Button(actions, text="Close controls", command=self.disconnect)
        self.disconnect_button.pack(side="left")
        ttk.Label(frame, textvariable=self.title, font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(8, 0))
        ttk.Label(frame, textvariable=self.details, wraplength=710).pack(anchor="w", pady=8)
        self.tabs = ttk.Notebook(frame)
        self.tabs.pack(fill="both", expand=True)
        sound = ttk.Frame(self.tabs, padding=12)
        features = ttk.Frame(self.tabs, padding=12)
        self.gestures = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(sound, text="Sound")
        self.tabs.add(features, text="Features")
        self.tabs.add(self.gestures, text="Gestures")
        self.anc = self.combo(sound, "Noise control", protocol.ANC_MODES, "set_anc")
        self.eq = self.combo(sound, "Equalizer preset", protocol.EQ_PRESETS, "set_eq")
        self.spatial = self.combo(sound, "Spatial audio", protocol.SPATIAL_MODES, "set_spatial", unpack=True)
        self.eq_note = ttk.Label(sound, text="", wraplength=640)
        self.eq_note.pack(anchor="w", pady=6)
        self.eqbar = eqbar = ttk.Frame(sound)
        eqbar.pack(fill="x", pady=4)
        self.eq_bands = []
        for label in ("Bass", "Mid", "Treble"):
            ttk.Label(eqbar, text=label).pack(side="left", padx=(0, 5))
            var = tk.DoubleVar(value=0)
            spin = ttk.Spinbox(eqbar, from_=-6, to=6, increment=0.5, width=5, textvariable=var)
            spin.pack(side="left", padx=(0, 10))
            self.eq_bands.append(var)
            self.controls.append(spin)
        self.custom_eq_button = self.button(sound, "Apply custom EQ", self.custom_eq)
        bassbar = ttk.Frame(sound)
        bassbar.pack(fill="x", pady=6)
        self.bass = tk.BooleanVar()
        check = ttk.Checkbutton(bassbar, text="Bass enhance", variable=self.bass)
        check.pack(side="left")
        self.bass_level = tk.IntVar(value=3)
        spin = ttk.Spinbox(bassbar, from_=0, to=5, width=4, textvariable=self.bass_level)
        spin.pack(side="left", padx=12)
        self.controls.extend([check, spin])
        self.button(bassbar, "Apply bass", self.apply_bass).pack_configure(side="left")
        self.switches = {}
        for key, label, method in (
            ("latency", "Low latency", "set_latency"),
            ("in_ear", "In-ear detection", "set_in_ear"),
            ("personalized_anc", "Personalized ANC", "set_personalized_anc"),
            ("super_mic", "Super Mic", "set_super_mic"),
        ):
            var = tk.BooleanVar()
            check = ttk.Checkbutton(features, text=label, variable=var,
                                    command=lambda m=method, v=var: self.setting(m, v.get()))
            check.pack(anchor="w", pady=3)
            self.switches[key] = (var, check)
            self.controls.append(check)
        rings = ttk.Frame(features)
        rings.pack(fill="x", pady=8)
        for label, side, enabled in (("Ring left", 2, True), ("Ring right", 3, True), ("Stop ringing", 0, False)):
            self.button(rings, label, lambda s=side, e=enabled: self.setting(
                "ring", s, e, ear1=bool(self.model and self.model.ear1_ring))).pack_configure(side="left", padx=(0, 8))
        ttk.Label(features, text="Take the buds out of your ears before ringing them.").pack(anchor="w")
        self.button(features, "Run ear-tip fit test", self.fit_test)
        self.status_label = ttk.Label(frame, textvariable=self.status, wraplength=710)
        self.status_label.pack(anchor="w", pady=(12, 0))
        self.update_enabled()
        root.protocol("WM_DELETE_WINDOW", self.close)
        threading.Thread(target=self.worker, daemon=True).start()
        root.after(80, self.poll)
        self.scan(False)

    def button(self, parent, label, command):
        widget = ttk.Button(parent, text=label, command=command)
        widget.pack(anchor="w", pady=4)
        self.controls.append(widget)
        return widget

    def combo(self, parent, label, choices, method, *, unpack=False):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=label, width=22).pack(side="left")
        combo = ttk.Combobox(row, values=[label for _, label in choices], state="readonly", width=28)
        combo.pack(side="left")
        def selected(_event):
            current_choices = self.eq_choices if method == "set_eq" else choices
            value = current_choices[combo.current()][0]
            self.setting(method, *(value if unpack else (value,)))
        combo.bind("<<ComboboxSelected>>", selected)
        self.controls.append(combo)
        return combo

    def worker(self):
        while True:
            item = self.jobs.get()
            if item is None:
                if self.session:
                    self.session.close()
                return
            job, callback = item
            try:
                value = job()
                self.results.put((callback, value, None))
            except Exception as exc:
                self.results.put((callback, None, str(exc)))
            if self.closed.is_set():
                if self.session:
                    self.session.close()
                return

    def submit(self, job, callback, text):
        if self.busy or self.closed.is_set():
            return
        self.busy = True
        self.status.set(text)
        self.update_enabled()
        self.jobs.put((job, callback))

    def poll(self):
        if self.closed.is_set():
            return
        try:
            while True:
                callback, value, error = self.results.get_nowait()
                self.busy = False
                if error:
                    self.status.set(error)
                    messagebox.showerror("Ear Link", error, parent=self.root)
                else:
                    callback(value)
                self.update_enabled()
        except queue.Empty:
            pass
        self.root.after(80, self.poll)

    def update_enabled(self):
        self.scan_button.configure(state="disabled" if self.busy else "normal")
        self.open_button.configure(state="disabled" if self.busy else "normal")
        enabled = bool(self.session) and not self.busy
        for widget in [self.refresh_button, self.disconnect_button, *self.controls]:
            widget.configure(state=("readonly" if isinstance(widget, ttk.Combobox) else "normal")
                             if enabled else "disabled")
        for key, (_, widget) in self.switches.items():
            if getattr(getattr(self, "snapshot", None), key, None) is None:
                widget.configure(state="disabled")

    def scan(self, inquiry):
        self.submit(lambda: windows.devices(inquiry=inquiry), self.scanned,
                    "Scanning Bluetooth… Keep the buds in pairing mode." if inquiry else "Loading paired devices…")

    def scanned(self, found):
        self.found = found
        self.render_devices()
        self.status.set("Choose your paired earbuds and connect controls. Pair new devices in Bluetooth Settings.")

    def render_devices(self):
        previous = self.devices.selection()
        self.devices.delete(*self.devices.get_children())
        for index, device in enumerate(self.found):
            if self.show_all.get() or looks_like_earbud(device.name, device.address):
                state = "Connected" if device.connected else "Paired" if device.paired else "Not paired"
                self.devices.insert("", "end", iid=str(index), text=device.name, values=(device.address, state))
        children = self.devices.get_children()
        if children:
            self.devices.selection_set(previous[0] if previous and previous[0] in children else children[0])

    def connect(self):
        selected = self.devices.selection()
        if not selected:
            self.status.set("Scan and choose your earbuds first.")
            return
        device = self.found[int(selected[0])]
        if not device.paired:
            windows.bluetooth_settings()
            self.status.set("Pair these earbuds in Windows Settings, then scan again.")
            return
        model = match_model(device.name)
        def job():
            if self.session:
                self.session.close()
                self.session = None
            session = open_session(device.address)
            try:
                snapshot = session.snapshot(model)
            except BaseException:
                session.close()
                raise
            self.session = session
            return snapshot
        def connected(snapshot):
            self.model = model
            self.title.set(device.name)
            self.present(snapshot)
        self.submit(job, connected, "Connecting and reading earbud status…")

    def present(self, snapshot: Snapshot):
        self.snapshot = snapshot
        listening = bool(self.model and self.model.listening_eq)
        self.eq_choices = protocol.eq_presets(listening)
        self.eq.configure(values=[label for _, label in self.eq_choices])
        self.eq_note.configure(text="Buds Neo listening presets, including Immersion Boost." if listening else "")
        if listening:
            self.eqbar.pack_forget()
            self.custom_eq_button.pack_forget()
        elif not self.eqbar.winfo_manager():
            self.eqbar.pack(fill="x", pady=4, after=self.eq_note)
            self.custom_eq_button.pack(anchor="w", pady=4, after=self.eqbar)
        battery = " · ".join(f"{side.title()}: {value['level']}%" + (" (charging)" if value['charging'] else "")
                             for side, value in snapshot.battery.items())
        self.details.set(f"{battery or 'Battery unavailable'}\nFirmware: {snapshot.firmware or 'unknown'}"
                         f" · Serial: {snapshot.serial or 'unknown'}")
        for combo, choices, value in ((self.anc, protocol.ANC_MODES, snapshot.anc),
                                       (self.eq, self.eq_choices, snapshot.eq),
                                       (self.spatial, protocol.SPATIAL_MODES, snapshot.spatial)):
            combo.set(next((label for code, label in choices if code == value), ""))
        self.bass.set(bool(snapshot.bass_enabled))
        self.bass_level.set(snapshot.bass_level if snapshot.bass_level is not None else 3)
        if snapshot.custom_eq:
            for var, value in zip(self.eq_bands, snapshot.custom_eq):
                var.set(round(value, 1))
        for key, (var, _) in self.switches.items():
            var.set(bool(getattr(snapshot, key)))
        for child in self.gestures.winfo_children():
            self.controls = [widget for widget in self.controls if widget.master != child]
            child.destroy()
        choices = list(protocol.GESTURE_ACTIONS.items())
        if not snapshot.gestures:
            ttk.Label(self.gestures, text="No gestures reported by these earbuds.").pack(anchor="w")
        for slot in snapshot.gestures:
            row = ttk.Frame(self.gestures)
            row.pack(fill="x", pady=3)
            label = f"{protocol.GESTURE_SIDES.get(slot.side, str(slot.side))} · {protocol.GESTURE_TYPES.get(slot.gesture, str(slot.gesture))}"
            ttk.Label(row, text=label, width=30).pack(side="left")
            combo = ttk.Combobox(row, values=[label for _, label in choices], state="readonly", width=24)
            combo.set(protocol.GESTURE_ACTIONS.get(slot.action, f"Action {slot.action}"))
            combo.pack(side="left")
            combo.bind("<<ComboboxSelected>>", lambda _event, s=slot, c=combo:
                       self.setting("set_gesture", s, choices[c.current()][0]))
            self.controls.append(combo)
        self.status.set(" ".join(snapshot.notes) or "Controls connected. Windows manages the audio codec and output.")

    def refresh(self):
        if self.session:
            session, model = self.session, self.model
            self.submit(lambda: session.snapshot(model), self.present, "Reading earbud status…")

    def setting(self, method, *args, **kwargs):
        if self.session:
            session = self.session
            self.submit(lambda: getattr(session, method)(*args, **kwargs),
                        lambda _: self.status.set("Command sent. Refresh status to read back the setting."),
                        "Sending setting…")

    def custom_eq(self):
        try:
            values = [var.get() for var in self.eq_bands]
            if not all(-6 <= value <= 6 for value in values):
                raise ValueError
        except (ValueError, tk.TclError):
            self.status.set("EQ bands must be numbers between -6 and 6 dB.")
            return
        self.setting("set_custom_eq", *values, self.model.eq_profile if self.model else "3400")

    def apply_bass(self):
        try:
            level = self.bass_level.get()
            if not 0 <= level <= 5:
                raise ValueError
        except (ValueError, tk.TclError):
            self.status.set("Bass level must be a whole number between 0 and 5.")
            return
        self.setting("set_bass", self.bass.get(), level)

    def fit_test(self):
        if self.session:
            self.submit(self.session.start_fit_test, lambda frame: self.status.set(
                "Fit test response: " + frame.payload.hex(" ") if frame else "No fit-test result returned."),
                "Running ear-tip fit test…")

    def disconnect(self):
        def job():
            if self.session:
                self.session.close()
                self.session = None
        def done(_):
            self.title.set("Choose your earbuds")
            self.details.set("")
            self.status.set("Control connection closed. Manage the audio connection in Bluetooth Settings.")
        self.submit(job, done, "Closing controls…")

    def close(self):
        self.closed.set()
        # Wake an idle worker; a busy worker closes its session after its job.
        self.jobs.put(None)
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    EarWindow(root)
    root.mainloop()
    return 0
