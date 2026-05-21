"""Read and write Bluetooth pairing keys in the Windows SYSTEM registry hive."""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from Registry import Registry

# Registry path within the SYSTEM hive (ControlSet001 is the canonical active set)
_BT_KEY_PATH = "ControlSet001\\Services\\BTHPORT\\Parameters\\Keys"
# Prefix string required by reged for the SYSTEM hive
_REGED_PREFIX = "HKEY_LOCAL_MACHINE\\SYSTEM"


@dataclass
class WindowsBLEEntry:
    """Represents a BLE device entry found in the Windows registry."""

    adapter_key: str  # e.g. 'c03532ac134a'
    device_key: str  # e.g. 'e49f640be81c'
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
    is_active: bool = False  # True if this entry appears in the BTHLE enum (Windows is using it)


@dataclass
class WindowsClassicEntry:
    """Represents a BR/EDR device entry found in the Windows registry."""

    adapter_key: str  # e.g. 'c03532ac134a'
    device_key: str  # value name on the adapter key, e.g. 'dfd64fc9dc97'
    link_key: bytes


def _open_bt_keys(reg: Registry.Registry) -> Registry.RegistryKey | None:
    """Open the BTHPORT Parameters Keys node; return None if not found."""
    try:
        return reg.open(_BT_KEY_PATH)
    except Registry.RegistryKeyNotFoundException:
        return None


_BTHLE_ENUM_PATH = "ControlSet001\\Enum\\BTHLE"


def _read_active_bthle_device_keys(reg: Registry.Registry) -> set[str]:
    """Return the set of device_key strings that appear in the BTHLE enum.

    The BTHLE enum (ControlSet001\\Enum\\BTHLE\\Dev_<addr>) is only populated
    for the entry Windows is actively using — it has a FriendlyName and is the
    one the BT stack will try to connect to. Keys are lowercase hex MAC strings
    (e.g. 'f6a2f5ec714b').
    """
    active: set[str] = set()
    try:
        bthle_root = reg.open(_BTHLE_ENUM_PATH)
    except Registry.RegistryKeyNotFoundException:
        return active
    for sk in bthle_root.subkeys():
        # Subkey names are like 'Dev_f6a2f5ec714b'
        name = sk.name()
        if name.startswith("Dev_"):
            active.add(name[4:].lower())
    return active


def read_windows_ble_entries(hive_path: Path) -> list[WindowsBLEEntry]:
    """Parse the Windows SYSTEM hive and return all BLE device entries.

    Sets is_active=True on entries whose device_key appears in the BTHLE enum,
    meaning Windows is actively using that pairing.
    """
    reg = Registry.Registry(str(hive_path))
    bt_root = _open_bt_keys(reg)
    if bt_root is None:
        return []

    active_keys = _read_active_bthle_device_keys(reg)
    entries: list[WindowsBLEEntry] = []

    for adapter_key in bt_root.subkeys():
        for device_key in adapter_key.subkeys():
            values = {v.name(): v.value() for v in device_key.values()}

            if "LTK" not in values or "IRK" not in values:
                continue

            entries.append(
                WindowsBLEEntry(
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
                    is_active=device_key.name().lower() in active_keys,
                )
            )

    return entries


def read_windows_classic_entries(hive_path: Path) -> list[WindowsClassicEntry]:
    """Parse the Windows SYSTEM hive and return all BR/EDR device entries.

    Classic BT link keys are stored as binary values directly on the adapter key,
    named by the device MAC (no subkey).
    """
    reg = Registry.Registry(str(hive_path))
    bt_root = _open_bt_keys(reg)
    if bt_root is None:
        return []

    entries: list[WindowsClassicEntry] = []

    for adapter_key in bt_root.subkeys():
        for val in adapter_key.values():
            name = val.name().lower()
            # Classic link key values are 12-char hex MAC names with 16-byte binary content
            if len(name) == 12 and all(c in "0123456789abcdef" for c in name):
                raw = val.value()
                if isinstance(raw, bytes) and len(raw) == 16:
                    entries.append(
                        WindowsClassicEntry(
                            adapter_key=adapter_key.name(),
                            device_key=name,
                            link_key=raw,
                        )
                    )

    return entries


def patch_ble_entry(
    hive_path: Path,
    adapter_key: str,
    device_key: str,
    ltk: bytes,
    irk: bytes,
    csrk_inbound: bytes | None = None,
    csrk_outbound: bytes | None = None,
    address_type: int | None = None,
) -> None:
    """Overwrite LTK, IRK, AddressType and optionally CSRK values in an existing BLE entry.

    Uses raw binary patching since python-registry is read-only.
    Values are located by their current byte content and replaced in-place.
    Requires the hive file to be writable (sudo).
    """
    hive_bytes = bytearray(hive_path.read_bytes())

    def _patch(old_val: bytes, new_val: bytes) -> bool:
        idx = hive_bytes.find(old_val)
        if idx == -1:
            return False
        hive_bytes[idx : idx + len(new_val)] = new_val
        return True

    reg = Registry.Registry(str(hive_path))
    bt_root = _open_bt_keys(reg)
    if bt_root is None:
        raise RuntimeError("BTHPORT\\Parameters\\Keys not found in hive")

    try:
        device_node = bt_root.subkey(adapter_key).subkey(device_key)
    except Exception as exc:
        raise KeyError(f"Registry key {adapter_key}\\{device_key} not found in hive") from exc

    current = {v.name(): v.value() for v in device_node.values()}

    updates: dict[str, tuple[bytes, bytes]] = {
        "LTK": (current["LTK"], ltk),
        "IRK": (current["IRK"], irk),
    }
    if csrk_inbound is not None and "CSRKInbound" in current:
        updates["CSRKInbound"] = (current["CSRKInbound"], csrk_inbound)
    if csrk_outbound is not None and "CSRK" in current:
        updates["CSRK"] = (current["CSRK"], csrk_outbound)
    for name, (old_val, new_val) in updates.items():
        if old_val == new_val:
            continue
        if not _patch(old_val, new_val):
            raise RuntimeError(
                f"Could not locate existing {name} value in hive for in-place patching. "
                "The hive may be in use or corrupted."
            )

    hive_path.write_bytes(bytes(hive_bytes))

    # Patch DWORD values via reged (raw binary search is unsafe for small integers)
    at_changed = address_type is not None and current.get("AddressType") != address_type
    if at_changed:
        reg_key_path = f"HKEY_LOCAL_MACHINE\\SYSTEM\\{_BT_KEY_PATH}\\{adapter_key}\\{device_key}"
        reg_content = (
            "Windows Registry Editor Version 5.00\n\n"
            f"[{reg_key_path}]\n"
            f'"AddressType"=dword:{address_type:08x}\n'
        )
        _run_reged_import(hive_path, reg_content)


def patch_classic_entry(
    hive_path: Path,
    adapter_key: str,
    device_key: str,
    link_key: bytes,
) -> None:
    """Overwrite a BR/EDR link key value on the adapter key in-place."""
    hive_bytes = bytearray(hive_path.read_bytes())

    reg = Registry.Registry(str(hive_path))
    bt_root = _open_bt_keys(reg)
    if bt_root is None:
        raise RuntimeError("BTHPORT\\Parameters\\Keys not found in hive")

    try:
        adapter_node = bt_root.find_subkey(adapter_key)
    except Exception as exc:
        raise KeyError(f"Adapter key {adapter_key} not found in hive") from exc

    current_val = None
    for val in adapter_node.values():
        if val.name().lower() == device_key.lower():
            current_val = val.value()
            break

    if current_val is None:
        raise KeyError(f"Classic link key value {device_key} not found under {adapter_key}")

    if current_val == link_key:
        return

    idx = hive_bytes.find(current_val)
    if idx == -1:
        raise RuntimeError(
            f"Could not locate existing LinkKey for {device_key} in hive for patching."
        )
    hive_bytes[idx : idx + 16] = link_key
    hive_path.write_bytes(bytes(hive_bytes))


def _run_reged_import(hive_path: Path, reg_content: str) -> None:
    """Write reg_content to a temp .reg file and import it into the hive via reged."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".reg", delete=False, encoding="utf-8") as f:
        f.write(reg_content)
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["reged", "-I", "-C", str(hive_path), _REGED_PREFIX, tmp_path],
            capture_output=True,
            text=True,
        )
        # reged exit codes: 0 = success, 1 = fatal error, 2 = warnings only (still succeeded)
        if result.returncode == 1:
            raise RuntimeError(
                f"reged import failed (exit {result.returncode}):\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _bytes_to_reg_hex(data: bytes) -> str:
    """Format bytes as a Windows .reg REG_BINARY value (hex: prefix)."""
    return "hex:" + ",".join(f"{b:02x}" for b in data)


def _qword_to_reg_hex(value: int) -> str:
    """Format a 64-bit int as a Windows .reg REG_QWORD value (hex(b): prefix)."""
    b = value.to_bytes(8, "little")
    return "hex(b):" + ",".join(f"{x:02x}" for x in b)


def create_ble_entry(
    hive_path: Path,
    adapter_key: str,
    device_key: str,
    ltk: bytes,
    irk: bytes,
    key_length: int,
    erand: int,
    ediv: int,
    address: int,
    address_type: int,
    csrk_inbound: bytes | None = None,
    csrk_outbound: bytes | None = None,
    auth_req: int = 0x29,
) -> None:
    """Create a new BLE device subkey in the Windows SYSTEM hive via reged.

    Used when the device has never been paired in Windows before.

    auth_req should be derived from the Linux pairing data (BLEKeys.auth_req).
    The fallback 0x29 = bonding(01) + SC(bit3) + CT2(bit5), no MITM.
    """
    reg_key_path = f"HKEY_LOCAL_MACHINE\\SYSTEM\\{_BT_KEY_PATH}\\{adapter_key}\\{device_key}"

    lines = [
        "Windows Registry Editor Version 5.00",
        "",
        f"[{reg_key_path}]",
        f'"LTK"={_bytes_to_reg_hex(ltk)}',
        f'"KeyLength"=dword:{key_length:08x}',
        f'"ERand"={_qword_to_reg_hex(erand)}',
        f'"EDIV"=dword:{ediv:08x}',
        f'"IRK"={_bytes_to_reg_hex(irk)}',
        f'"Address"={_qword_to_reg_hex(address)}',
        f'"AddressType"=dword:{address_type:08x}',
        f'"AuthReq"=dword:{auth_req:08x}',
        # OutboundSignCounter: starts at 0 for a new pairing
        f'"OutboundSignCounter"=dword:{0:08x}',
        # InboundSignCounter: 0xFFFFFFFFFFFFFFFF is the Windows "uninitialized" sentinel
        # (means: accept any counter value on first inbound signed packet)
        f'"InboundSignCounter"={_qword_to_reg_hex(0xFFFFFFFFFFFFFFFF)}',
        # CEntralIRKStatus=1: IRK verified/resolved — required for private address resolution
        f'"CEntralIRKStatus"=dword:{1:08x}',
    ]

    if csrk_inbound is not None:
        lines.append(f'"CSRKInbound"={_bytes_to_reg_hex(csrk_inbound)}')
    if csrk_outbound is not None:
        lines.append(f'"CSRK"={_bytes_to_reg_hex(csrk_outbound)}')

    lines.append("")
    _run_reged_import(hive_path, "\n".join(lines))


def create_classic_entry(
    hive_path: Path,
    adapter_key: str,
    device_key: str,
    link_key: bytes,
) -> None:
    """Create a new BR/EDR link key value on the adapter key via reged.

    Classic BT keys are stored as binary values directly on the adapter key,
    named by the device MAC (no subkey).
    """
    reg_key_path = f"HKEY_LOCAL_MACHINE\\SYSTEM\\{_BT_KEY_PATH}\\{adapter_key}"

    lines = [
        "Windows Registry Editor Version 5.00",
        "",
        f"[{reg_key_path}]",
        f'"{device_key}"={_bytes_to_reg_hex(link_key)}',
        "",
    ]

    _run_reged_import(hive_path, "\n".join(lines))
