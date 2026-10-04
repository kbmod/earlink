import ctypes
import socket
import unittest
from unittest.mock import Mock, patch

from earlink import protocol, session, windows


class WindowsTests(unittest.TestCase):
    def test_native_socket_address_matches_windows_sdk(self):
        self.assertEqual(ctypes.sizeof(windows.SockaddrBth), 30)
        self.assertEqual(windows.SockaddrBth.address.offset, 2)
        self.assertEqual(windows.SockaddrBth.service.offset, 10)
        self.assertEqual(windows.SockaddrBth.port.offset, 26)

    def test_address_byte_order_and_validation(self):
        address = "2C:BE:EB:10:20:30"
        self.assertEqual(windows.address_number(address), 0x2CBEEB102030)
        self.assertEqual(windows.address_text(windows.address_number(address)), address)
        for invalid in ("bad", "2C:BE:EB:10:20", "2C:BE:EB:10:20:30:40"):
            with self.assertRaises(ValueError):
                windows.address_number(invalid)

    def test_windows_session_uses_vendor_service_and_shared_protocol(self):
        transport = Mock()
        transport.recv.return_value = protocol.encode(
            protocol.command(protocol.OP_ANC_GET, protocol.DIR_RESPONSE), b"\x01\x07\x00")
        with patch.object(session.sys, "platform", "win32"), patch.object(
            windows, "connect_socket", return_value=transport
        ) as connect:
            ear = session.EarSession("2C:BE:EB:10:20:30", 0)
            connect.assert_called_once_with(ear.address, 0, service=session.VENDOR_SPP_UUID)
            frame = ear._read(protocol.OP_ANC_GET)
            self.assertEqual(protocol.parse_anc(frame.payload), 7)
            sent = protocol.Parser().feed(transport.sendall.call_args.args[0])[0]
            self.assertEqual(sent.command, protocol.command(protocol.OP_ANC_GET, protocol.DIR_GET))
            ear.close()
            transport.close.assert_called_once()

    def test_probe_failure_closes_session_before_fallback(self):
        first, second = Mock(), Mock()
        first._read.return_value = None
        second._read.return_value = protocol.Frame(0x4006, 1, b"serial")
        with patch.object(session, "spp_channels", return_value=[0, 6]), patch.object(
            session, "EarSession", side_effect=[first, second]
        ):
            self.assertIs(session.open_session("2C:BE:EB:10:20:30"), second)
            first.close.assert_called_once()
            second.close.assert_not_called()

    @unittest.skipUnless(hasattr(ctypes, "WinDLL"), "Windows native API")
    def test_native_connect_timeout_closes_socket(self):
        api = Mock()
        api.connect.return_value = -1
        api.WSAGetLastError.return_value = 10035
        transport = Mock()
        with patch.object(ctypes, "WinDLL", return_value=api), patch.object(
            windows.socket, "socket", return_value=transport
        ), patch.object(windows.select, "select", return_value=([], [], [])):
            with self.assertRaises(socket.timeout):
                windows.connect_socket("2C:BE:EB:10:20:30", 6)
            transport.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
