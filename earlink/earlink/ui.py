"""GTK 4 / libadwaita window for pairing and controlling earbuds."""

from __future__ import annotations

import queue
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from . import audio, protocol
from .bluez import Adapter
from .catalog import looks_like_earbud, match_model
from .session import EarSession, GestureSlot, Snapshot, open_session

APP_ID = "page.earlink.EarLink"


class EarApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.connect("activate", self._activate)

    def _activate(self, _app) -> None:
        window = self.props.active_window
        if window is None:
            window = MainWindow(self)
        window.present()


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: EarApp) -> None:
        super().__init__(application=app, title="Ear Link")
        self.set_default_size(960, 780)
        self._jobs: queue.Queue = queue.Queue()
        self._session: EarSession | None = None
        self._model = None
        self._snapshot = Snapshot()
        self._address = ""
        self._device_path = ""
        self._updating = False
        self._show_all = False
        self._scanning = False
        try:
            self.adapter = Adapter()
        except Exception as exc:  # dbus may be down
            self.adapter = None
            self._adapter_error = str(exc)
        else:
            self._adapter_error = ""
        threading.Thread(target=self._worker, name="earlink-bt", daemon=True).start()

        self.toast = Adw.ToastOverlay()
        self.toolbar = Adw.ToolbarView()
        self.toast.set_child(self.toolbar)
        self.set_content(self.toast)

        self.header = Adw.HeaderBar()
        self.back = Gtk.Button(icon_name="go-previous-symbolic")
        self.back.set_tooltip_text("Devices")
        self.back.connect("clicked", lambda *_: self._show_devices())
        self.back.set_visible(False)
        self.header.pack_start(self.back)
        self.scan_button = Gtk.ToggleButton(label="Scan")
        self.scan_button.connect("toggled", self._on_scan)
        self.header.pack_start(self.scan_button)
        about = Gtk.Button(icon_name="help-about-symbolic")
        about.connect("clicked", self._about)
        self.header.pack_end(about)
        self.spinner = Gtk.Spinner()
        self.header.pack_end(self.spinner)
        self.toolbar.add_top_bar(self.header)

        self.stack = Gtk.Stack()
        self.stack.set_vexpand(True)
        self.toolbar.set_content(self.stack)
        self.stack.add_named(self._build_devices(), "devices")
        self.stack.add_named(self._build_controls(), "controls")

        self.connect("close-request", self._on_close)
        GLib.timeout_add_seconds(2, self._poll_devices)
        self._refresh_adapter_status()
        self._reload_devices()

    # ---- jobs -------------------------------------------------------------

    def _worker(self) -> None:
        while True:
            job = self._jobs.get()
            try:
                job()
            except Exception as exc:  # surface every background failure
                message = str(exc) or exc.__class__.__name__
                GLib.idle_add(self._toast, message)

    def _submit(self, job) -> None:
        self.spinner.start()
        def wrapped():
            try:
                job()
            finally:
                GLib.idle_add(self.spinner.stop)
        self._jobs.put(wrapped)

    def _toast(self, message: str) -> None:
        self.toast.add_toast(Adw.Toast(title=message, timeout=5))

    def _on_close(self, *_args) -> bool:
        if self.adapter is not None:
            try:
                if self._scanning:
                    self.adapter.stop_discovery()
            except Exception:
                pass
            self.adapter.close()
        if self._session is not None:
            self._session.close()
        return False

    # ---- devices ----------------------------------------------------------

    def _build_devices(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page.set_margin_top(12)
        page.set_margin_bottom(12)
        page.set_margin_start(12)
        page.set_margin_end(12)
        self.status = Adw.Banner()
        self.status.set_revealed(True)
        page.append(self.status)
        hint = Gtk.Label(
            label="Open the case and press Scan. Buds Neo do not have a pairing button. "
            "Ear Link pairs them for audio, then opens their control channel.",
            wrap=True,
            xalign=0,
        )
        hint.add_css_class("dim-label")
        page.append(hint)
        self.show_all = Gtk.CheckButton(label="Show every nearby Bluetooth device")
        self.show_all.connect("toggled", self._on_show_all)
        page.append(self.show_all)
        self.power = Gtk.Button(label="Turn Bluetooth on")
        self.power.connect("clicked", lambda *_: self._submit(self._power_on))
        self.power.set_halign(Gtk.Align.START)
        page.append(self.power)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        self.device_list = Gtk.ListBox()
        self.device_list.add_css_class("boxed-list")
        self.device_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll.set_child(self.device_list)
        page.append(scroll)
        return page

    def _build_controls(self) -> Gtk.Widget:
        self.controls = Adw.PreferencesPage()
        self.info_group = Adw.PreferencesGroup(title="Earbuds")
        self.controls.add(self.info_group)
        self.battery_row = Adw.ActionRow(title="Battery")
        self.info_group.add(self.battery_row)
        self.identity_row = Adw.ActionRow(title="Device")
        self.info_group.add(self.identity_row)

        self.noise_group = Adw.PreferencesGroup(title="Noise control")
        self.controls.add(self.noise_group)
        self.anc_group = Adw.ToggleGroup()
        self.anc_group.set_homogeneous(True)
        for value, label in protocol.ANC_MODES:
            self.anc_group.add(Adw.Toggle(label=label, name=str(value)))
        self.anc_group.connect("notify::active-name", self._on_anc)
        self.noise_group.add(self._wrap(self.anc_group))

        self.sound_group = Adw.PreferencesGroup(title="Sound")
        self.controls.add(self.sound_group)
        self.eq_group = Adw.ToggleGroup()
        for value, label in protocol.EQ_PRESETS:
            self.eq_group.add(Adw.Toggle(label=label, name=str(value)))
        self.eq_group.connect("notify::active-name", self._on_eq)
        self.sound_group.add(self._wrap(self.eq_group))
        self.bass_scale = self._scale("Bass", self._on_custom_eq)
        self.mid_scale = self._scale("Mid", self._on_custom_eq)
        self.treble_scale = self._scale("Treble", self._on_custom_eq)
        for row in (self.bass_scale, self.mid_scale, self.treble_scale):
            self.sound_group.add(row)
        self.enhance = Adw.SwitchRow(title="Bass enhance")
        self.enhance.connect("notify::active", self._on_enhance)
        self.sound_group.add(self.enhance)
        self.enhance_level = Adw.SpinRow.new_with_range(0, 5, 1)
        self.enhance_level.set_title("Bass enhance amount")
        self.enhance_level.connect("notify::value", self._on_enhance)
        self.sound_group.add(self.enhance_level)
        self.spatial = self._combo("Spatial audio", [label for _pair, label in protocol.SPATIAL_MODES], self._on_spatial)
        self.sound_group.add(self.spatial)
        self.codec = self._combo("Computer audio profile", [], self._on_codec)
        self.sound_group.add(self.codec)

        self.gesture_group = Adw.PreferencesGroup(title="Controls", description="What a press on the earbuds does.")
        self.controls.add(self.gesture_group)

        self.extra_group = Adw.PreferencesGroup(title="Earbud settings")
        self.controls.add(self.extra_group)
        self.latency = self._switch("Low latency", self._on_latency)
        self.in_ear = self._switch("In-ear detection", self._on_in_ear)
        self.personal = self._switch("Personalized noise cancellation", self._on_personal)
        self.super_mic = self._switch("Super mic", self._on_super_mic)
        for row in (self.latency, self.in_ear, self.personal, self.super_mic):
            self.extra_group.add(row)
        find = Gtk.Box(spacing=8)
        for label, side in (("Ring left", 0x02), ("Ring right", 0x03), ("Stop", 0)):
            button = Gtk.Button(label=label)
            button.connect("clicked", self._on_ring, side, label != "Stop")
            find.append(button)
        self.extra_group.add(self._wrap(find))
        fit = Gtk.Button(label="Run ear-tip fit test")
        fit.connect("clicked", lambda *_: self._submit(self._fit_test))
        fit.set_halign(Gtk.Align.START)
        self.extra_group.add(self._wrap(fit))
        color = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog())
        color.connect("notify::rgba", self._on_color)
        color_row = Adw.ActionRow(title="Case light", subtitle="Nothing Ear (1)")
        color_row.add_suffix(color)
        self.color_button = color
        self.color_row = color_row
        self.extra_group.add(color_row)

        disconnect = Gtk.Button(label="Disconnect")
        disconnect.connect("clicked", lambda *_: self._submit(self._disconnect))
        forget = Gtk.Button(label="Forget")
        forget.add_css_class("destructive-action")
        forget.connect("clicked", lambda *_: self._submit(self._forget))
        actions = Gtk.Box(spacing=8)
        actions.append(disconnect)
        actions.append(forget)
        self.extra_group.add(self._wrap(actions))
        return self.controls

    def _scale(self, title: str, callback) -> Adw.SpinRow:
        row = Adw.SpinRow.new_with_range(-6, 6, 1)
        row.set_title(title)
        row.connect("notify::value", callback)
        return row

    def _switch(self, title: str, callback) -> Adw.SwitchRow:
        row = Adw.SwitchRow(title=title)
        row.connect("notify::active", callback)
        return row

    def _combo(self, title: str, labels: list[str], callback) -> Adw.ComboRow:
        row = Adw.ComboRow(title=title)
        row.set_model(Gtk.StringList.new(labels))
        row.connect("notify::selected", callback)
        return row

    @staticmethod
    def _wrap(widget: Gtk.Widget) -> Adw.ActionRow:
        row = Adw.ActionRow()
        widget.set_hexpand(True)
        row.set_child(widget)
        return row

    def _refresh_adapter_status(self) -> None:
        if self.adapter is None:
            self.status.set_title(self._adapter_error or "Bluetooth is unavailable")
            self.power.set_visible(False)
            self.scan_button.set_sensitive(False)
            return
        try:
            on = self.adapter.powered()
            name = self.adapter.alias()
        except Exception as exc:
            self.status.set_title(str(exc))
            return
        self.power.set_visible(not on)
        self.scan_button.set_sensitive(on)
        if on:
            self.status.set_title(f"Bluetooth is on · this computer is {name}")
        else:
            self.status.set_title("Bluetooth is off")

    def _power_on(self) -> None:
        if self.adapter is None:
            return
        self.adapter.set_powered(True)
        GLib.idle_add(self._refresh_adapter_status)
        GLib.idle_add(self._reload_devices)

    def _on_scan(self, button: Gtk.ToggleButton) -> None:
        if self.adapter is None:
            return
        self._scanning = button.get_active()
        def job():
            if self._scanning:
                self.adapter.start_discovery()
            else:
                self.adapter.stop_discovery()
            GLib.idle_add(self._reload_devices)
        self._submit(job)

    def _on_show_all(self, button: Gtk.CheckButton) -> None:
        self._show_all = button.get_active()
        self._reload_devices()

    def _poll_devices(self) -> bool:
        if self.stack.get_visible_child_name() == "devices":
            self._reload_devices()
        return True

    def _reload_devices(self) -> None:
        if self.adapter is None:
            return
        try:
            devices = self.adapter.devices()
        except Exception as exc:
            self.status.set_title(str(exc))
            return
        visible_devices = [
            device
            for device in devices
            if self._show_all or looks_like_earbud(device.name, device.address)
        ]
        signature = tuple(
            (device.address, device.name, device.paired, device.connected) for device in visible_devices
        )
        if signature == getattr(self, "_device_signature", None):
            return
        self._device_signature = signature
        while True:
            row = self.device_list.get_row_at_index(0)
            if row is None:
                break
            self.device_list.remove(row)
        visible = 0
        for device in visible_devices:
            visible += 1
            title = device.name or device.address
            model = match_model(device.name)
            if model and model.name.casefold() not in title.casefold():
                title = f"{title} · {model.name}"
            bits = [device.address]
            if device.connected:
                bits.append("connected")
            elif device.paired:
                bits.append("paired")
            else:
                bits.append("not paired")
            row = Adw.ActionRow(title=title, subtitle=" · ".join(bits))
            if device.connected:
                button = Gtk.Button(label="Controls")
                button.add_css_class("suggested-action")
                button.connect("clicked", self._on_open, device)
            elif device.paired:
                button = Gtk.Button(label="Connect")
                button.connect("clicked", self._on_connect, device)
            else:
                button = Gtk.Button(label="Pair")
                button.add_css_class("suggested-action")
                button.connect("clicked", self._on_pair, device)
            button.set_valign(Gtk.Align.CENTER)
            row.add_suffix(button)
            self.device_list.append(row)
        if visible == 0:
            empty = Adw.ActionRow(
                title="No earbuds yet",
                subtitle="Put them in pairing mode and press Scan. Their names look like Nothing Ear or CMF Buds.",
            )
            self.device_list.append(empty)

    def _remember(self, device) -> None:
        self._device_path = device.path
        self._address = device.address
        self._model = match_model(device.name)

    def _on_pair(self, _button, device) -> None:
        self._remember(device)
        self._toast(f"Pairing {device.name}…")
        path, name, address = device.path, device.name, device.address
        self._submit(lambda: self._pair_job(path, name, address))

    def _on_connect(self, _button, device) -> None:
        self._remember(device)
        self._toast(f"Connecting to {device.name}…")
        path, name, address = device.path, device.name, device.address
        self._submit(lambda: self._connect_job(path, name, address))

    def _on_open(self, _button, device) -> None:
        self._remember(device)
        path, name, address = device.path, device.name, device.address
        self._submit(lambda: self._open_controls_job(path, name, address))

    def _pair_job(self, path: str, name: str, address: str) -> None:
        assert self.adapter is not None
        self.adapter.pair_and_connect(path)
        self._open_controls_job(path, name, address)
        GLib.idle_add(self._toast, f"Paired {name}")

    def _connect_job(self, path: str, name: str, address: str) -> None:
        assert self.adapter is not None
        self.adapter.connect(path)
        self._open_controls_job(path, name, address)

    def _open_controls_job(self, path: str, name: str, address: str) -> None:
        self._address = address
        self._device_path = path
        self._model = match_model(name)
        if self._session is not None:
            self._session.close()
            self._session = None
        session = open_session(self._address)
        snapshot = session.snapshot(self._model)
        self._session = session
        profiles = audio.codec_profiles(self._address)
        active = audio.active_profile(self._address)
        GLib.idle_add(self._present_controls, snapshot, profiles, active, path)

    def _show_devices(self) -> None:
        self.back.set_visible(False)
        self.scan_button.set_visible(True)
        self.stack.set_visible_child_name("devices")
        self._reload_devices()

    def _present_controls(self, snapshot: Snapshot, profiles, active, path: str) -> None:
        self._snapshot = snapshot
        self._device_path = path
        self._updating = True
        self.back.set_visible(True)
        self.scan_button.set_visible(False)
        name = self._model.name if self._model else self._address
        bits = [self._address]
        if snapshot.firmware:
            bits.append(f"firmware {snapshot.firmware}")
        if snapshot.serial:
            bits.append(f"serial {snapshot.serial}")
        self.identity_row.set_title(name)
        self.identity_row.set_subtitle(" · ".join(bits))
        self.battery_row.set_subtitle(self._battery_text(snapshot))
        self._select_toggle(self.anc_group, snapshot.anc)
        self._select_toggle(self.eq_group, snapshot.eq)
        if snapshot.custom_eq:
            bass, mid, treble = snapshot.custom_eq
            self.bass_scale.set_value(round(bass))
            self.mid_scale.set_value(round(mid))
            self.treble_scale.set_value(round(treble))
        if snapshot.bass_enabled is not None:
            self.enhance.set_active(snapshot.bass_enabled)
        if snapshot.bass_level is not None:
            self.enhance_level.set_value(snapshot.bass_level)
        self._set_switch(self.latency, snapshot.latency)
        self._set_switch(self.in_ear, snapshot.in_ear)
        self._set_switch(self.personal, snapshot.personalized_anc)
        self._set_switch(self.super_mic, snapshot.super_mic)
        self.spatial.set_visible(True)
        self._set_spatial(snapshot.spatial)
        self._fill_codecs(profiles, active)
        self._fill_gestures(snapshot.gestures)
        ear1 = bool(self._model and self._model.ear1_ring)
        self.color_row.set_visible(ear1)
        for note in snapshot.notes:
            self._toast(note)
        if not snapshot.battery and snapshot.firmware is None and snapshot.anc is None and snapshot.eq is None:
            self._toast("Connected for audio. The earbud control channel did not return settings.")
        self.stack.set_visible_child_name("controls")
        self._updating = False

    @staticmethod
    def _battery_text(snapshot: Snapshot) -> str:
        labels = (("left", "Left"), ("right", "Right"), ("case", "Case"), ("headset", "Headset"))
        parts = []
        for key, title in labels:
            reading = snapshot.battery.get(key)
            if not reading:
                continue
            suffix = ", charging" if reading.get("charging") else ""
            parts.append(f"{title} {reading['level']}%{suffix}")
        return " · ".join(parts) if parts else "Battery not reported yet. Open the case for the case level."

    def _select_toggle(self, group: Adw.ToggleGroup, value: int | None) -> None:
        if value is None:
            return
        if group.get_toggle_by_name(str(value)) is not None:
            group.set_active_name(str(value))

    def _set_switch(self, row: Adw.SwitchRow, value: bool | None) -> None:
        row.set_visible(value is not None)
        if value is not None:
            row.set_active(value)

    def _set_spatial(self, value: tuple[int, int] | None) -> None:
        if value is None:
            return
        for index, (pair, _label) in enumerate(protocol.SPATIAL_MODES):
            if pair == value:
                self.spatial.set_selected(index)
                return

    def _fill_codecs(self, profiles, active: str | None) -> None:
        labels = [item["label"] for item in profiles] or ["No Bluetooth audio profile yet"]
        self._codec_profiles = profiles
        self.codec.set_model(Gtk.StringList.new(labels))
        self.codec.set_sensitive(bool(profiles))
        if active:
            for index, item in enumerate(profiles):
                if item["profile"] == active:
                    self.codec.set_selected(index)
                    break

    def _fill_gestures(self, slots: list[GestureSlot]) -> None:
        # Drop previously generated rows. The first children are not stored, so
        # the group is rebuilt from a clean list kept on the window.
        for row in getattr(self, "_gesture_rows", []):
            self.gesture_group.remove(row)
        self._gesture_rows = []
        actions = list(protocol.GESTURE_ACTIONS.items())
        if not slots:
            row = Adw.ActionRow(title="No gesture map reported")
            self.gesture_group.add(row)
            self._gesture_rows.append(row)
            return
        for slot in slots:
            labels = []
            codes = []
            known = False
            for code, label in actions:
                labels.append(label)
                codes.append(code)
                if code == slot.action:
                    known = True
            if not known:
                labels.append(f"Action {slot.action}")
                codes.append(slot.action)
            row = Adw.ComboRow(title=slot.label)
            row.set_model(Gtk.StringList.new(labels))
            row.set_selected(codes.index(slot.action))
            row.connect("notify::selected", self._on_gesture, slot, codes)
            self.gesture_group.add(row)
            self._gesture_rows.append(row)

    # ---- control actions --------------------------------------------------

    def _session_call(self, func) -> None:
        def job():
            if self._session is None:
                raise OSError("The earbuds are not connected")
            func(self._session)
        self._submit(job)

    def _on_anc(self, group, _param) -> None:
        if self._updating:
            return
        name = group.get_active_name()
        if not name:
            return
        self._session_call(lambda session: session.set_anc(int(name)))

    def _on_eq(self, group, _param) -> None:
        if self._updating:
            return
        name = group.get_active_name()
        if not name:
            return
        preset = int(name)
        if preset == 0x05:
            self._on_custom_eq()
            return
        self._session_call(lambda session: session.set_eq(preset))

    def _on_custom_eq(self, *_args) -> None:
        if self._updating:
            return
        profile = self._model.eq_profile if self._model else "3400"
        bass = self.bass_scale.get_value()
        mid = self.mid_scale.get_value()
        treble = self.treble_scale.get_value()
        self._session_call(lambda session: session.set_custom_eq(bass, mid, treble, profile))

    def _on_enhance(self, *_args) -> None:
        if self._updating:
            return
        enabled = self.enhance.get_active()
        level = int(self.enhance_level.get_value())
        self._session_call(lambda session: session.set_bass(enabled, level))

    def _on_spatial(self, row, _param) -> None:
        if self._updating:
            return
        index = row.get_selected()
        if index < 0 or index >= len(protocol.SPATIAL_MODES):
            return
        first, second = protocol.SPATIAL_MODES[index][0]
        self._session_call(lambda session: session.set_spatial(first, second))

    def _on_codec(self, row, _param) -> None:
        if self._updating:
            return
        profiles = getattr(self, "_codec_profiles", [])
        index = row.get_selected()
        if index < 0 or index >= len(profiles):
            return
        profile = profiles[index]["profile"]
        address = self._address
        self._submit(lambda: audio.set_profile(address, profile))

    def _on_latency(self, row, _param) -> None:
        if self._updating:
            return
        enabled = row.get_active()
        self._session_call(lambda session: session.set_latency(enabled))

    def _on_in_ear(self, row, _param) -> None:
        if self._updating:
            return
        enabled = row.get_active()
        self._session_call(lambda session: session.set_in_ear(enabled))

    def _on_personal(self, row, _param) -> None:
        if self._updating:
            return
        enabled = row.get_active()
        self._session_call(lambda session: session.set_personalized_anc(enabled))

    def _on_super_mic(self, row, _param) -> None:
        if self._updating:
            return
        enabled = row.get_active()
        self._session_call(lambda session: session.set_super_mic(enabled))

    def _on_gesture(self, row, _param, slot: GestureSlot, codes: list[int]) -> None:
        if self._updating:
            return
        index = row.get_selected()
        if index < 0 or index >= len(codes):
            return
        action = codes[index]
        self._session_call(lambda session: session.set_gesture(slot, action))

    def _on_ring(self, _button, side: int, enabled: bool) -> None:
        ear1 = bool(self._model and self._model.ear1_ring)
        if side == 0:
            self._session_call(lambda session: session.ring(0x02, False, ear1=ear1))
            return
        self._session_call(lambda session: session.ring(side, enabled, ear1=ear1))

    def _fit_test(self) -> None:
        if self._session is None:
            raise OSError("The earbuds are not connected")
        frame = self._session.start_fit_test()
        if frame is None or len(frame.payload) < 2:
            GLib.idle_add(self._toast, "Fit test finished without a result. Keep both earbuds in.")
            return
        left, right = frame.payload[0], frame.payload[1]
        GLib.idle_add(self._toast, f"Fit test · left {left}, right {right}. A higher code is a better seal.")

    def _on_color(self, button, _param) -> None:
        if self._updating:
            return
        color = button.get_rgba()
        red = int(color.red * 255)
        green = int(color.green * 255)
        blue = int(color.blue * 255)
        self._session_call(lambda session: session.set_case_color(red, green, blue))

    def _disconnect(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None
        if self.adapter is not None and self._device_path:
            self.adapter.disconnect(self._device_path)
        GLib.idle_add(self._show_devices)
        GLib.idle_add(self._toast, "Disconnected")

    def _forget(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None
        if self.adapter is not None and self._device_path:
            self.adapter.forget(self._device_path)
        GLib.idle_add(self._show_devices)
        GLib.idle_add(self._toast, "Earbuds removed from this computer")

    def _about(self, *_args) -> None:
        dialog = Adw.AboutDialog(
            application_name="Ear Link",
            application_icon="audio-headphones-symbolic",
            version="1.0.0",
            comments=(
                "Finds Nothing and CMF earbuds, pairs them for audio, and controls noise cancellation, "
                "the equalizer, gestures, battery, low latency, in-ear detection, find-my-earbuds, "
                "the fit test, bass enhance, spatial audio, personalized ANC, and Super Mic. "
                "Firmware flashing, Audiodo, Dirac, Magic Button, and transcription stay in the official app "
                "because they need Nothing's online services. Dual connection still works: pair this "
                "computer here, and pair the phone from the phone."
            ),
        )
        dialog.present(self)


def main() -> int:
    app = EarApp()
    return app.run(None)
