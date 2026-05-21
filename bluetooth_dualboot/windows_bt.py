"""Read and write Bluetooth pairing keys in the Windows SYSTEM registry hive."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from Registry import Registry

# Registry path within the SYSTEM hive (ControlSet001 is the canonical active set)
_BT_KEY_PATH = "ControlSet001\\Services\\BTHPORT\\Parameters\\Keys"


@dataclass
class WindowsBTEntry:
    """Represents a BLE device entry found in the Windows registry."""

    adapter_key: str  # e.g. 'c03532ac134a'
    device_key: str  # e.g. 'd8b8c38e9fd6'
    ltk: bytes
    irk: bytes
    key_length: int
    erand: int
    ediv: int
    csrk_inbound: bytes | None
    csrk_outbound: bytes | None
    inbound_sign_counter: int
    outbound_sign_counter: int
    address: int
    address_type: int
    auth_req: int


def _open_bt_keys(reg: Registry.Registry) -> Registry.RegistryKey | None:
    """Open the BTHPORT Parameters Keys node; return None if not found."""
    try:
        return reg.open(_BT_KEY_PATH)
    except Registry.RegistryKeyNotFoundException:
        return None


def read_windows_bt_entries(hive_path: Path) -> list[WindowsBTEntry]:
    """Parse the Windows SYSTEM hive and return all BLE device entries."""
    reg = Registry.Registry(str(hive_path))
    bt_root = _open_bt_keys(reg)
    if bt_root is None:
        return []

    entries: list[WindowsBTEntry] = []

    for adapter_key in bt_root.subkeys():
        for device_key in adapter_key.subkeys():
            values = {v.name(): v.value() for v in device_key.values()}

            # Only process entries that look like BLE (have LTK + IRK)
            if "LTK" not in values or "IRK" not in values:
                continue

            entries.append(
                WindowsBTEntry(
                    adapter_key=adapter_key.name(),
                    device_key=device_key.name(),
                    ltk=values.get("LTK", b""),
                    irk=values.get("IRK", b""),
                    key_length=values.get("KeyLength", 16),
                    erand=values.get("ERand", 0),
                    ediv=values.get("EDIV", 0),
                    csrk_inbound=values.get("CSRKInbound"),
                    csrk_outbound=values.get("CSRK"),
                    inbound_sign_counter=values.get("InboundSignCounter", 0),
                    outbound_sign_counter=values.get("OutboundSignCounter", 0),
                    address=values.get("Address", 0),
                    address_type=values.get("AddressType", 0),
                    auth_req=values.get("AuthReq", 0),
                )
            )

    return entries


def write_ble_keys_to_hive(
    hive_path: Path,
    adapter_key: str,
    device_key: str,
    ltk: bytes,
    irk: bytes,
    csrk_inbound: bytes | None = None,
    csrk_outbound: bytes | None = None,
) -> None:
    """Overwrite LTK, IRK, and optionally CSRK values for a device in the Windows hive.

    Uses raw binary patching of the hive file since python-registry is read-only.
    Each key value is located by its existing byte content and replaced in-place.
    The hive file must be writable (requires root / sudo on Linux).
    """
    hive_bytes = bytearray(hive_path.read_bytes())

    def _patch(old_val: bytes, new_val: bytes, label: str) -> bool:
        idx = hive_bytes.find(old_val)
        if idx == -1:
            return False
        hive_bytes[idx : idx + len(new_val)] = new_val
        return True

    # Read current values from the hive to locate them for patching
    reg = Registry.Registry(str(hive_path))
    bt_root = _open_bt_keys(reg)
    if bt_root is None:
        raise RuntimeError("BTHPORT\\Parameters\\Keys not found in hive")

    try:
        device_node = bt_root.find_subkey(adapter_key).find_subkey(device_key)
    except Exception as exc:
        raise KeyError(f"Registry key {adapter_key}\\{device_key} not found in hive") from exc

    current = {v.name(): v.value() for v in device_node.values()}

    updates = {"LTK": (current["LTK"], ltk), "IRK": (current["IRK"], irk)}
    if csrk_inbound is not None and "CSRKInbound" in current:
        updates["CSRKInbound"] = (current["CSRKInbound"], csrk_inbound)
    if csrk_outbound is not None and "CSRK" in current:
        updates["CSRK"] = (current["CSRK"], csrk_outbound)

    for name, (old_val, new_val) in updates.items():
        if old_val == new_val:
            continue
        if not _patch(old_val, new_val, name):
            raise RuntimeError(
                f"Could not locate existing {name} value in hive for in-place patching. "
                "The hive may be in use or corrupted."
            )

    hive_path.write_bytes(bytes(hive_bytes))
