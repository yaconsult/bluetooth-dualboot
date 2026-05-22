"""CLI entry point: sync Bluetooth pairing keys between Linux and Windows.

BLE devices: Windows → Linux (Windows pairing is canonical; mouse stores Windows host identity).
Classic BR/EDR: Linux → Windows (symmetric link keys; either direction works).
"""

from __future__ import annotations

import argparse
import datetime
import os
import shutil
import sys
from pathlib import Path

from bluetooth_dualboot.linux_bt import (
    AnyDeviceKeys,
    BLEKeys,
    ClassicKeys,
    discover_all_devices,
    patch_ble_info_file,
)
from bluetooth_dualboot.utils import (
    find_ntfs_mounts,
    find_windows_system_hive,
    mac_to_windows_key,
    reverse_hex_key,
)
from bluetooth_dualboot.windows_bt import (
    WindowsBLEEntry,
    WindowsClassicEntry,
    create_classic_entry,
    patch_classic_entry,
    read_windows_ble_entries,
    read_windows_classic_entries,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bt-sync",
        description=(
            "Sync Bluetooth pairing keys between Linux and Windows so every paired "
            "device works in both OSes without re-pairing. BLE: Windows→Linux. "
            "Classic: Linux→Windows."
        ),
    )
    parser.add_argument(
        "--windows-mount",
        metavar="PATH",
        help="Mount point of the Windows NTFS partition (auto-detected if omitted)",
    )
    parser.add_argument(
        "--bluez-dir",
        metavar="PATH",
        default="/var/lib/bluetooth",
        help="Path to the BlueZ key store (default: /var/lib/bluetooth)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without writing anything",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed key information",
    )
    return parser


def _find_hive(windows_mount: str | None, verbose: bool) -> Path:
    """Locate the Windows SYSTEM hive, auto-detecting the mount if needed."""
    if windows_mount:
        mounts = [Path(windows_mount)]
    else:
        mounts = find_ntfs_mounts()
        if not mounts:
            print("ERROR: No NTFS partitions found. Is the Windows drive mounted?", file=sys.stderr)
            sys.exit(1)

    for mount in mounts:
        hive = find_windows_system_hive(mount)
        if hive:
            if verbose:
                print(f"  Found Windows SYSTEM hive: {hive}")
            return hive

    print(
        "ERROR: Could not find Windows\\System32\\config\\SYSTEM on any NTFS mount.",
        file=sys.stderr,
    )
    print(f"  Searched: {[str(m) for m in mounts]}", file=sys.stderr)
    sys.exit(1)


def _mac_candidates(mac: str) -> tuple[str, str]:
    """Return (normal, reversed) lowercase no-sep MAC strings for matching."""
    normal = mac_to_windows_key(mac)
    reversed_ = bytes(reversed(bytes.fromhex(normal))).hex()
    return normal, reversed_


def _find_ble_win_entry(lk: BLEKeys, win_ble: list[WindowsBLEEntry]) -> WindowsBLEEntry | None:
    """Match a Linux BLE device to a Windows registry entry.

    Match priority:
    1. IRK match on an active entry (appears in BTHLE enum — Windows is using it).
    2. Active entry when the IRK-matched entry is inactive — if there is exactly one
       active BLE entry and we have an IRK match on an inactive entry, the active
       entry is almost certainly the same physical device re-paired in Windows. Patch
       it so Windows can actually use the updated keys.
    3. IRK match on any entry — fallback if BTHLE enum is absent or stale.
    4. MAC match (normal and byte-reversed) — fallback for public-address devices.
    """
    linux_irk = reverse_hex_key(lk.irk) if lk.irk else None
    normal, reversed_ = _mac_candidates(lk.device_mac)
    irk_match: WindowsBLEEntry | None = None
    mac_match: WindowsBLEEntry | None = None
    active_entries = [we for we in win_ble if we.is_active]
    for we in win_ble:
        irk_hit = linux_irk and we.irk and we.irk == linux_irk
        if irk_hit:
            if we.is_active:
                return we
            if irk_match is None:
                irk_match = we
        if we.device_key in (normal, reversed_):
            mac_match = we
    # IRK matched an inactive entry — if there is exactly one active BLE entry,
    # that active entry is the device Windows is actually using (re-paired since
    # the last Linux sync). Patch it instead.
    if irk_match is not None and len(active_entries) == 1:
        return active_entries[0]
    return irk_match or mac_match


def _find_classic_win_entry(
    lk: ClassicKeys, win_classic: list[WindowsClassicEntry]
) -> WindowsClassicEntry | None:
    normal, reversed_ = _mac_candidates(lk.device_mac)
    for we in win_classic:
        if we.device_key in (normal, reversed_):
            return we
    return None


def _adapter_win_key(adapter_mac: str, win_ble: list[WindowsBLEEntry]) -> str:
    """Derive the Windows adapter key from existing entries or by normalising the MAC."""
    for we in win_ble:
        return we.adapter_key
    return mac_to_windows_key(adapter_mac)


def _win_key_to_linux_hex(win_bytes: bytes) -> str:
    """Byte-reverse a Windows key (little-endian) to Linux hex (big-endian, uppercase)."""
    return bytes(reversed(win_bytes)).hex().upper()


def _sync_ble(
    lk: BLEKeys,
    we: WindowsBLEEntry | None,
    bluez_dir: Path,
    dry_run: bool,
    verbose: bool,
) -> bool:
    """Sync a BLE device: Windows → Linux. Returns True if Linux info file was changed.

    BLE devices store the host's identity (adapter IRK) during pairing. Since
    Windows and Linux have different adapter IRKs, the device only recognises
    one host. By copying the Windows keys into Linux, both OSes present the
    same keys and the device (bonded to Windows) works in both.
    """
    if we is None:
        print(f"  [{lk.device_name}] No matching Windows BLE entry found — skipping.")
        print("    Hint: pair this device in Windows first, then run bt-sync.")
        return False

    # Convert Windows keys (little-endian bytes) → Linux format (big-endian hex)
    win_ltk = _win_key_to_linux_hex(we.ltk) if we.ltk else ""
    win_irk = _win_key_to_linux_hex(we.irk) if we.irk else ""
    win_csrk_local = _win_key_to_linux_hex(we.csrk_outbound) if we.csrk_outbound else ""
    win_csrk_remote = _win_key_to_linux_hex(we.csrk_inbound) if we.csrk_inbound else ""

    # Check if update is needed
    needs_update = (
        (win_ltk and win_ltk != lk.ltk)
        or (win_irk and win_irk != lk.irk)
        or (win_csrk_local and win_csrk_local != lk.csrk_local)
        or (win_csrk_remote and win_csrk_remote != lk.csrk_remote)
        or we.ediv != lk.ltk_ediv
        or we.erand != lk.ltk_rand
    )

    if not needs_update:
        print(f"  [{lk.device_name}] BLE keys already in sync — nothing to do.")
        return False

    if verbose or dry_run:
        print("    Action: PATCH Linux info file with Windows keys")
        if win_ltk and win_ltk != lk.ltk:
            print(f"    LTK:  {lk.ltk} → {win_ltk}")
        if win_irk and win_irk != lk.irk:
            print(f"    IRK:  {lk.irk} → {win_irk}")
        if win_csrk_local and win_csrk_local != lk.csrk_local:
            print(f"    CSRK(local):  {lk.csrk_local} → {win_csrk_local}")
        if win_csrk_remote and win_csrk_remote != lk.csrk_remote:
            print(f"    CSRK(remote): {lk.csrk_remote} → {win_csrk_remote}")
        if we.ediv != lk.ltk_ediv:
            print(f"    EDiv: {lk.ltk_ediv} → {we.ediv}")
        if we.erand != lk.ltk_rand:
            print(f"    Rand: {lk.ltk_rand} → {we.erand}")

    if dry_run:
        print(f"  [{lk.device_name}] DRY RUN — would patch Linux info file.")
        return True

    info_path = bluez_dir / lk.adapter_mac / lk.device_mac / "info"
    patch_ble_info_file(
        info_path=info_path,
        ltk=win_ltk,
        ltk_rand=we.erand,
        ltk_ediv=we.ediv,
        irk=win_irk,
        csrk_local=win_csrk_local,
        csrk_remote=win_csrk_remote,
    )
    print(f"  [{lk.device_name}] Linux BLE keys updated from Windows.")
    return True


def _sync_classic(
    lk: ClassicKeys,
    we: WindowsClassicEntry | None,
    adapter_win_key: str,
    hive_path: Path,
    dry_run: bool,
    verbose: bool,
) -> bool:
    """Sync a Classic BT device — patch if entry exists, create if not. Returns True if changed."""
    if not lk.link_key:
        print(f"  [{lk.device_name}] No LinkKey found in Linux — skipping.")
        return False

    # Classic link keys are stored as-is (no byte-reversal needed for BR/EDR)
    new_link_key = bytes.fromhex(lk.link_key)
    device_win_key = mac_to_windows_key(lk.device_mac)

    if we is None:
        if verbose or dry_run:
            print("    Action: CREATE new Windows Classic BT entry")
            print(f"    LinkKey: {new_link_key.hex().upper()}")

        if dry_run:
            print(f"  [{lk.device_name}] DRY RUN — would create new Windows Classic entry.")
            return True

        create_classic_entry(
            hive_path=hive_path,
            adapter_key=adapter_win_key,
            device_key=device_win_key,
            link_key=new_link_key,
        )
        print(f"  [{lk.device_name}] Created new Windows Classic BT entry.")
        return True

    if we.link_key == new_link_key:
        print(f"  [{lk.device_name}] Classic key already in sync — nothing to do.")
        return False

    if verbose or dry_run:
        print("    Action: PATCH existing Windows Classic entry")
        print(f"    LinkKey: {we.link_key.hex().upper()} → {new_link_key.hex().upper()}")

    if dry_run:
        print(f"  [{lk.device_name}] DRY RUN — would patch existing Windows Classic entry.")
        return True

    patch_classic_entry(
        hive_path=hive_path,
        adapter_key=we.adapter_key,
        device_key=we.device_key,
        link_key=new_link_key,
    )
    print(f"  [{lk.device_name}] Classic key patched in Windows registry.")
    return True


def _needs_classic_write(
    classic_pairs: list[tuple[ClassicKeys, WindowsClassicEntry | None]],
) -> bool:
    """Return True if at least one Classic device needs a Windows registry write."""
    for lk, we in classic_pairs:
        if not lk.link_key:
            continue
        if we is None or we.link_key != bytes.fromhex(lk.link_key):
            return True
    return False


def _backup_hive(hive_path: Path) -> Path:
    """Create a timestamped backup of the Windows SYSTEM hive before any writes.

    The backup is written alongside the original hive file. If anything goes
    wrong the user can restore it by copying it back over the SYSTEM file.
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = hive_path.with_name(f"SYSTEM.bt-sync-backup-{timestamp}")
    shutil.copy2(hive_path, backup_path)
    return backup_path


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if os.geteuid() != 0:
        print("ERROR: This script must be run as root (sudo).", file=sys.stderr)
        sys.exit(1)

    print("=== bt-sync: Bluetooth Dual-Boot Key Sync ===\n")

    # 1. Discover all Linux paired devices
    print(f"[1/4] Reading Linux BT keys from {args.bluez_dir} ...")
    try:
        linux_devices: list[AnyDeviceKeys] = discover_all_devices(Path(args.bluez_dir))
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if not linux_devices:
        print("  No paired devices found in Linux BT store.")
        sys.exit(0)

    ble_devices = [d for d in linux_devices if isinstance(d, BLEKeys)]
    classic_devices = [d for d in linux_devices if isinstance(d, ClassicKeys)]
    print(f"  Found {len(ble_devices)} BLE + {len(classic_devices)} Classic device(s):")
    for d in linux_devices:
        dtype = "BLE" if isinstance(d, BLEKeys) else "Classic"
        print(f"    - [{dtype}] {d.device_name} ({d.device_mac})")

    # 2. Locate Windows SYSTEM hive
    print("\n[2/4] Locating Windows SYSTEM hive ...")
    hive_path = _find_hive(args.windows_mount, args.verbose)
    print(f"  Hive: {hive_path}")

    # 3. Read Windows BT entries
    print("\n[3/4] Reading Windows BT registry entries ...")
    win_ble = read_windows_ble_entries(hive_path)
    win_classic = read_windows_classic_entries(hive_path)
    print(f"  Found {len(win_ble)} BLE + {len(win_classic)} Classic entry(ies) in Windows.")

    # Determine Windows adapter key (needed for create operations)
    adapter_win_key = (
        _adapter_win_key(linux_devices[0].adapter_mac, win_ble) if linux_devices else ""
    )

    # 4. Determine what needs changing, backup only if writes are needed, then sync
    print("\n[4/4] Syncing keys ...")

    # Pre-pair each Linux device with its Windows entry (or None) for the sync loop
    ble_pairs = [(lk, _find_ble_win_entry(lk, win_ble)) for lk in ble_devices]
    classic_pairs = [(lk, _find_classic_win_entry(lk, win_classic)) for lk in classic_devices]

    needs_hive_write = _needs_classic_write(classic_pairs)
    if not args.dry_run and needs_hive_write:
        backup_path = _backup_hive(hive_path)
        print(f"  Backup: {backup_path}")
        print(f"  (Restore with: sudo cp '{backup_path}' '{hive_path}')")

    changed = 0

    bluez_dir = Path(args.bluez_dir)
    ble_changed = False
    for lk, we in ble_pairs:
        print(f"\n  [BLE] {lk.device_name} ({lk.device_mac})")
        if args.verbose:
            status = "found in Windows" if we else "NOT in Windows"
            print(f"    Windows entry: {status}")
        if _sync_ble(lk, we, bluez_dir, args.dry_run, args.verbose):
            changed += 1
            ble_changed = True

    for lk, we in classic_pairs:
        print(f"\n  [Classic] {lk.device_name} ({lk.device_mac})")
        if args.verbose:
            status = "found in Windows" if we else "NOT in Windows — will create"
            print(f"    Windows entry: {status}")
        if _sync_classic(lk, we, adapter_win_key, hive_path, args.dry_run, args.verbose):
            changed += 1

    print()
    if args.dry_run:
        print(f"DRY RUN complete. {changed} device(s) would be updated.")
    else:
        print(f"Done. {changed} device(s) updated.")
        if ble_changed:
            print("Run: sudo systemctl restart bluetooth")
            print("Then verify your BLE devices reconnect in Linux.")


if __name__ == "__main__":
    main()
