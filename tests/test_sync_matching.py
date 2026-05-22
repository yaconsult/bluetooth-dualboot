"""Tests for BLE matching logic and _sync_ble behaviour."""

from pathlib import Path
from unittest.mock import patch

from bluetooth_dualboot.linux_bt import BLEKeys
from bluetooth_dualboot.sync import _find_ble_win_entry, _sync_ble, _win_key_to_mac
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


def test_name_fallback_matches_sole_active_entry():
    """When IRK and MAC both fail, match by device name on the sole active entry."""
    lk = _make_ble_keys("F2:E8:D8:09:66:57", "CB1E599082F4578B29040F3BD1DB4DC3")
    # Different IRK and MAC — no IRK/MAC match possible
    active = _make_win_entry("d0774e9fd983", b"\x99" * 16, is_active=True)

    with patch(
        "bluetooth_dualboot.sync._device_name_from_cache",
        return_value="Test Mouse",
    ):
        result = _find_ble_win_entry(lk, [active])
    assert result is active


def test_name_fallback_skips_when_name_differs():
    """Name fallback should NOT match if the device names differ."""
    lk = _make_ble_keys("F2:E8:D8:09:66:57", "CB1E599082F4578B29040F3BD1DB4DC3")
    active = _make_win_entry("d0774e9fd983", b"\x99" * 16, is_active=True)

    with patch(
        "bluetooth_dualboot.sync._device_name_from_cache",
        return_value="Other Device",
    ):
        result = _find_ble_win_entry(lk, [active])
    assert result is None


def test_name_fallback_skips_when_multiple_active():
    """Name fallback should NOT match if there are multiple active entries."""
    lk = _make_ble_keys("F2:E8:D8:09:66:57", "CB1E599082F4578B29040F3BD1DB4DC3")
    active1 = _make_win_entry("d0774e9fd983", b"\x99" * 16, is_active=True)
    active2 = _make_win_entry("aabbccddeeff", b"\x88" * 16, is_active=True)

    with patch(
        "bluetooth_dualboot.sync._device_name_from_cache",
        return_value="Test Mouse",
    ):
        result = _find_ble_win_entry(lk, [active1, active2])
    assert result is None


def test_win_key_to_mac():
    assert _win_key_to_mac("d0774e9fd983") == "D0:77:4E:9F:D9:83"
    assert _win_key_to_mac("fa7388ba3bfb") == "FA:73:88:BA:3B:FB"
    assert _win_key_to_mac("c03532ac134a") == "C0:35:32:AC:13:4A"


# --- _sync_ble tests ---

_BLE_INFO_TEMPLATE = """\
[General]
Name=BT5.0 Mouse
Appearance=0x03c2
AddressType=static
SupportedTechnologies=LE;
Trusted=true
Blocked=false

[IdentityResolvingKey]
Key=OLDIRK00000000000000000000000000

[LongTermKey]
Key=OLDLTK00000000000000000000000000
Authenticated=0
EncSize=16
EDiv=0
Rand=0

[PeripheralLongTermKey]
Key=OLDPLTK0000000000000000000000000
Authenticated=0
EncSize=16
EDiv=0
Rand=0
"""


def _setup_bluez(tmp_path: Path, adapter: str, device: str) -> Path:
    """Create a minimal BlueZ directory with a device info file."""
    device_dir = tmp_path / adapter / device
    device_dir.mkdir(parents=True)
    (device_dir / "info").write_text(_BLE_INFO_TEMPLATE)
    return tmp_path


def test_sync_ble_renames_device_dir_when_address_changes(tmp_path):
    """_sync_ble should rename the device directory to the Windows address."""
    adapter = "C0:35:32:AC:13:4A"
    old_mac = "F2:E8:D8:09:66:57"
    win_mac = "D0:77:4E:9F:D9:83"
    bluez_dir = _setup_bluez(tmp_path, adapter, old_mac)

    lk = _make_ble_keys(old_mac, "OLDIRK00000000000000000000000000")
    we = _make_win_entry("d0774e9fd983", b"\xaa" * 16, is_active=True)

    changed = _sync_ble(lk, we, bluez_dir, dry_run=False, verbose=False)

    assert changed is True
    # Old directory should be gone, new one should exist
    assert not (bluez_dir / adapter / old_mac).exists()
    assert (bluez_dir / adapter / win_mac / "info").exists()


def test_sync_ble_writes_peripheral_ltk(tmp_path):
    """_sync_ble should write PeripheralLongTermKey with the same LTK values."""
    import configparser

    adapter = "C0:35:32:AC:13:4A"
    device = "FA:73:88:BA:3B:FB"
    bluez_dir = _setup_bluez(tmp_path, adapter, device)

    lk = _make_ble_keys(device, "OLDIRK00000000000000000000000000")
    we = _make_win_entry("fa7388ba3bfb", b"\xbb" * 16, is_active=True)

    _sync_ble(lk, we, bluez_dir, dry_run=False, verbose=False)

    parser = configparser.ConfigParser()
    parser.read(str(bluez_dir / adapter / device / "info"))
    # LTK and PeripheralLTK should have the same key
    assert parser["LongTermKey"]["key"] == parser["PeripheralLongTermKey"]["key"]
    assert parser["LongTermKey"]["ediv"] == parser["PeripheralLongTermKey"]["ediv"]
    assert parser["LongTermKey"]["rand"] == parser["PeripheralLongTermKey"]["rand"]


def test_sync_ble_no_byte_reversal(tmp_path):
    """_sync_ble should write Windows keys as-is (no byte reversal)."""
    adapter = "C0:35:32:AC:13:4A"
    device = "FA:73:88:BA:3B:FB"
    bluez_dir = _setup_bluez(tmp_path, adapter, device)

    lk = _make_ble_keys(device, "OLDIRK00000000000000000000000000")
    raw_ltk = bytes.fromhex("441A7084CC0B022B0DFC72CD0603A6B4")
    we = _make_win_entry("fa7388ba3bfb", b"\xcc" * 16, is_active=True)
    # Override LTK on the entry
    we = WindowsBLEEntry(
        adapter_key=we.adapter_key,
        device_key=we.device_key,
        ltk=raw_ltk,
        irk=we.irk,
        key_length=we.key_length,
        erand=we.erand,
        ediv=we.ediv,
        csrk_inbound=we.csrk_inbound,
        csrk_outbound=we.csrk_outbound,
        inbound_sign_counter=we.inbound_sign_counter,
        outbound_sign_counter=we.outbound_sign_counter,
        address=we.address,
        address_type=we.address_type,
        auth_req=we.auth_req,
        is_active=we.is_active,
    )

    _sync_ble(lk, we, bluez_dir, dry_run=False, verbose=False)

    from bluetooth_dualboot.linux_bt import read_ble_keys

    keys = read_ble_keys(bluez_dir / adapter / device / "info", adapter, device)
    assert keys is not None
    # Should be hex-encoded as-is, NOT reversed
    assert keys.ltk == "441A7084CC0B022B0DFC72CD0603A6B4"


def test_sync_ble_dry_run_does_not_rename(tmp_path):
    """_sync_ble in dry_run mode should NOT rename directories or modify files."""
    adapter = "C0:35:32:AC:13:4A"
    old_mac = "F2:E8:D8:09:66:57"
    bluez_dir = _setup_bluez(tmp_path, adapter, old_mac)

    lk = _make_ble_keys(old_mac, "OLDIRK00000000000000000000000000")
    we = _make_win_entry("d0774e9fd983", b"\xaa" * 16, is_active=True)

    changed = _sync_ble(lk, we, bluez_dir, dry_run=True, verbose=False)

    assert changed is True
    # Old directory should still exist (dry run)
    assert (bluez_dir / adapter / old_mac / "info").exists()
