# Ear Link for CMF Buds Neo

Linux and Windows companion for **CMF Buds Neo**. It brings the listening controls from the Android and iOS Nothing X app to your desktop, so you can pair the buds to this computer and change how they sound and how the buttons behave without the phone. It is not the official Nothing X app.

Available listening controls are noise cancellation (off, high, medium, low, adaptive, and transparency), spatial audio, bass enhance, low latency, and the press gestures on each bud. Ear Link also shows battery, firmware version, and serial number, and it can ring the buds or run the ear-tip fit test.

## Downloads

| Platform | Download |
| --- | --- |
| Windows x64 | [EarLink.exe](https://github.com/kbmod/earlink/releases/latest/download/EarLink.exe) — portable; Python is included |
| Debian | [earlink_1.0.0_all.deb](https://github.com/kbmod/earlink/releases/latest/download/earlink_1.0.0_all.deb) |

See [all releases](https://github.com/kbmod/earlink/releases). The existing Debian
release predates Immersion Boost support; rebuild from current source below to
get the new presets on Debian.

Buds Neo do not have a case pairing button. To pair a new device, take both
buds out and hold both touch controls together for about five seconds until
pairing starts, then release. Opening the case alone may reconnect them to an
existing device without making them discoverable to a new one.

## Windows

The Windows version uses a native Tk desktop interface and Microsoft's Bluetooth
stack, sharing the same earbud protocol and controls with the Debian version.
It does not need GTK, BlueZ, a virtual COM port, or administrator access.

1. Download and run **EarLink.exe** from the link above. No installation is needed.
2. Put the buds in pairing mode as described above and click **Pair / Bluetooth settings**. Use Windows **Add device**
   to pair the earbuds and connect them for audio.
3. Return to Ear Link, click **Scan**, select the earbuds, and click **Connect controls**.

Noise control, battery, firmware, serial number, bass enhance, low latency,
spatial audio, EQ commands, gestures, ringing, and the fit test use the shared
protocol. Other model-specific switches are enabled only if the earbuds report
them. Windows manages audio outputs and codec negotiation; use **Sound settings**
for audio routing. **Close controls** closes the vendor connection; manage audio
disconnection and device removal in Windows Bluetooth Settings.

Windows uses the vendor service UUID to resolve the control channel, with the
known RFCOMM channels as fallbacks. Bluetooth hardware must support Microsoft's
Bluetooth Classic/RFCOMM stack. The executable and interface were tested on
Windows 11. Connecting to paired Buds Neo and changing Pop / Immersion Boost
were verified on the live Bluetooth control channel. Other controls share the
Debian protocol implementation; they have not all been retested on Windows.

If the buds do not appear, confirm pairing mode and temporarily turn off phone
Bluetooth. Search with Windows **Add device → Bluetooth** first. Run one scan
at a time; simultaneous Windows and Ear Link scans can report discovery as busy.

To run from source with Python 3.11 or later installed with Tcl/Tk:

```powershell
cd earlink
python -m earlink
```

To build a standalone Windows executable from the repository root:

```powershell
.\earlink\packaging\build-windows.ps1 -Python python
```

The script installs pinned PyInstaller dependencies into `build/windows-venv`
and writes `build/windows/EarLink.exe`. Build it on Windows; the resulting
executable needs no Python installation. Bluetooth pairing keys belong to each
OS installation, so switching between Debian and Windows may require pairing
again in that OS.

## Install on Debian

Download from releases.

```sh
#install deps
sudo apt install python3 python3-gi python3-dbus gir1.2-gtk-4.0 gir1.2-adw-1 bluez pipewire-pulse pulseaudio-utils
#install package
sudo dpkg -i earlink_1.0.0_all.deb
```

It needs BlueZ, Python 3, GTK 4, and libadwaita. PipeWire (or PulseAudio) is used for the audio profile.

Bluetooth has to be enabled in the firmware and switched on.

Launch **Ear Link** from the app menu, or run `earlink`. After installing a new package, quit the app and open it again.

## Pair

1. Take both buds out and hold both touch controls together for about five seconds until pairing starts.
2. In Ear Link, press **Scan**.
3. Choose **CMF Buds Neo** and press **Pair**.
4. Accept the desktop Bluetooth prompt.

After pairing they show up as `CMF Buds Neo`. Press **Connect** if they are paired but not connected, then **Controls**.

If nothing appears, tick **Show every nearby Bluetooth device** and re-enter
pairing mode. Temporarily turn off Bluetooth on a phone that might reconnect.

## Controls

On Buds Neo, **Controls** talks to Nothing’s vendor serial port (RFCOMM channel 6, service `aeac4a03-dff5-498f-843a-34487cf133eb`). The older channel 15 used by earlier Nothing earbuds is closed on this model.

These read and write against a paired Buds Neo:

- Battery for the left bud, right bud, and case. The case level updates while the case is open.
- Firmware version and serial number.
- Noise control: Off, High, Medium, Low, Adaptive, Transparency.
- Gestures for double press, triple press, press and hold, and double-press and hold, on each bud.
- Low latency.
- Bass enhance.
- Spatial audio: Off, Fixed, Head tracking, Concert, Cinema.
- Find the buds (ring left, ring right, or stop).
- Ear-tip fit test.
- On Debian, the computer’s Bluetooth audio profile (SBC, AAC, and whatever else PipeWire negotiated). Windows manages its own audio codec.

Equalizer presets are on the Sound page. Buds Neo offers **Immersion Boost**,
Pop, Rock, Classical, Electronic, and Enhance Vocals on both Windows and Debian.
Ear Link uses the CMF listening-mode command for these presets. Immersion Boost
was identified from the buds' reported mode `6` while selected in Nothing X;
switching to Pop and restoring Immersion Boost was verified by reading back
modes `3` and `6` from the connected buds. Other Nothing models retain their
existing EQ controls. Custom EQ is hidden for Buds Neo.

## Not available here

Buds Neo does not use every screen in Nothing X. These stay on the phone:

- Firmware updates
- The dual-connection list of the other paired device. This computer can still be one of the two devices the buds connect to.
- Magic Button, Essential Space, and voice-memo transcription
- In-ear detection. Buds Neo does not report that setting.

## Rebuild the Debian package

```sh
earlink/packaging/build-deb.sh
sudo dpkg -i earlink_1.0.0_all.deb
```

Run protocol and transport tests, including captured Buds Neo battery and
Immersion Boost responses:

```sh
cd earlink
python3 -m unittest discover -s tests -v
```

On Windows, use `python` instead of `python3`. Windows-only native API tests
are skipped on Linux. The updated GTK interface has not been runtime-tested
on Debian from this Windows checkout.
