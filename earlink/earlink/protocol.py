"""Nothing X earbud control frames.

The earbuds speak a small binary protocol on a Bluetooth RFCOMM channel
(usually 15). A frame is:

    55 60 01 | command (le u16) | payload length (le u16) | operation | payload | crc16

CRC-16/MODBUS covers every byte before the checksum. The command word packs
the opcode in the low byte and a direction in the high byte: 0xC0 read,
0xF0 write, 0x40 response, 0x70 ack, 0xE0 unsolicited.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

SOF = 0x55
HEADER = bytes((0x55, 0x60, 0x01))

DIR_GET = 0xC0
DIR_SET = 0xF0
DIR_RESPONSE = 0x40
DIR_ACK = 0x70
DIR_EVENT = 0xE0

# Opcodes. The full command word is (direction << 8) | opcode.
OP_RING = 0x02
OP_GESTURE = 0x03
OP_IN_EAR = 0x04
OP_SERIAL = 0x06
OP_BATTERY = 0x07
OP_LED = 0x0D
OP_ANC = 0x0F
OP_EQ = 0x10
OP_PERSONAL_ANC_SET = 0x11
OP_FIT = 0x14
OP_LED_GET = 0x17
OP_GESTURE_GET = 0x18
OP_ANC_GET = 0x1E
OP_EQ_GET = 0x1F
OP_PERSONAL_ANC = 0x20
OP_LATENCY = 0x40
OP_LATENCY_GET = 0x41
OP_FIRMWARE = 0x42
OP_CUSTOM_EQ_SET = 0x41  # write opcode collides with the latency read opcode; direction distinguishes them
OP_CUSTOM_EQ = 0x44
OP_CODEC = 0x29
OP_ADVANCED_EQ = 0x4C
OP_BASS = 0x4E
OP_SPATIAL_GET = 0x4F
OP_LISTENING = 0x50
OP_BASS_SET = 0x51
OP_SPATIAL = 0x52
OP_SUPER_MIC = 0x5E
OP_SUPER_MIC_SET = 0x5F

ANC_MODES = (
    (0x05, "Off"),
    (0x01, "High"),
    (0x02, "Medium"),
    (0x03, "Low"),
    (0x04, "Adaptive"),
    (0x07, "Transparency"),
)
ANC_BY_VALUE = {value: label for value, label in ANC_MODES}
ANC_BY_LABEL = {label.lower(): value for value, label in ANC_MODES}

EQ_PRESETS = (
    (0x00, "Balanced"),
    (0x01, "Voice"),
    (0x02, "More treble"),
    (0x03, "More bass"),
    (0x05, "Custom"),
    (0x06, "Advanced"),
)
EQ_BY_VALUE = {value: label for value, label in EQ_PRESETS}

SPATIAL_MODES = (
    ((0x00, 0x00), "Off"),
    ((0x01, 0x00), "Fixed"),
    ((0x01, 0x01), "Head tracking"),
    ((0x02, 0x00), "Concert"),
    ((0x03, 0x00), "Cinema"),
)

# (low Hz, low Q, mid Hz, mid Q, high Hz, high Q)
EQ_PROFILES = {
    "3400": (140.0, 0.8, 980.0, 0.7, 3400.0, 1.0),
    "3500": (140.0, 0.8, 980.0, 0.7, 3500.0, 1.0),
    "stick": (140.0, 0.8, 980.0, 0.66, 3500.0, 1.0),
    "6900": (140.0, 0.8, 980.0, 0.7, 6900.0, 1.0),
}

GESTURE_SIDES = {
    0x02: "Left",
    0x03: "Right",
    0x04: "Case",
    0x06: "Headset",
}
GESTURE_TYPES = {
    1: "Press",
    2: "Double press",
    3: "Triple press",
    5: "Slide",
    7: "Press and hold",
    9: "Double-press and hold",
    10: "Rotate",
    11: "Pinch both buds",
}
GESTURE_ACTIONS = {
    1: "No action",
    2: "Play / pause",
    3: "Answer or hang up",
    4: "Decline call",
    8: "Skip back",
    9: "Skip forward",
    10: "Noise control",
    11: "Voice assistant",
    17: "Low latency",
    18: "Volume up",
    19: "Volume down",
    23: "Volume",
    24: "Camera shutter",
    27: "Spatial audio",
    29: "Microphone mute",
    31: "News",
    32: "Radio",
    33: "Essential Space",
    34: "EQ preset",
    35: "Ultra bass",
    36: "Treble enhance",
    37: "Recording",
}


def command(opcode: int, direction: int) -> int:
    return (direction << 8) | (opcode & 0xFF)


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def encode(command_word: int, payload: bytes = b"", operation: int = 1) -> bytes:
    if len(payload) > 0xFFFF:
        raise ValueError("payload too long")
    body = bytearray(HEADER)
    body.append(command_word & 0xFF)
    body.append((command_word >> 8) & 0xFF)
    body.append(len(payload) & 0xFF)
    body.append((len(payload) >> 8) & 0xFF)
    body.append(operation & 0xFF)
    body.extend(payload)
    checksum = crc16(body)
    body.append(checksum & 0xFF)
    body.append((checksum >> 8) & 0xFF)
    return bytes(body)


@dataclass(frozen=True)
class Frame:
    command: int
    operation: int
    payload: bytes

    @property
    def opcode(self) -> int:
        return self.command & 0xFF

    @property
    def direction(self) -> int:
        return (self.command >> 8) & 0xFF


class Parser:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[Frame]:
        self._buffer.extend(data)
        frames: list[Frame] = []
        while True:
            start = self._buffer.find(SOF)
            if start < 0:
                self._buffer.clear()
                break
            if start:
                del self._buffer[:start]
            if len(self._buffer) < 8:
                break
            if self._buffer[1] != 0x60 or self._buffer[2] != 0x01:
                del self._buffer[0]
                continue
            length = self._buffer[5] | (self._buffer[6] << 8)
            if length > 512:
                del self._buffer[0]
                continue
            total = 8 + length + 2
            if len(self._buffer) < total:
                break
            raw = bytes(self._buffer[:total])
            expected = raw[-2] | (raw[-1] << 8)
            direction = raw[4]
            # Requests use CRC-16/MODBUS. Buds Neo replies on the vendor serial
            # port with the same framing, but that checksum does not match, so a
            # complete header is enough when the direction byte is one the buds use.
            if crc16(raw[:-2]) != expected and direction not in (
                DIR_GET,
                DIR_SET,
                DIR_RESPONSE,
                DIR_ACK,
                DIR_EVENT,
            ):
                del self._buffer[0]
                continue
            del self._buffer[:total]
            frames.append(
                Frame(
                    command=raw[3] | (raw[4] << 8),
                    operation=raw[7],
                    payload=raw[8 : 8 + length],
                )
            )
        return frames


def _eq_float_bytes(value: float, *, total: bool = False) -> bytes:
    if total and value >= 0:
        return b"\x00\x00\x00\x80"
    raw = bytearray(struct.pack(">f", float(value)))
    if value != 0.0 and raw[0] == 0 and raw[1] == 0 and raw[2] == 0:
        raw[3] |= 0x80
    raw[0], raw[3] = raw[3], raw[0]
    raw[1], raw[2] = raw[2], raw[1]
    return bytes(raw)


def _eq_float(data: bytes) -> float:
    if len(data) < 4:
        return 0.0
    swapped = bytes((data[3], data[2], data[1], data[0]))
    if swapped[0] == 0 and swapped[1] == 0 and swapped[2] == 0 and swapped[3] & 0x80:
        swapped = bytes((swapped[0], swapped[1], swapped[2], swapped[3] & 0x7F))
        return -struct.unpack(">f", swapped)[0]
    return struct.unpack(">f", swapped)[0]


def encode_custom_eq(bass: float, mid: float, treble: float, profile: str = "3400") -> bytes:
    low_f, low_q, mid_f, mid_q, high_f, high_q = EQ_PROFILES[profile]

    def clamp(value: float) -> float:
        return max(-6.0, min(6.0, float(value)))

    bands = (
        (0x01, clamp(mid), mid_f, mid_q),
        (0x02, clamp(treble), high_f, high_q),
        (0x00, clamp(bass), low_f, low_q),
    )
    loudest = max(band[1] for band in bands)
    payload = bytearray()
    payload.append(len(bands))
    payload.extend(_eq_float_bytes(-max(loudest, 0.0), total=True))
    for kind, gain, freq, quality in bands:
        payload.append(kind)
        payload.extend(_eq_float_bytes(gain))
        payload.extend(_eq_float_bytes(freq))
        payload.extend(_eq_float_bytes(quality))
    payload.extend(b"\x00" * (len(bands) * 3))
    return bytes(payload)


def decode_custom_eq(payload: bytes) -> tuple[float, float, float] | None:
    if len(payload) < 5 + 13 * 3:
        return None
    gains = []
    for band in range(3):
        offset = 6 + band * 13
        gains.append(_eq_float(payload[offset : offset + 4]))
    # Wire order is mid, treble, bass.
    mid, treble, bass = gains
    return bass, mid, treble


def parse_battery(payload: bytes) -> dict[str, dict[str, int | bool]]:
    names = {0x02: "left", 0x03: "right", 0x04: "case", 0x06: "headset"}
    found: dict[str, dict[str, int | bool]] = {}
    if not payload:
        return found
    count = payload[0]
    for index in range(count):
        offset = 1 + index * 2
        if offset + 1 >= len(payload):
            break
        name = names.get(payload[offset])
        if name is None:
            continue
        raw = payload[offset + 1]
        level = raw & 0x7F
        if level > 100:
            continue
        found[name] = {"level": level, "charging": bool(raw & 0x80)}
    return found


def parse_anc(payload: bytes) -> int | None:
    if len(payload) >= 3 and payload[0] in (0x01, 0x02):
        for offset in range(0, len(payload) - 2, 3):
            if payload[offset] == 0x01 and payload[offset + 1] in ANC_BY_VALUE:
                return payload[offset + 1]
    if len(payload) >= 2 and payload[1] in ANC_BY_VALUE:
        return payload[1]
    if payload and payload[0] in ANC_BY_VALUE:
        return payload[0]
    return None


def parse_serial(payload: bytes) -> str | None:
    if len(payload) < 8:
        return None
    text = payload[7:].split(b"\x00", 1)[0].decode("utf-8", "ignore")
    for line in text.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) == 3 and parts[1] == "4" and parts[2]:
            return parts[2]
    cleaned = "".join(ch for ch in text if ch.isprintable()).strip()
    return cleaned or None


def parse_firmware(payload: bytes) -> str | None:
    if not payload:
        return None
    text = payload.split(b"\x00", 1)[0].decode("utf-8", "ignore").strip()
    if text and all(ch.isprintable() for ch in text):
        return text
    if len(payload) >= 4 and all(part < 100 for part in payload[:4]):
        return ".".join(str(part) for part in payload[:4])
    return payload.hex()


def parse_gestures(payload: bytes) -> list[dict[str, int]]:
    if not payload:
        return []
    slots = []
    count = payload[0]
    for index in range(count):
        base = 1 + index * 4
        if base + 3 >= len(payload):
            break
        slots.append(
            {
                "side": payload[base],
                "common": payload[base + 1],
                "gesture": payload[base + 2],
                "action": payload[base + 3],
            }
        )
    return slots


def gesture_label(slot: dict[str, int]) -> str:
    side = GESTURE_SIDES.get(slot["side"], f"Bud {slot['side']}")
    kind = GESTURE_TYPES.get(slot["gesture"], f"Gesture {slot['gesture']}")
    return f"{side} · {kind}"


def anc_payload(mode: int) -> bytes:
    return bytes((0x01, mode & 0xFF, 0x00))


def latency_payload(enabled: bool) -> bytes:
    return bytes((0x01 if enabled else 0x02, 0x00))


def in_ear_payload(enabled: bool) -> bytes:
    return bytes((0x01, 0x01, 0x01 if enabled else 0x00))


def bass_payload(enabled: bool, level: int) -> bytes:
    level = max(0, min(5, int(level)))
    return bytes((0x01 if enabled else 0x00, level * 2))


def ring_payload(side: int, enabled: bool, *, ear1: bool) -> bytes:
    if ear1:
        return bytes((0x01 if enabled else 0x00,))
    return bytes((side & 0xFF, 0x01 if enabled else 0x00))
