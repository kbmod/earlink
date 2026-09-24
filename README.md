# Ear Link for CMF Buds Neo

Linux companion for **CMF Buds Neo**. It brings the listening controls from the Android and iOS Nothing X app to your desktop, so you can pair the buds to this computer and change how they sound and how the buttons behave without the phone. It is not the official Nothing X app.

Those listening controls are noise cancellation (off, high, medium, low, adaptive, and transparency), spatial audio, bass enhance, low latency, and the press gestures on each bud. Ear Link also shows battery, firmware version, and serial number, and it can ring the buds or run the ear-tip fit test.

Buds Neo do not have a pairing button. Opening the case is what makes them visible.

## Install

The package is `earlink_1.0.0_all.deb` in this directory.

```sh
sudo dpkg -i earlink_1.0.0_all.deb
```

It needs BlueZ, Python 3, GTK 4, and libadwaita. PipeWire (or PulseAudio) is used for the audio profile.

Bluetooth has to be enabled in the firmware and switched on. This machine’s adapter is the MediaTek controller that shows up as `hci0`.

Launch **Ear Link** from the app menu, or run `earlink`. After installing a new package, quit the app and open it again.

## Pair

1. Open the Buds Neo case and leave it open next to the computer.
2. In Ear Link, press **Scan**.
3. Choose **CMF Buds Neo** and press **Pair**.
4. Accept the desktop Bluetooth prompt.

The buds use the address prefix `2C:BE:EB`. After pairing they show up as `CMF Buds Neo`. Press **Connect** if they are paired but not connected, then **Controls**.

If nothing appears, tick **Show every nearby Bluetooth device**. A closed case will not show up, and a scan while the case is shut times out.

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
- The computer’s Bluetooth audio profile (SBC, AAC, and whatever else PipeWire negotiated).

Equalizer presets are on the Sound page. Buds Neo’s own sound profiles in the official app are Dirac Opteo; this app sends the standard Nothing equalizer instead, and a preset the buds ignore will not change the sound.

## Not available here

Buds Neo does not use every screen in Nothing X. These stay on the phone:

- Dirac Opteo, which is this model’s equalizer. The Sound page can still send the older Nothing presets, and the buds may ignore them.
- Firmware updates
- The dual-connection list of the other paired device. This computer can still be one of the two devices the buds connect to.
- Magic Button, Essential Space, and voice-memo transcription
- In-ear detection. Buds Neo does not report that setting.

## Rebuild the package

```sh
earlink/packaging/build-deb.sh
sudo dpkg -i earlink_1.0.0_all.deb
```

Protocol checks, including a captured Buds Neo battery frame:

```sh
cd earlink && PYTHONPATH=. python3 -m unittest tests.test_protocol
```
