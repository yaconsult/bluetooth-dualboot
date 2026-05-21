"""Tests for _find_ble_win_entry matching logic, including is_active preference."""

from bluetooth_dualboot.linux_bt import BLEKeys
from bluetooth_dualboot.sync import _find_ble_win_entry
from bluetooth_dualboot.windows_bt import WindowsBLEEntry


def _make_ble_keys(mac: str, irk: str) -> BLEKeys:
    return BLEKeys(
        adapter_mac="C0:35:32:AC:13:4A",
        device_mac=mac,
        device_name="Test Mouse",
        ltk="AA" * 16,
        ltk_ediv=0,
        ltk_rand=0,
        ltk_enc_size=16,
        irk=irk,
        address_type="static",
    )


def _make_win_entry(device_key: str, irk: bytes, is_active: bool = False) -> WindowsBLEEntry:
    return WindowsBLEEntry(
        adapter_key="c03532ac134a",
        device_key=device_key,
        ltk=b"\xaa" * 16,
        irk=irk,
        key_length=16,
        erand=0,
        ediv=0,
        csrk_inbound=None,
        csrk_outbound=None,
        inbound_sign_counter=0,
        outbound_sign_counter=0,
        address=0,
        address_type=1,
        auth_req=0x29,
        is_active=is_active,
    )


# Linux IRK "9D390DA8589DAA9F1D2B8AB67CF61744" reversed = "4417F67CB68A2B1D9FAA9D58A80D399D"
_LINUX_IRK = "9D390DA8589DAA9F1D2B8AB67CF61744"
_WIN_IRK_ACTIVE = bytes.fromhex("4417F67CB68A2B1D9FAA9D58A80D399D")
_WIN_IRK_STALE = bytes.fromhex("4417F67CB68A2B1D9FAA9D58A80D399D")  # same IRK, different entry


def test_prefers_active_irk_match_over_inactive():
    """When multiple entries share the same IRK, prefer the one marked active."""
    lk = _make_ble_keys("FA:73:88:BA:3B:FB", _LINUX_IRK)
    inactive = _make_win_entry("fa7388ba3bfb", _WIN_IRK_STALE, is_active=False)
    active = _make_win_entry("f6a2f5ec714b", _WIN_IRK_ACTIVE, is_active=True)

    result = _find_ble_win_entry(lk, [inactive, active])
    assert result is active


def test_prefers_active_irk_match_regardless_of_order():
    """Order of entries in list should not affect active-preference logic."""
    lk = _make_ble_keys("FA:73:88:BA:3B:FB", _LINUX_IRK)
    inactive = _make_win_entry("fa7388ba3bfb", _WIN_IRK_STALE, is_active=False)
    active = _make_win_entry("f6a2f5ec714b", _WIN_IRK_ACTIVE, is_active=True)

    # Active first
    assert _find_ble_win_entry(lk, [active, inactive]) is active
    # Active last
    assert _find_ble_win_entry(lk, [inactive, active]) is active


def test_falls_back_to_inactive_irk_match_when_no_active():
    """When no active entry matches, return the first inactive IRK match."""
    lk = _make_ble_keys("FA:73:88:BA:3B:FB", _LINUX_IRK)
    inactive = _make_win_entry("fa7388ba3bfb", _WIN_IRK_STALE, is_active=False)

    result = _find_ble_win_entry(lk, [inactive])
    assert result is inactive


def test_mac_match_used_when_no_irk():
    """Falls back to MAC match when IRK is absent."""
    lk = _make_ble_keys("FA:73:88:BA:3B:FB", "")
    mac_entry = _make_win_entry("fa7388ba3bfb", b"\x00" * 16, is_active=False)

    result = _find_ble_win_entry(lk, [mac_entry])
    assert result is mac_entry


def test_falls_back_to_sole_active_entry_when_irk_match_is_inactive():
    """When IRK matches an inactive entry but exactly one active entry exists,
    return the active entry — it is the device Windows re-paired and is using."""
    lk = _make_ble_keys("FA:73:88:BA:3B:FB", _LINUX_IRK)
    # Inactive entry has matching IRK (our previous sync wrote it there)
    inactive_irk_match = _make_win_entry("fa7388ba3bfb", _WIN_IRK_STALE, is_active=False)
    # Active entry has a different IRK (Windows re-paired independently)
    different_irk = bytes.fromhex("915B169EEEC9D8A367C0E98DA75C458C")
    active_different_irk = _make_win_entry("f6a2f5ec714b", different_irk, is_active=True)

    result = _find_ble_win_entry(lk, [inactive_irk_match, active_different_irk])
    assert result is active_different_irk


def test_does_not_fall_back_to_active_when_multiple_active_entries():
    """When multiple active entries exist, do not blindly pick one — fall back to
    the IRK match instead to avoid patching the wrong device."""
    lk = _make_ble_keys("FA:73:88:BA:3B:FB", _LINUX_IRK)
    inactive_irk_match = _make_win_entry("fa7388ba3bfb", _WIN_IRK_STALE, is_active=False)
    different_irk = bytes.fromhex("915B169EEEC9D8A367C0E98DA75C458C")
    active1 = _make_win_entry("f6a2f5ec714b", different_irk, is_active=True)
    irk2 = bytes.fromhex("AABBCCDDEEFF001122334455667788AA")
    active2 = _make_win_entry("aabbccddeeff", irk2, is_active=True)

    result = _find_ble_win_entry(lk, [inactive_irk_match, active1, active2])
    # Falls back to IRK match, not the ambiguous active entries
    assert result is inactive_irk_match


def test_returns_none_when_no_match():
    """Returns None when no entry matches by IRK or MAC."""
    lk = _make_ble_keys("FA:73:88:BA:3B:FB", _LINUX_IRK)
    unrelated = _make_win_entry("aabbccddeeff", b"\x11" * 16, is_active=False)

    result = _find_ble_win_entry(lk, [unrelated])
    assert result is None
