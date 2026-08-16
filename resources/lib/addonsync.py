# SPDX-FileCopyrightText: © 2016 Rob Webset
# SPDX-FileCopyrightText: © 2019 Robert Hudson
# SPDX-FileCopyrightText: © 2020-2021 Peter J. Mello <admin@petermello.net>
# SPDX-License-Identifier: MPL-2.0
"""Modernized AddonSync core for Kodi 19+.

The implementation deliberately uses Kodi's VFS API for both local and network
paths so SMB/NFS sources are treated the same way as local profile folders.
"""

from __future__ import annotations

import hashlib
import json
import re
import traceback
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import xbmc
import xbmcgui
import xbmcvfs
from xbmcaddon import Addon

ADDON_ID = "service.addonsync"
ADDON = Addon(id=ADDON_ID)
LOCK_PROPERTY = f"{ADDON_ID}.sync_running"
MANIFEST_NAME = "manifest.json"
LEGACY_MANIFEST_NAME = "hashdata.xml"
MANIFEST_SCHEMA = 2
HASH_ALGORITHM = "sha256-tree-v1"
CHUNK_SIZE = 1024 * 1024

SKIP_EXACT = {
    ADDON_ID,
    "screensaver.xbmc.builtin.black",
    "screensaver.xbmc.builtin.dim",
    "service.xbmc.versioncheck",
}
SKIP_PREFIXES = (
    "metadata.",
    "repository.",
    "resource.language.",
    "skin.",
)


def _setting(name: str, default: str = "") -> str:
    value = ADDON.getSetting(name)
    return value if value != "" else default


def _setting_bool(name: str, default: bool = False) -> bool:
    value = ADDON.getSetting(name)
    if value == "":
        return default
    return value.lower() == "true"


def _setting_int(name: str, default: int = 0) -> int:
    try:
        return int(float(_setting(name, str(default))))
    except (TypeError, ValueError):
        return default


def log(message: str, level: int = xbmc.LOGDEBUG) -> None:
    if _setting_bool("logEnabled", False) or level != xbmc.LOGDEBUG:
        xbmc.log(f"{ADDON_ID}: {message}", level)


def notify(message_id: int, milliseconds: int = 5000) -> None:
    xbmcgui.Dialog().notification(
        ADDON.getLocalizedString(32000) or "AddonSync",
        ADDON.getLocalizedString(message_id),
        time=milliseconds,
    )


def _separator(path: str) -> str:
    if "://" in path or "\\" not in path:
        return "/"
    return "\\"


def as_dir(path: str) -> str:
    if not path:
        return path
    if path.endswith(("/", "\\")):
        return path
    return path + _separator(path)


def vfs_join(base: str, *parts: str) -> str:
    result = base.rstrip("/\\")
    sep = _separator(base)
    for part in parts:
        if part is None:
            continue
        clean = str(part).strip("/\\")
        if clean:
            result = f"{result}{sep}{clean}"
    return result


def dir_exists(path: str) -> bool:
    return bool(path) and xbmcvfs.exists(as_dir(path))


def ensure_dir(path: str) -> bool:
    if dir_exists(path):
        return True
    try:
        return bool(xbmcvfs.mkdirs(as_dir(path))) or dir_exists(path)
    except Exception:  # Kodi VFS exceptions vary by backend.
        log(f"Unable to create directory {path}: {traceback.format_exc()}", xbmc.LOGERROR)
        return False


def remove_tree(root: str) -> bool:
    """Recursively delete a directory using VFS operations only."""
    if not dir_exists(root):
        return True
    try:
        dirs, files = xbmcvfs.listdir(as_dir(root))
        ok = True
        for filename in files:
            ok = bool(xbmcvfs.delete(vfs_join(root, filename))) and ok
        for dirname in dirs:
            ok = remove_tree(vfs_join(root, dirname)) and ok
        ok = bool(xbmcvfs.rmdir(as_dir(root))) and ok
        return ok or not dir_exists(root)
    except Exception:
        log(f"Unable to remove directory {root}: {traceback.format_exc()}", xbmc.LOGERROR)
        return False


def copy_tree(source: str, target: str) -> bool:
    """Recursively copy source to target using xbmcvfs."""
    source = as_dir(source)
    target = as_dir(target)
    if not dir_exists(source):
        log(f"Copy source does not exist: {source}", xbmc.LOGERROR)
        return False
    if not ensure_dir(target):
        return False
    try:
        dirs, files = xbmcvfs.listdir(source)
        for filename in sorted(files):
            src_file = vfs_join(source, filename)
            dst_file = vfs_join(target, filename)
            if not xbmcvfs.copy(src_file, dst_file):
                log(f"Copy failed: {src_file} -> {dst_file}", xbmc.LOGERROR)
                return False
        for dirname in sorted(dirs):
            if not copy_tree(vfs_join(source, dirname), vfs_join(target, dirname)):
                return False
        return True
    except Exception:
        log(f"Recursive copy failed {source} -> {target}: {traceback.format_exc()}", xbmc.LOGERROR)
        return False


def _hash_file(path: str, hasher) -> None:
    with xbmcvfs.File(path) as handle:
        while True:
            block = handle.readBytes(CHUNK_SIZE)
            if not block:
                break
            hasher.update(block)


def hash_tree(root: str) -> str | None:
    """Return a stable SHA-256 hash of names and bytes in a directory tree."""
    if not dir_exists(root):
        return None
    hasher = hashlib.sha256()

    def walk(path: str, relative: str = "") -> None:
        dirs, files = xbmcvfs.listdir(as_dir(path))
        for dirname in sorted(dirs):
            if dirname.startswith(".addonsync"):
                continue
            rel = f"{relative}/{dirname}" if relative else dirname
            hasher.update(f"D\0{rel}\0".encode("utf-8"))
            walk(vfs_join(path, dirname), rel)
        for filename in sorted(files):
            if filename.startswith(".addonsync"):
                continue
            rel = f"{relative}/{filename}" if relative else filename
            hasher.update(f"F\0{rel}\0".encode("utf-8"))
            _hash_file(vfs_join(path, filename), hasher)
            hasher.update(b"\0")

    try:
        walk(root)
        return hasher.hexdigest()
    except Exception:
        log(f"Hashing failed for {root}: {traceback.format_exc()}", xbmc.LOGERROR)
        return None


def _json_rpc(method: str, params: dict | None = None) -> dict:
    request = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        request["params"] = params
    try:
        response = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
    except (TypeError, ValueError):
        log(f"Invalid JSON-RPC response for {method}: {traceback.format_exc()}", xbmc.LOGERROR)
        return {}
    if "error" in response:
        log(f"JSON-RPC error for {method}: {response['error']}", xbmc.LOGERROR)
    return response


def _skip_addon(addon_id: str) -> bool:
    return addon_id in SKIP_EXACT or addon_id.startswith(SKIP_PREFIXES)


def _filter_values(setting_name: str) -> set[str]:
    raw = _setting(setting_name, "").strip()
    if not raw:
        return set()
    return {item for item in re.split(r"[\s,;]+", raw) if item}


def _apply_filter(addons: dict[str, dict]) -> dict[str, dict]:
    filter_type = _setting_int("filterType", 0)
    if filter_type == 1:
        selected = _filter_values("includedAddons")
        return {key: value for key, value in addons.items() if key in selected}
    if filter_type == 2:
        selected = _filter_values("excludedAddons")
        return {key: value for key, value in addons.items() if key not in selected}
    return addons


def installed_addons() -> dict[str, dict]:
    response = _json_rpc(
        "Addons.GetAddons",
        {"enabled": True, "properties": ["broken", "version", "name"]},
    )
    result = response.get("result", {})
    addons: dict[str, dict] = {}
    for item in result.get("addons", []):
        addon_id = item.get("addonid", "")
        if not addon_id or _skip_addon(addon_id) or item.get("broken"):
            continue
        addons[addon_id] = {
            "version": str(item.get("version", "")),
            "name": item.get("name", addon_id),
        }
    return _apply_filter(addons)


def addon_profile(addon_id: str) -> str | None:
    try:
        profile = Addon(id=addon_id).getAddonInfo("profile")
    except Exception:
        log(f"Unable to resolve profile for {addon_id}")
        return None
    return as_dir(profile) if profile else None


def local_addon_details() -> dict[str, dict]:
    details: dict[str, dict] = {}
    for addon_id, info in installed_addons().items():
        profile = addon_profile(addon_id)
        if not profile:
            continue
        details[addon_id] = {
            "version": info["version"],
            "dir": profile,
            "hash": hash_tree(profile),
        }
    return details


def central_store() -> str:
    return as_dir(_setting("centralStoreLocation", "").strip())


def is_master() -> bool:
    return _setting_int("installationType", 0) == 0


def version_match_required() -> bool:
    return _setting_bool("forceVersionMatch", True)


def _read_text(path: str) -> str | None:
    if not xbmcvfs.exists(path):
        return None
    try:
        with xbmcvfs.File(path) as handle:
            return handle.read()
    except Exception:
        log(f"Unable to read {path}: {traceback.format_exc()}", xbmc.LOGERROR)
        return None


def _write_text(path: str, content: str) -> bool:
    try:
        with xbmcvfs.File(path, "w") as handle:
            return bool(handle.write(content))
    except Exception:
        log(f"Unable to write {path}: {traceback.format_exc()}", xbmc.LOGERROR)
        return False


def read_manifest(store: str) -> dict | None:
    manifest_path = vfs_join(store, MANIFEST_NAME)
    raw = _read_text(manifest_path)
    if raw:
        try:
            manifest = json.loads(raw)
            if isinstance(manifest.get("addons"), dict):
                return manifest
        except (TypeError, ValueError):
            log(f"Invalid {MANIFEST_NAME} in {store}", xbmc.LOGERROR)

    # One-time compatibility path for stores created by the old AddonSync.
    legacy_raw = _read_text(vfs_join(store, LEGACY_MANIFEST_NAME))
    if not legacy_raw:
        return None
    try:
        root = ET.fromstring(legacy_raw)
        addons = {}
        for element in root.findall("addon"):
            addon_id = element.attrib.get("name")
            if addon_id:
                addons[addon_id] = {
                    "version": element.attrib.get("version", ""),
                    "hash": element.text or "",
                }
        return {
            "schema": 1,
            "algorithm": "legacy-md5-tree",
            "addons": addons,
        }
    except ET.ParseError:
        log(f"Invalid legacy {LEGACY_MANIFEST_NAME}: {traceback.format_exc()}", xbmc.LOGERROR)
        return None


def write_manifest(store: str, addons: dict[str, dict]) -> bool:
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "algorithm": HASH_ALGORITHM,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "addons": addons,
    }
    content = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False)
    tmp = vfs_join(store, f".{MANIFEST_NAME}.tmp")
    final = vfs_join(store, MANIFEST_NAME)
    if not _write_text(tmp, content):
        return False
    # Rename on the same VFS backend is preferable; fall back to direct write.
    if xbmcvfs.exists(final):
        xbmcvfs.delete(final)
    if xbmcvfs.rename(tmp, final):
        return True
    success = _write_text(final, content)
    xbmcvfs.delete(tmp)
    return success


def _replace_tree_verified(source: str, target: str, expected_hash: str) -> bool:
    """Stage, verify and replace target. Restore a local backup on failure."""
    target_base = target.rstrip("/\\")
    temp = f"{target_base}.addonsync.tmp"
    backup = f"{target_base}.addonsync.bak"
    remove_tree(temp)
    remove_tree(backup)

    if not copy_tree(source, temp):
        remove_tree(temp)
        return False
    staged_hash = hash_tree(temp)
    if staged_hash != expected_hash:
        log(
            f"Verification failed for staged copy {source} -> {temp}: "
            f"expected {expected_hash}, got {staged_hash}",
            xbmc.LOGERROR,
        )
        remove_tree(temp)
        return False

    had_target = dir_exists(target)
    if had_target and not copy_tree(target, backup):
        log(f"Could not create safety backup for {target}", xbmc.LOGERROR)
        remove_tree(temp)
        remove_tree(backup)
        return False

    if had_target and not remove_tree(target):
        log(f"Could not remove old target {target}; restoring safety backup", xbmc.LOGERROR)
        # remove_tree() may have removed only part of the target. Re-copy the
        # verified safety backup before giving up, and retain the backup if
        # restoration itself fails so the user still has a recoverable copy.
        restored = copy_tree(backup, target)
        remove_tree(temp)
        if restored and hash_tree(target) == hash_tree(backup):
            remove_tree(backup)
        return False

    installed = False
    try:
        # Same-filesystem rename is cheap and normally atomic.
        installed = bool(xbmcvfs.rename(as_dir(temp), as_dir(target)))
    except Exception:
        installed = False
    if not installed:
        installed = copy_tree(temp, target)
        remove_tree(temp)

    if installed and hash_tree(target) == expected_hash:
        remove_tree(backup)
        return True

    log(f"Final verification failed for {target}; restoring backup", xbmc.LOGERROR)
    remove_tree(target)
    if had_target and dir_exists(backup):
        copy_tree(backup, target)
    remove_tree(temp)
    remove_tree(backup)
    return False


def _service_addons() -> set[str]:
    response = _json_rpc(
        "Addons.GetAddons",
        {"type": "xbmc.service", "enabled": True, "properties": ["broken"]},
    )
    result = response.get("result", {})
    return {
        item.get("addonid")
        for item in result.get("addons", [])
        if item.get("addonid") and not item.get("broken") and item.get("addonid") != ADDON_ID
    }


def _set_addon_enabled(addon_id: str, enabled: bool) -> bool:
    response = _json_rpc("Addons.SetAddonEnabled", {"addonid": addon_id, "enabled": enabled})
    return "error" not in response


def sync_master(store: str) -> bool:
    if not ensure_dir(store):
        log(f"Central store is not writable/available: {store}", xbmc.LOGERROR)
        return False

    old_manifest = read_manifest(store) or {"addons": {}}
    old_addons = old_manifest.get("addons", {})
    details = local_addon_details()
    new_manifest: dict[str, dict] = {}
    success = True

    for addon_id, detail in details.items():
        source_hash = detail.get("hash")
        source_dir = detail.get("dir")
        if not source_hash or not source_dir or not dir_exists(source_dir):
            continue

        target_dir = vfs_join(store, addon_id)
        old = old_addons.get(addon_id, {})
        unchanged = (
            old_manifest.get("algorithm") == HASH_ALGORITHM
            and old.get("hash") == source_hash
            and dir_exists(target_dir)
        )
        if not unchanged:
            log(f"Master: updating {addon_id}")
            if not _replace_tree_verified(source_dir, target_dir, source_hash):
                success = False
                if old and dir_exists(target_dir):
                    new_manifest[addon_id] = old
                continue
        else:
            log(f"Master: {addon_id} already current")

        new_manifest[addon_id] = {
            "version": detail["version"],
            "hash": source_hash,
        }

    if not write_manifest(store, new_manifest):
        success = False
    return success


def sync_slave(store: str) -> bool:
    manifest = read_manifest(store)
    if not manifest:
        log(f"No manifest found in {store}", xbmc.LOGERROR)
        notify(32034)
        return False

    manifest_addons = manifest.get("addons", {})
    algorithm = manifest.get("algorithm", "")
    details = local_addon_details()
    restart_services = _setting_bool("restartUpdatedServiceAddons", False)
    service_addons = _service_addons() if restart_services else set()
    success = True

    for addon_id, local in details.items():
        remote = manifest_addons.get(addon_id)
        if not remote:
            continue
        if version_match_required() and local.get("version") != remote.get("version"):
            log(
                f"Slave: version mismatch for {addon_id}: "
                f"local={local.get('version')} master={remote.get('version')}"
            )
            continue

        source_dir = vfs_join(store, addon_id)
        if not dir_exists(source_dir):
            log(f"Slave: master data missing for {addon_id}: {source_dir}", xbmc.LOGERROR)
            success = False
            continue

        expected_hash = remote.get("hash")
        if algorithm != HASH_ALGORITHM:
            # Legacy manifests used an incompatible hash construction. Re-hash
            # the stored tree once with the new algorithm instead of trusting it.
            expected_hash = hash_tree(source_dir)
        if not expected_hash:
            success = False
            continue
        if local.get("hash") == expected_hash:
            log(f"Slave: {addon_id} already current")
            continue

        # Before modifying local settings, verify that the central copy itself
        # matches the manifest. This avoids propagating a partial network copy.
        if algorithm == HASH_ALGORITHM:
            remote_hash = hash_tree(source_dir)
            if remote_hash != expected_hash:
                log(
                    f"Slave: central data verification failed for {addon_id}: "
                    f"expected {expected_hash}, got {remote_hash}",
                    xbmc.LOGERROR,
                )
                success = False
                continue

        disabled_for_sync = addon_id in service_addons
        if disabled_for_sync:
            log(f"Slave: stopping service add-on {addon_id}")
            _set_addon_enabled(addon_id, False)
            xbmc.Monitor().waitForAbort(0.5)

        try:
            log(f"Slave: updating {addon_id}")
            if not _replace_tree_verified(source_dir, local["dir"], expected_hash):
                success = False
        finally:
            if disabled_for_sync:
                log(f"Slave: starting service add-on {addon_id}")
                _set_addon_enabled(addon_id, True)

    return success


def sync_once(show_notifications: bool = False) -> bool:
    home = xbmcgui.Window(10000)
    if home.getProperty(LOCK_PROPERTY) == "true":
        log("Synchronization skipped because another AddonSync run is active")
        if show_notifications:
            notify(32035)
        return False

    store = central_store()
    if not store:
        log("Central store is not configured", xbmc.LOGERROR)
        if show_notifications:
            notify(32032)
            ADDON.openSettings()
        return False

    home.setProperty(LOCK_PROPERTY, "true")
    try:
        if show_notifications:
            notify(32030, 2500)
        ok = sync_master(store) if is_master() else sync_slave(store)
        if show_notifications:
            notify(32031 if ok else 32033)
        return ok
    except Exception:
        log(f"Unhandled synchronization error: {traceback.format_exc()}", xbmc.LOGERROR)
        if show_notifications:
            notify(32033)
        return False
    finally:
        home.clearProperty(LOCK_PROPERTY)


def run_manual() -> None:
    log(f"Manual run started (version {ADDON.getAddonInfo('version')})")
    sync_once(show_notifications=True)


def run_service() -> None:
    log(f"Service started (version {ADDON.getAddonInfo('version')})")
    if not _setting_bool("runOnStartup", True):
        log("Automatic startup synchronization is disabled")
        return

    monitor = xbmc.Monitor()
    interval_hours = max(0, _setting_int("checkInterval", 0))
    while not monitor.abortRequested():
        sync_once(show_notifications=False)
        if interval_hours <= 0:
            break
        if monitor.waitForAbort(interval_hours * 60 * 60):
            break
    log("Service stopped")


def select_filter_addons() -> None:
    filter_type = _setting_int("filterType", 0)
    if filter_type not in (1, 2):
        xbmcgui.Dialog().ok(
            ADDON.getLocalizedString(32000) or "AddonSync",
            ADDON.getLocalizedString(32037),
        )
        return

    # Get an unfiltered list for the selector.
    response = _json_rpc(
        "Addons.GetAddons",
        {"enabled": True, "properties": ["broken", "name"]},
    )
    rows = []
    for item in response.get("result", {}).get("addons", []):
        addon_id = item.get("addonid", "")
        if not addon_id or item.get("broken") or _skip_addon(addon_id):
            continue
        rows.append((str(item.get("name", addon_id)), addon_id))
    rows.sort(key=lambda row: row[0].casefold())

    if not rows:
        xbmcgui.Dialog().ok(
            ADDON.getLocalizedString(32000) or "AddonSync",
            ADDON.getLocalizedString(32036),
        )
        return

    labels = [f"{name}  [{addon_id}]" for name, addon_id in rows]
    selection = xbmcgui.Dialog().multiselect(
        ADDON.getLocalizedString(32019),
        labels,
    )
    if selection is None:
        return

    selected_ids = [rows[index][1] for index in selection]
    key = "includedAddons" if filter_type == 1 else "excludedAddons"
    ADDON.setSetting(key, " ".join(selected_ids))
    notify(32038, 2500)
