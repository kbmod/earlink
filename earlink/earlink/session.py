"""RFCOMM session with one paired earbud."""

from __future__ import annotations

import re
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field

from . import protocol
from .catalog import Model

READ_ALIASES = {
    protocol.OP_SERIAL: {protocol.command(protocol.OP_SERIAL, protocol.DIR_RESPONSE)},
    protocol.OP_BATTERY: {
        protocol.command(protocol.OP_BATTERY, protocol.DIR_RESPONSE),
        protocol.command(0x01, protocol.DIR_EVENT),
    },
    protocol.OP_ANC_GET: {
        protocol.command(protocol.OP_ANC_GET, protocol.DIR_RESPONSE),
        protocol.command(0x03, protocol.DIR_EVENT),
    },
    protocol.OP_EQ_GET: {
        protocol.command(protocol.OP_EQ_GET, protocol.DIR_RESPONSE),
        protocol.command(protocol.OP_LISTENING, protocol.DIR_RESPONSE),
    },
    protocol.OP_CUSTOM_EQ: {protocol.command(protocol.OP_CUSTOM_EQ, protocol.DIR_RESPONSE)},
    protocol.OP_BASS: {protocol.command(protocol.OP_BASS, protocol.DIR_RESPONSE)},
    protocol.OP_PERSONAL_ANC: {protocol.command(protocol.OP_PERSONAL_ANC, protocol.DIR_RESPONSE)},
    protocol.OP_IN_EAR: {protocol.command(protocol.OP_IN_EAR, protocol.DIR_RESPONSE)},
    protocol.OP_LATENCY_GET: {protocol.command(protocol.OP_LATENCY_GET, protocol.DIR_RESPONSE)},
    protocol.OP_FIRMWARE: {protocol.command(protocol.OP_FIRMWARE, protocol.DIR_RESPONSE)},
    protocol.OP_GESTURE_GET: {protocol.command(protocol.OP_GESTURE_GET, protocol.DIR_RESPONSE)},
    protocol.OP_SUPER_MIC: {protocol.command(protocol.OP_SUPER_MIC, protocol.DIR_RESPONSE)},
    protocol.OP_SPATIAL_GET: {protocol.command(protocol.OP_SPATIAL_GET, protocol.DIR_RESPONSE)},
    protocol.OP_CODEC: {protocol.command(protocol.OP_CODEC, protocol.DIR_RESPONSE)},
    protocol.OP_FIT: {protocol.command(0x0D, protocol.DIR_EVENT)},
}


@dataclass
class GestureSlot:
    side: int
    common: int
    gesture: int
    action: int

    @property
    def label(self) -> str:
        return protocol.gesture_label(
            {"side": self.side, "common": self.common, "gesture": self.gesture, "action": self.action}
        )


@dataclass
class Snapshot:
    serial: str | None = None
    firmware: str | None = None
    battery: dict = field(default_factory=dict)
    anc: int | None = None
    eq: int | None = None
    custom_eq: tuple[float, float, float] | None = None
    bass_enabled: bool | None = None
    bass_level: int | None = None
    latency: bool | None = None
    in_ear: bool | None = None
    personalized_anc: bool | None = None
    super_mic: bool | None = None
    spatial: tuple[int, int] | None = None
    gestures: list[GestureSlot] = field(default_factory=list)
    device_codec: int | None = None
    notes: list[str] = field(default_factory=list)


class EarSession:
    def __init__(self, address: str, channel: int) -> None:
        self.address = address
        self.channel = channel
        self._socket = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        self._socket.settimeout(4)
        self._socket.connect((address, channel))
        self._socket.settimeout(0.25)
        self._parser = protocol.Parser()
        self._lock = threading.Lock()
        self._operation = 1

    def close(self) -> None:
        try:
            self._socket.close()
        except OSError:
            pass

    def _next_operation(self) -> int:
        operation = self._operation
        self._operation = 1 if operation >= 255 else operation + 1
        return operation

    def request(
        self,
        command_word: int,
        payload: bytes = b"",
        *,
        timeout: float = 1.6,
        accept: set[int] | None = None,
    ) -> protocol.Frame | None:
        with self._lock:
            packet = protocol.encode(command_word, payload, self._next_operation())
            self._socket.sendall(packet)
            deadline = time.monotonic() + timeout
            opcode = command_word & 0xFF
            while time.monotonic() < deadline:
                try:
                    data = self._socket.recv(1024)
                except socket.timeout:
                    continue
                if not data:
                    return None
                for frame in self._parser.feed(data):
                    if accept is not None:
                        if frame.command in accept:
                            return frame
                    elif frame.opcode == opcode and frame.direction in (
                        protocol.DIR_RESPONSE,
                        protocol.DIR_ACK,
                        protocol.DIR_EVENT,
                    ):
                        return frame
            return None

    def write(self, command_word: int, payload: bytes = b"") -> None:
        """Send a setting. A missing ack is still success: several models only notify later."""
        frame = self.request(command_word, payload, timeout=0.6)
        del frame

    def _read(self, opcode: int, payload: bytes = b"", timeout: float = 1.4) -> protocol.Frame | None:
        return self.request(
            protocol.command(opcode, protocol.DIR_GET),
            payload,
            timeout=timeout,
            accept=READ_ALIASES.get(opcode),
        )

    def snapshot(self, model: Model | None) -> Snapshot:
        state = Snapshot()
        # A device-info read wakes a fresh session. Later reads are ignored without it.
        self._read(protocol.OP_SERIAL, timeout=1.8)
        serial = self._read(protocol.OP_SERIAL)
        if serial is not None:
            state.serial = protocol.parse_serial(serial.payload)
        firmware = self._read(protocol.OP_FIRMWARE)
        if firmware is not None:
            state.firmware = protocol.parse_firmware(firmware.payload)
        battery = self._read(protocol.OP_BATTERY)
        if battery is not None:
            state.battery = protocol.parse_battery(battery.payload)
        anc = self._read(protocol.OP_ANC_GET)
        if anc is not None:
            state.anc = protocol.parse_anc(anc.payload)
        eq = self._read(protocol.OP_EQ_GET)
        if eq is not None and eq.payload:
            state.eq = eq.payload[0]
        custom = self._read(protocol.OP_CUSTOM_EQ)
        if custom is not None:
            state.custom_eq = protocol.decode_custom_eq(custom.payload)
        bass = self._read(protocol.OP_BASS)
        if bass is not None and bass.payload:
            state.bass_enabled = bass.payload[0] > 0
            if len(bass.payload) > 1:
                state.bass_level = bass.payload[1] // 2
        latency = self._read(protocol.OP_LATENCY_GET)
        if latency is not None and latency.payload:
            state.latency = latency.payload[0] == 1
        in_ear = self._read(protocol.OP_IN_EAR)
        if in_ear is not None and len(in_ear.payload) >= 3:
            state.in_ear = in_ear.payload[2] == 1
        personal = self._read(protocol.OP_PERSONAL_ANC)
        if personal is not None and personal.payload:
            state.personalized_anc = personal.payload[0] == 1
        mic = self._read(protocol.OP_SUPER_MIC)
        if mic is not None and mic.payload:
            state.super_mic = mic.payload[0] == 1
        spatial = self._read(protocol.OP_SPATIAL_GET)
        if spatial is not None and len(spatial.payload) >= 2:
            state.spatial = (spatial.payload[0], spatial.payload[1])
        elif spatial is not None and spatial.payload:
            state.spatial = (spatial.payload[0], 0)
        gestures = self._read(protocol.OP_GESTURE_GET)
        if gestures is not None:
            state.gestures = [GestureSlot(**slot) for slot in protocol.parse_gestures(gestures.payload)]
        codec = self._read(protocol.OP_CODEC)
        if codec is not None and codec.payload:
            state.device_codec = codec.payload[0]
        if not state.battery and state.firmware is None and state.anc is None:
            state.notes.append("The control channel answered, but no earbud status came back.")
        if model is None:
            state.notes.append("The Bluetooth name did not match a known Nothing or CMF model. Controls still follow what the earbuds report.")
        return state

    def set_anc(self, mode: int) -> None:
        self.write(protocol.command(protocol.OP_ANC, protocol.DIR_SET), protocol.anc_payload(mode))

    def set_eq(self, preset: int) -> None:
        self.write(protocol.command(protocol.OP_EQ, protocol.DIR_SET), bytes((preset & 0xFF, 0x00)))

    def set_custom_eq(self, bass: float, mid: float, treble: float, profile: str) -> None:
        payload = protocol.encode_custom_eq(bass, mid, treble, profile)
        self.write(protocol.command(protocol.OP_CUSTOM_EQ_SET, protocol.DIR_SET), payload)
        self.set_eq(0x05)

    def set_bass(self, enabled: bool, level: int) -> None:
        self.write(protocol.command(protocol.OP_BASS_SET, protocol.DIR_SET), protocol.bass_payload(enabled, level))

    def set_latency(self, enabled: bool) -> None:
        self.write(protocol.command(protocol.OP_LATENCY, protocol.DIR_SET), protocol.latency_payload(enabled))

    def set_in_ear(self, enabled: bool) -> None:
        self.write(protocol.command(protocol.OP_IN_EAR, protocol.DIR_SET), protocol.in_ear_payload(enabled))

    def set_personalized_anc(self, enabled: bool) -> None:
        value = b"\x01" if enabled else b"\x00"
        self.write(protocol.command(protocol.OP_PERSONAL_ANC_SET, protocol.DIR_SET), value)

    def set_super_mic(self, enabled: bool) -> None:
        value = b"\x01" if enabled else b"\x00"
        self.write(protocol.command(protocol.OP_SUPER_MIC_SET, protocol.DIR_SET), value)

    def set_spatial(self, first: int, second: int) -> None:
        self.write(protocol.command(protocol.OP_SPATIAL, protocol.DIR_SET), bytes((first & 0xFF, second & 0xFF)))

    def set_gesture(self, slot: GestureSlot, action: int) -> None:
        payload = bytes((0x01, slot.side & 0xFF, slot.common & 0xFF, slot.gesture & 0xFF, action & 0xFF))
        self.write(protocol.command(protocol.OP_GESTURE, protocol.DIR_SET), payload)

    def ring(self, side: int, enabled: bool, *, ear1: bool) -> None:
        self.write(
            protocol.command(protocol.OP_RING, protocol.DIR_SET),
            protocol.ring_payload(side, enabled, ear1=ear1),
        )

    def start_fit_test(self) -> protocol.Frame | None:
        self.write(protocol.command(protocol.OP_FIT, protocol.DIR_SET), b"\x01")
        return self.request(
            protocol.command(protocol.OP_FIT, protocol.DIR_SET),
            b"\x00",
            timeout=8,
            accept={protocol.command(0x0D, protocol.DIR_EVENT)},
        )

    def set_case_color(self, red: int, green: int, blue: int) -> None:
        payload = bytes((0x01, 0x01, red & 0xFF, green & 0xFF, blue & 0xFF))
        self.write(protocol.command(protocol.OP_LED, protocol.DIR_SET), payload)


# Nothing's own serial port, seen on CMF Buds Neo. Channel 15 is the older
# port and these buds refuse it.
VENDOR_SPP_UUID = "aeac4a03-dff5-498f-843a-34487cf133eb"


def spp_channels(address: str) -> list[int]:
    vendor: list[int] = []
    others: list[int] = []
    try:
        result = subprocess.run(
            ["sdptool", "browse", address],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        text = result.stdout or ""
    except (OSError, subprocess.SubprocessError):
        text = ""
    pending_vendor = False
    pending_serial = False
    for line in text.splitlines():
        lowered = line.casefold()
        if "uuid 128:" in lowered or "service class" in lowered or "service name:" in lowered:
            if VENDOR_SPP_UUID in lowered:
                pending_vendor = True
            if any(word in lowered for word in ("serial", "spp", "nothing", "cmf")):
                pending_serial = True
        match = re.search(r"Channel:\s*(\d+)", line)
        if not match:
            continue
        number = int(match.group(1))
        if pending_vendor and number not in vendor:
            vendor.append(number)
        elif pending_serial and number not in others:
            others.append(number)
        pending_vendor = False
        pending_serial = False
    ordered: list[int] = []
    for number in (*vendor, 6, *others, 15, 1):
        if number not in ordered:
            ordered.append(number)
    return ordered


def open_session(address: str) -> EarSession:
    errors: list[str] = []
    for channel in spp_channels(address):
        session: EarSession | None = None
        try:
            session = EarSession(address, channel)
            probe = session._read(protocol.OP_SERIAL, timeout=1.6)
            if probe is None:
                probe = session._read(protocol.OP_BATTERY, timeout=1.2)
            if probe is None:
                raise OSError(f"channel {channel} did not answer")
            return session
        except OSError as exc:
            errors.append(f"{channel}: {exc}")
            if session is not None:
                session.close()
    detail = "; ".join(errors) or "no serial channel"
    raise OSError(f"Could not open the earbud control channel ({detail})")
