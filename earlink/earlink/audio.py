"""PipeWire / Pulse card profiles for a connected Bluetooth headset."""

from __future__ import annotations

import re
import subprocess


def _pactl(*args: str) -> str:
    try:
        result = subprocess.run(
            ["pactl", *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout if result.returncode == 0 else ""


def card_name(address: str) -> str:
    return "bluez_card." + address.replace(":", "_")


def codec_profiles(address: str) -> list[dict[str, str]]:
    text = _pactl("list", "cards")
    if not text:
        return []
    wanted = card_name(address)
    block = ""
    for part in re.split(r"(?=^Card #)", text, flags=re.MULTILINE):
        if re.search(r"^\s*Name:\s*" + re.escape(wanted) + r"\s*$", part, re.MULTILINE):
            block = part
            break
    if not block:
        return []
    found: list[dict[str, str]] = []
    in_profiles = False
    for line in block.splitlines():
        stripped = line.strip()
        if stripped == "Profiles:":
            in_profiles = True
            continue
        if in_profiles and stripped.startswith("Active Profile:"):
            break
        if not in_profiles:
            continue
        match = re.match(r"\s*([^:]+):\s*(.*)", line)
        if not match:
            continue
        profile = match.group(1).strip()
        description = match.group(2).strip()
        if "a2dp" not in profile and "headset" not in profile:
            continue
        found.append({"profile": profile, "label": description or profile})
    return found


def active_profile(address: str) -> str | None:
    text = _pactl("list", "cards")
    wanted = card_name(address)
    in_card = False
    for line in text.splitlines():
        if re.match(r"^\s*Name:\s*" + re.escape(wanted) + r"\s*$", line):
            in_card = True
            continue
        if in_card and line.startswith("Card #"):
            break
        if in_card:
            match = re.match(r"\s*Active Profile:\s*(\S+)", line)
            if match:
                return match.group(1)
    return None


def set_profile(address: str, profile: str) -> None:
    result = subprocess.run(
        ["pactl", "set-card-profile", card_name(address), profile],
        capture_output=True,
        text=True,
        timeout=6,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "pactl failed").strip()
        raise OSError(detail)
