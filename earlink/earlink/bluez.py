"""BlueZ adapter access: discovery, pairing, and connection.

Pairing uses a NoInputNoOutput agent so earbuds that use Just Works can
complete without a PIN. The desktop's own agent is restored when this
process releases the agent.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop

DBusGMainLoop(set_as_default=True)

BUS_NAME = "org.bluez"
AGENT_PATH = "/org/earlink/agent"


@dataclass
class Device:
    path: str
    address: str
    name: str
    paired: bool
    connected: bool
    trusted: bool
    rssi: int | None


class Rejected(dbus.DBusException):
    _dbus_error_name = "org.bluez.Error.Rejected"


class Agent(dbus.service.Object):
    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Release(self):  # noqa: N802
        return None

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="s")
    def RequestPinCode(self, device):  # noqa: N802
        return "0000"

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):  # noqa: N802
        return None

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="u")
    def RequestPasskey(self, device):  # noqa: N802
        return dbus.UInt32(0)

    @dbus.service.method("org.bluez.Agent1", in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):  # noqa: N802
        return None

    @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):  # noqa: N802
        return None

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
    def RequestAuthorization(self, device):  # noqa: N802
        return None

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):  # noqa: N802
        return None

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Cancel(self):  # noqa: N802
        return None


class Adapter:
    def __init__(self) -> None:
        self.bus = dbus.SystemBus()
        self._local = threading.local()
        self.agent = Agent(self.bus, AGENT_PATH)
        self._agent_ready = False
        manager = dbus.Interface(self.bus.get_object(BUS_NAME, "/"), "org.bluez.AgentManager1")
        try:
            manager.RegisterAgent(AGENT_PATH, "NoInputNoOutput")
            manager.RequestDefaultAgent(AGENT_PATH)
            self._agent_ready = True
        except dbus.DBusException:
            # The desktop session already owns an agent. Pairing dialogs still work.
            self._agent_ready = False
        self._manager = manager

    def close(self) -> None:
        if not self._agent_ready:
            return
        try:
            self._manager.UnregisterAgent(AGENT_PATH)
        except dbus.DBusException:
            pass

    def _bus(self):
        # The agent lives on the main connection, which the GTK loop dispatches.
        # Every other call uses a connection owned by the calling thread.
        if threading.current_thread() is threading.main_thread():
            return self.bus
        bus = getattr(self._local, "bus", None)
        if bus is None:
            bus = dbus.SystemBus(private=True)
            self._local.bus = bus
        return bus

    def _adapter_path(self) -> str:
        objects = dbus.Interface(
            self._bus().get_object(BUS_NAME, "/"), "org.freedesktop.DBus.ObjectManager"
        ).GetManagedObjects()
        powered = None
        fallback = None
        for path, interfaces in objects.items():
            if "org.bluez.Adapter1" not in interfaces:
                continue
            fallback = fallback or path
            if interfaces["org.bluez.Adapter1"].get("Powered"):
                powered = path
                break
        if powered or fallback:
            return str(powered or fallback)
        raise OSError("No Bluetooth adapter found")

    def properties(self):
        path = self._adapter_path()
        return path, dbus.Interface(self._bus().get_object(BUS_NAME, path), "org.freedesktop.DBus.Properties")

    def powered(self) -> bool:
        _path, props = self.properties()
        return bool(props.Get("org.bluez.Adapter1", "Powered"))

    def alias(self) -> str:
        _path, props = self.properties()
        return str(props.Get("org.bluez.Adapter1", "Alias"))

    def set_powered(self, enabled: bool) -> None:
        _path, props = self.properties()
        props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(enabled))

    def start_discovery(self) -> None:
        path, _props = self.properties()
        adapter = dbus.Interface(self._bus().get_object(BUS_NAME, path), "org.bluez.Adapter1")
        try:
            adapter.SetDiscoveryFilter({"Transport": "auto"})
        except dbus.DBusException:
            pass
        try:
            adapter.StartDiscovery()
        except dbus.DBusException as exc:
            if "InProgress" not in str(exc):
                raise

    def stop_discovery(self) -> None:
        path, _props = self.properties()
        adapter = dbus.Interface(self._bus().get_object(BUS_NAME, path), "org.bluez.Adapter1")
        try:
            adapter.StopDiscovery()
        except dbus.DBusException:
            pass

    def devices(self) -> list[Device]:
        objects = dbus.Interface(
            self._bus().get_object(BUS_NAME, "/"), "org.freedesktop.DBus.ObjectManager"
        ).GetManagedObjects()
        found: list[Device] = []
        for path, interfaces in objects.items():
            raw = interfaces.get("org.bluez.Device1")
            if raw is None:
                continue
            address = str(raw.get("Address", ""))
            name = str(raw.get("Alias") or raw.get("Name") or address)
            rssi = raw.get("RSSI")
            found.append(
                Device(
                    path=str(path),
                    address=address,
                    name=name,
                    paired=bool(raw.get("Paired", False)),
                    connected=bool(raw.get("Connected", False)),
                    trusted=bool(raw.get("Trusted", False)),
                    rssi=int(rssi) if rssi is not None else None,
                )
            )
        found.sort(key=lambda device: (not device.connected, not device.paired, device.name.casefold()))
        return found

    def _device(self, path: str):
        obj = self._bus().get_object(BUS_NAME, path)
        return (
            dbus.Interface(obj, "org.bluez.Device1"),
            dbus.Interface(obj, "org.freedesktop.DBus.Properties"),
        )

    def pair_and_connect(self, path: str) -> None:
        device, props = self._device(path)
        try:
            if not bool(props.Get("org.bluez.Device1", "Paired")):
                device.Pair(timeout=90)
        except dbus.DBusException as exc:
            if "AlreadyExists" not in str(exc):
                raise OSError(self._explain(exc)) from exc
        props.Set("org.bluez.Device1", "Trusted", dbus.Boolean(True))
        try:
            if not bool(props.Get("org.bluez.Device1", "Connected")):
                device.Connect(timeout=45)
        except dbus.DBusException as exc:
            raise OSError(self._explain(exc)) from exc

    def connect(self, path: str) -> None:
        device, props = self._device(path)
        props.Set("org.bluez.Device1", "Trusted", dbus.Boolean(True))
        try:
            if not bool(props.Get("org.bluez.Device1", "Connected")):
                device.Connect(timeout=45)
        except dbus.DBusException as exc:
            raise OSError(self._explain(exc)) from exc

    def disconnect(self, path: str) -> None:
        device, _props = self._device(path)
        try:
            device.Disconnect(timeout=20)
        except dbus.DBusException as exc:
            if "NotConnected" not in str(exc):
                raise OSError(self._explain(exc)) from exc

    def forget(self, path: str) -> None:
        adapter_path, _props = self.properties()
        adapter = dbus.Interface(self._bus().get_object(BUS_NAME, adapter_path), "org.bluez.Adapter1")
        try:
            self.disconnect(path)
        except OSError:
            pass
        try:
            adapter.RemoveDevice(path)
        except dbus.DBusException as exc:
            raise OSError(self._explain(exc)) from exc

    @staticmethod
    def _explain(exc: dbus.DBusException) -> str:
        text = str(exc)
        if "AuthenticationFailed" in text or "AuthenticationCanceled" in text:
            return "Pairing was rejected. Put the earbuds in pairing mode and try again."
        if "ConnectionAttemptFailed" in text:
            return "The earbuds refused the connection. Open the case, then try again."
        if "InProgress" in text:
            return "Bluetooth is already busy with another connection."
        message = exc.get_dbus_message() if hasattr(exc, "get_dbus_message") else text
        return message or text
