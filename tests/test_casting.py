import unittest

from mirror_backend.casting import _cache_key_for_serial


class CacheKeyForSerialTests(unittest.TestCase):
    def test_wifi_serial_is_safe_for_windows_directory(self):
        self.assertEqual(
            _cache_key_for_serial("192.168.1.25:5555"),
            "192.168.1.25%3A5555",
        )

    def test_usb_serial_keeps_existing_cache_directory(self):
        self.assertEqual(_cache_key_for_serial("1WMHH123456789"), "1WMHH123456789")

    def test_different_serials_do_not_collapse_to_same_directory(self):
        self.assertNotEqual(
            _cache_key_for_serial("192.168.1.25:5555"),
            _cache_key_for_serial("192.168.1.25_5555"),
        )


if __name__ == "__main__":
    unittest.main()
