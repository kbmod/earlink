import unittest

from earlink.catalog import looks_like_earbud, match_model
from earlink.protocol import (
    Parser,
    crc16,
    decode_custom_eq,
    encode,
    encode_custom_eq,
    parse_anc,
    parse_battery,
    parse_gestures,
    parse_serial,
)


class ProtocolTests(unittest.TestCase):
    def test_known_anc_and_latency_frames(self):
        transparency = encode(0xF00F, bytes((0x01, 0x07, 0x00)), operation=0xCB)
        self.assertEqual(transparency.hex(), "5560010ff00300cb010700c5af")
        off = encode(0xF00F, bytes((0x01, 0x05, 0x00)), operation=0xCD)
        self.assertEqual(off.hex(), "5560010ff00300cd010500c447")
        latency_on = encode(0xF040, bytes((0x01, 0x00)), operation=0x27)
        self.assertEqual(latency_on.hex(), "55600140f0020027010097f7")
        in_ear = encode(0xF004, bytes((0x01, 0x01, 0x01)), operation=0x26)
        self.assertEqual(in_ear.hex(), "55600104f00300260101017310")
        firmware = encode(0xC042, b"", operation=0x03)
        self.assertEqual(firmware.hex(), "55600142c0000003e0d1")
        serial = encode(0xC006, b"", operation=0x05)
        self.assertEqual(serial.hex(), "55600106c000000590dc")

    def test_crc_matches_the_published_vector(self):
        body = bytes((0x55, 0x60, 0x01, 0x34, 0x12, 0x02, 0x00, 0x01, 0xAA, 0xBB))
        self.assertEqual(crc16(body), 0xFA6A)

    def test_buds_neo_response_without_modbus_crc(self):
        # Captured from CMF Buds Neo on the vendor serial port. The payload is
        # three batteries at 100 percent; the trailing checksum is not MODBUS.
        frame = bytes.fromhex("5560010740070002030264036404641a9a")
        parsed = Parser().feed(frame)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].command, 0x4007)
        battery = parse_battery(parsed[0].payload)
        self.assertEqual(battery["left"]["level"], 100)
        self.assertEqual(battery["right"]["level"], 100)
        self.assertEqual(battery["case"]["level"], 100)

    def test_parser_resynchronises(self):
        good = encode(0xC007, b"\x01\x02", operation=4)
        parser = Parser()
        frames = parser.feed(b"\xff\xff" + good[:4])
        self.assertEqual(frames, [])
        frames = parser.feed(good[4:])
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].command, 0xC007)
        self.assertEqual(frames[0].payload, b"\x01\x02")

    def test_battery_anc_gestures_and_serial(self):
        battery = parse_battery(bytes((0x03, 0x02, 0x40, 0x03, 0x9A, 0x04, 0x32)))
        self.assertEqual(battery["left"]["level"], 64)
        self.assertFalse(battery["left"]["charging"])
        self.assertEqual(battery["right"]["level"], 26)
        self.assertTrue(battery["right"]["charging"])
        self.assertEqual(battery["case"]["level"], 50)
        self.assertEqual(parse_anc(bytes((0x01, 0x07, 0x00))), 0x07)
        slots = parse_gestures(bytes((0x01, 0x02, 0x01, 0x02, 0x09)))
        self.assertEqual(slots[0]["action"], 9)
        text = b"\x00" * 7 + b"x,4,SH10182307002807\n"
        self.assertEqual(parse_serial(text), "SH10182307002807")

    def test_custom_eq_round_trip(self):
        payload = encode_custom_eq(bass=-2, mid=3, treble=1, profile="3400")
        bass, mid, treble = decode_custom_eq(payload)
        self.assertAlmostEqual(bass, -2, places=2)
        self.assertAlmostEqual(mid, 3, places=2)
        self.assertAlmostEqual(treble, 1, places=2)
        # 980 Hz is the mid band used by the official app, stored byte-swapped.
        self.assertEqual(payload[10:14].hex(), "00007544")

    def test_model_matching_prefers_the_longer_name(self):
        self.assertEqual(match_model("Nothing Ear (2)").model_id, "B155")
        self.assertEqual(match_model("CMF Buds Pro 2").model_id, "B172")
        self.assertEqual(match_model("CMF Buds").model_id, "B168")
        self.assertEqual(match_model("Nothing Ear").model_id, "B171")
        self.assertTrue(looks_like_earbud("Headphones", "2C:BE:EB:10:20:30"))
        self.assertFalse(looks_like_earbud("Keyboard", "AA:BB:CC:DD:EE:FF"))


if __name__ == "__main__":
    unittest.main()
