"""Tests for utility functions."""

from bluetooth_dualboot.utils import mac_to_windows_key, normalize_mac, reverse_hex_key


def test_normalize_mac_colons():
    assert normalize_mac("c0:35:32:ac:13:4a") == "C0:35:32:AC:13:4A"


def test_normalize_mac_no_sep():
    assert normalize_mac("c03532ac134a") == "C0:35:32:AC:13:4A"


def test_normalize_mac_dashes():
    assert normalize_mac("C0-35-32-AC-13-4A") == "C0:35:32:AC:13:4A"


def test_mac_to_windows_key():
    assert mac_to_windows_key("C0:35:32:AC:13:4A") == "c03532ac134a"


def test_mac_to_windows_key_no_sep():
    assert mac_to_windows_key("c03532ac134a") == "c03532ac134a"


def test_reverse_hex_key_known_pair():
    """Verify the Linux↔Windows byte-reversal for our real LTK values."""
    linux_ltk = "6AA1ACBA40F3DDB60C78FA7C3B23A709"
    windows_ltk = bytes.fromhex("09A7233B7CFA780CB6DDF340BAACA16A")
    assert reverse_hex_key(linux_ltk) == windows_ltk


def test_reverse_hex_key_irk():
    """Verify the Linux↔Windows byte-reversal for our real IRK values."""
    linux_irk = "9CA8DC498406FE2496D9355156612611"
    windows_irk = bytes.fromhex("112661565135D99624FE068449DCA89C")
    assert reverse_hex_key(linux_irk) == windows_irk


def test_reverse_hex_key_roundtrip():
    """Reversing twice should give back the original bytes."""
    key = "DEADBEEF01234567AABBCCDD11223344"
    result = reverse_hex_key(key)
    assert reverse_hex_key(result.hex().upper()) == bytes.fromhex(key)
