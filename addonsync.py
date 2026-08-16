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
MANIFEST_SCHEMA = 4
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

SCOPE_ADDON_DATA = "addon_data"
SCOPE_ADDONS = "addons"
SCOPE_CONFIG = "config"
SCOPE_PLAYLISTS = "playlists"
SCOPE_PROFILES = "profiles"
ADDON_SCOPES = (SCOPE_ADDONS, SCOPE_ADDON_DATA)
FOLDER_SCOPES = (SCOPE_CONFIG, SCOPE_PLAYLISTS, SCOPE_PROFILES)
SCOPE_ORDER = (SCOPE_ADDONS, SCOPE_ADDON_DATA, SCOPE_CONFIG, SCOPE_PLAYLISTS, SCOPE_PROFILES)
SCOPE_LABELS = {
    SCOPE_ADDON_DATA: "addon_data",
    SCOPE_ADDONS: "addons",
    SCOPE_CONFIG: "config",
    SCOPE_PLAYLISTS: "playlists",
    SCOPE_PROFILES: "profiles",
}

# The Config scope intentionally excludes database/cache/profile payloads that
# have their own semantics. It synchronizes portable configuration stored in
# the master profile root plus the keymaps/library configuration directories.
CONFIG_FILES = (
    "advancedsettings.xml",
    "favourites.xml",
    "guisettings.xml",
    "Lircmap.xml",
    "mediasources.xml",
    "PartyMode.xsp",
    "passwords.xml",
    "playercorefactory.xml",
    "RssFeeds.xml",
    "sources.xml",
    "upnpserver.xml",
    "wakeonlan.xml",
)
CONFIG_DIRS = ("keymaps", "library")


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


def localized(message_id: int, fallback: str, **values) -> str:
    """Return a localized string and optionally format named placeholders."""
    text = ADDON.getLocalizedString(message_id) or fallback
    if values:
        try:
            text = text.format(**values)
        except (KeyError, ValueError):
            log(f"Unable to format localized string {message_id}: {text!r}", xbmc.LOGERROR)
    return text


def notify_text(message: str, milliseconds: int = 5000) -> None:
    xbmcgui.Dialog().notification(
        localized(32000, "AddonSync"),
        message,
        time=milliseconds,
    )


def notify(message_id: int, milliseconds: int = 5000) -> None:
    notify_text(ADDON.getLocalizedString(message_id), milliseconds)


def scope_label(scope: str) -> str:
    if scope == SCOPE_ADDON_DATA:
        return localized(32053, "Add-on data")
    if scope == SCOPE_ADDONS:
        return localized(32054, "Add-on files")
    if scope == SCOPE_CONFIG:
        return localized(32055, "Config")
    if scope == SCOPE_PLAYLISTS:
        return localized(32056, "Playlists")
    if scope == SCOPE_PROFILES:
        return localized(32057, "Profiles")
    return SCOPE_LABELS.get(scope, scope)


class SyncStatus:
    """Native Kodi background progress notification for an active sync run."""

    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.dialog = None
        self.updated = 0
        self.current = 0
        self.skipped = 0
        self.errors = 0
        if enabled:
            try:
                self.dialog = xbmcgui.DialogProgressBG()
            except Exception:
                log(f"Unable to create sync progress dialog: {traceback.format_exc()}", xbmc.LOGERROR)
                self.enabled = False

    @property
    def title(self) -> str:
        return localized(32000, "AddonSync")

    def start(self) -> None:
        if not self.enabled or self.dialog is None:
            return
        try:
            self.dialog.create(self.title, localized(32041, "Preparing synchronization"))
            self.dialog.update(1, self.title, localized(32041, "Preparing synchronization"))
        except Exception:
            log(f"Unable to start sync progress dialog: {traceback.format_exc()}", xbmc.LOGERROR)
            self.enabled = False

    def update(self, percent: int, message: str) -> None:
        if not self.enabled or self.dialog is None:
            return
        try:
            self.dialog.update(max(0, min(100, int(percent))), self.title, message)
        except Exception:
            log(f"Unable to update sync progress dialog: {traceback.format_exc()}", xbmc.LOGERROR)
            self.enabled = False

    def scope_item(
        self,
        scope: str,
        current: int,
        total: int,
        addon_id: str,
        percent: int,
        updating: bool = False,
    ) -> None:
        label = scope_label(scope)
        if updating:
            message = localized(32045, "{scope}: updating {addon}", scope=label, addon=addon_id)
        else:
            message = localized(
                32044,
                "{scope}: {current}/{total} - {addon}",
                scope=label,
                current=current,
                total=max(total, 1),
                addon=addon_id,
            )
        self.update(percent, message)

    def summary(self) -> str:
        return localized(
            32047,
            "Updated: {updated} | Current: {current} | Skipped: {skipped}",
            updated=self.updated,
            current=self.current,
            skipped=self.skipped,
        )

    def finish(self, success: bool) -> str:
        if success:
            message = localized(32050, "Synchronization complete - {summary}", summary=self.summary())
        else:
            message = localized(
                32049,
                "Synchronization failed - {errors} error(s) - {summary}",
                errors=max(self.errors, 1),
                summary=self.summary(),
            )
        self.update(100, message)
        self.close()
        return message

    def close(self) -> None:
        if self.dialog is None:
            return
        try:
            self.dialog.close()
        except Exception:
            log(f"Unable to close sync progress dialog: {traceback.format_exc()}", xbmc.LOGERROR)
        finally:
            self.dialog = None


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


def installed_addons(apply_filter: bool = True) -> dict[str, dict]:
    """Return installed Kodi add-ons, including disabled add-ons.

    Kodi JSON-RPC defaults to installed add-ons. Using ``enabled=all`` avoids
    silently omitting disabled add-ons from a Master snapshot.
    """
    response = _json_rpc(
        "Addons.GetAddons",
        {"enabled": "all", "installed": True, "properties": ["broken", "version", "name"]},
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
    return _apply_filter(addons) if apply_filter else addons


def addon_data_dir(addon_id: str) -> str:
    """Return this profile's data directory for an add-on."""
    return as_dir(xbmcvfs.translatePath(vfs_join("special://profile/addon_data", addon_id)))


def addon_install_dir(addon_id: str) -> str:
    """Return the user-installed add-on directory under special://home/addons."""
    return as_dir(xbmcvfs.translatePath(vfs_join("special://home/addons", addon_id)))


def master_profile_dir() -> str:
    """Return Kodi's master/default userdata directory."""
    return as_dir(xbmcvfs.translatePath("special://masterprofile"))


def playlists_dir() -> str:
    """Return the active profile's playlists directory."""
    return as_dir(xbmcvfs.translatePath("special://profile/playlists"))


def profiles_dir() -> str:
    """Return the directory containing additional Kodi profiles."""
    return as_dir(xbmcvfs.translatePath("special://masterprofile/profiles"))


def _work_dir(name: str) -> str:
    return as_dir(xbmcvfs.translatePath(vfs_join("special://temp", ADDON_ID, name)))


def _copy_file_if_exists(source: str, target: str) -> bool:
    if not xbmcvfs.exists(source):
        return True
    parent = target.rsplit(_separator(target), 1)[0] if _separator(target) in target else ""
    if parent and not ensure_dir(parent):
        return False
    if xbmcvfs.exists(target):
        xbmcvfs.delete(target)
    return bool(xbmcvfs.copy(source, target))


def _copy_directory_contents(source: str, target: str) -> bool:
    """Copy a directory tree; a missing source represents an empty scope."""
    if not ensure_dir(target):
        return False
    if not dir_exists(source):
        return True
    return copy_tree(source, target)


def build_folder_scope_snapshot(scope: str, destination: str) -> bool:
    """Build a deterministic snapshot for Config/Playlists/Profiles.

    Config is a virtual folder made from Kodi's portable master-profile
    configuration files and the keymaps/library configuration directories.
    Database/cache payloads and the separately selectable playlists/profiles
    areas are intentionally not included.
    """
    remove_tree(destination)
    if not ensure_dir(destination):
        return False

    if scope == SCOPE_PLAYLISTS:
        return _copy_directory_contents(playlists_dir(), destination)

    root = master_profile_dir()
    if scope == SCOPE_CONFIG:
        for filename in CONFIG_FILES:
            if not _copy_file_if_exists(vfs_join(root, filename), vfs_join(destination, filename)):
                return False
        for dirname in CONFIG_DIRS:
            src = vfs_join(root, dirname)
            if dir_exists(src) and not copy_tree(src, vfs_join(destination, dirname)):
                return False
        return True

    if scope == SCOPE_PROFILES:
        if not _copy_file_if_exists(vfs_join(root, "profiles.xml"), vfs_join(destination, "profiles.xml")):
            return False
        src_profiles = profiles_dir()
        if dir_exists(src_profiles) and not copy_tree(src_profiles, vfs_join(destination, "profiles")):
            return False
        return True

    raise ValueError(f"Unknown folder synchronization scope: {scope}")


def _clear_folder_scope_target(scope: str) -> bool:
    """Remove only files/directories controlled by a virtual folder scope."""
    if scope == SCOPE_PLAYLISTS:
        return remove_tree(playlists_dir())

    root = master_profile_dir()
    if scope == SCOPE_CONFIG:
        ok = True
        for filename in CONFIG_FILES:
            path = vfs_join(root, filename)
            if xbmcvfs.exists(path):
                ok = bool(xbmcvfs.delete(path)) and ok
        for dirname in CONFIG_DIRS:
            ok = remove_tree(vfs_join(root, dirname)) and ok
        return ok

    if scope == SCOPE_PROFILES:
        ok = remove_tree(profiles_dir())
        profiles_xml = vfs_join(root, "profiles.xml")
        if xbmcvfs.exists(profiles_xml):
            ok = bool(xbmcvfs.delete(profiles_xml)) and ok
        return ok

    raise ValueError(f"Unknown folder synchronization scope: {scope}")


def _install_folder_scope_snapshot(scope: str, snapshot: str) -> bool:
    """Install an already-verified folder-scope snapshot without verification."""
    if not _clear_folder_scope_target(scope):
        return False

    if scope == SCOPE_PLAYLISTS:
        return _copy_directory_contents(snapshot, playlists_dir())

    root = master_profile_dir()
    if scope == SCOPE_CONFIG:
        for filename in CONFIG_FILES:
            if not _copy_file_if_exists(vfs_join(snapshot, filename), vfs_join(root, filename)):
                return False
        for dirname in CONFIG_DIRS:
            src = vfs_join(snapshot, dirname)
            if dir_exists(src) and not copy_tree(src, vfs_join(root, dirname)):
                return False
        return True

    if scope == SCOPE_PROFILES:
        if not _copy_file_if_exists(vfs_join(snapshot, "profiles.xml"), vfs_join(root, "profiles.xml")):
            return False
        src_profiles = vfs_join(snapshot, "profiles")
        if dir_exists(src_profiles) and not copy_tree(src_profiles, profiles_dir()):
            return False
        return True

    raise ValueError(f"Unknown folder synchronization scope: {scope}")


def _replace_folder_scope_verified(scope: str, source: str, expected_hash: str) -> bool:
    """Replace a virtual folder scope with backup, rollback and hash verification."""
    backup = _work_dir(f"backup-{scope}")
    verify = _work_dir(f"verify-{scope}")
    remove_tree(backup)
    remove_tree(verify)

    if not build_folder_scope_snapshot(scope, backup):
        return False

    if not _install_folder_scope_snapshot(scope, source):
        _install_folder_scope_snapshot(scope, backup)
        remove_tree(backup)
        return False

    if not build_folder_scope_snapshot(scope, verify):
        _install_folder_scope_snapshot(scope, backup)
        remove_tree(backup)
        remove_tree(verify)
        return False

    installed_hash = hash_tree(verify)
    remove_tree(verify)
    if installed_hash == expected_hash:
        remove_tree(backup)
        return True

    log(
        f"Final verification failed for folder scope {scope}; restoring backup",
        xbmc.LOGERROR,
    )
    _install_folder_scope_snapshot(scope, backup)
    remove_tree(backup)
    return False


def scope_local_dir(scope: str, addon_id: str) -> str:
    if scope == SCOPE_ADDON_DATA:
        return addon_data_dir(addon_id)
    if scope == SCOPE_ADDONS:
        return addon_install_dir(addon_id)
    raise ValueError(f"Unknown add-on synchronization scope: {scope}")


def selected_sync_scopes() -> list[str]:
    scopes: list[str] = []
    if _setting_bool("syncAddonData", True):
        scopes.append(SCOPE_ADDON_DATA)
    if _setting_bool("syncAddonFiles", False):
        scopes.append(SCOPE_ADDONS)
    if _setting_bool("syncConfig", False):
        scopes.append(SCOPE_CONFIG)
    if _setting_bool("syncPlaylists", False):
        scopes.append(SCOPE_PLAYLISTS)
    if _setting_bool("syncProfiles", False):
        scopes.append(SCOPE_PROFILES)
    return scopes


def local_scope_details(
    scope: str,
    status: SyncStatus | None = None,
    scope_index: int = 0,
    scope_count: int = 1,
) -> dict[str, dict]:
    """Collect per-add-on details for the add-on based synchronization scopes."""
    if scope not in ADDON_SCOPES:
        raise ValueError(f"local_scope_details only supports add-on scopes: {scope}")
    details: dict[str, dict] = {}
    addons = installed_addons()
    total = len(addons)
    span = 85.0 / max(scope_count, 1)
    base = 5.0 + (scope_index * span)
    scan_span = span * 0.4

    if status is not None:
        status.update(
            int(base),
            localized(32042, "Master: checking {scope}", scope=scope_label(scope)),
        )

    for index, (addon_id, info) in enumerate(addons.items(), start=1):
        if status is not None:
            percent = int(base + scan_span * (index / max(total, 1)))
            status.scope_item(scope, index, total, addon_id, percent)
        path = scope_local_dir(scope, addon_id)
        if not dir_exists(path):
            if status is not None:
                status.skipped += 1
            continue
        details[addon_id] = {
            "version": info["version"],
            "dir": path,
            "hash": hash_tree(path),
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
            if isinstance(manifest.get("scopes"), dict):
                return manifest
            # Schema 2 stored addon_data directly in the top-level ``addons``
            # mapping and its files directly below the central store root.
            if isinstance(manifest.get("addons"), dict):
                return {
                    "schema": int(manifest.get("schema", 2) or 2),
                    "algorithm": manifest.get("algorithm", ""),
                    "generated_utc": manifest.get("generated_utc", ""),
                    "legacy_layout": True,
                    "scopes": {
                        SCOPE_ADDON_DATA: {"addons": manifest.get("addons", {})},
                    },
                }
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
            "legacy_layout": True,
            "scopes": {SCOPE_ADDON_DATA: {"addons": addons}},
        }
    except ET.ParseError:
        log(f"Invalid legacy {LEGACY_MANIFEST_NAME}: {traceback.format_exc()}", xbmc.LOGERROR)
        return None


def write_manifest(store: str, scopes: dict[str, dict]) -> bool:
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "algorithm": HASH_ALGORITHM,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "scopes": scopes,
    }
    content = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False)
    tmp = vfs_join(store, f".{MANIFEST_NAME}.tmp")
    final = vfs_join(store, MANIFEST_NAME)
    if not _write_text(tmp, content):
        return False
    if xbmcvfs.exists(final):
        xbmcvfs.delete(final)
    if xbmcvfs.rename(tmp, final):
        return True
    success = _write_text(final, content)
    xbmcvfs.delete(tmp)
    return success


def scope_store_dir(store: str, scope: str, addon_id: str, manifest: dict | None = None) -> str:
    if manifest and manifest.get("legacy_layout") and scope == SCOPE_ADDON_DATA:
        return vfs_join(store, addon_id)
    return vfs_join(store, scope, addon_id)


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

    # xbmcvfs.rename() is documented for files, not directory trees. Copy the
    # verified staging tree into place and then remove staging. The pre-copy
    # safety backup above provides rollback if this final installation fails.
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


def _scope_manifest_items(manifest: dict, scope: str) -> dict[str, dict]:
    scope_data = manifest.get("scopes", {}).get(scope, {})
    items = scope_data.get("addons", {}) if isinstance(scope_data, dict) else {}
    return items if isinstance(items, dict) else {}


def _scope_manifest_folder(manifest: dict, scope: str) -> dict:
    scope_data = manifest.get("scopes", {}).get(scope, {})
    folder = scope_data.get("folder", {}) if isinstance(scope_data, dict) else {}
    return folder if isinstance(folder, dict) else {}


def folder_scope_store_dir(store: str, scope: str) -> str:
    return vfs_join(store, scope, "content")


def _sync_master_addon_scope(
    store: str,
    old_manifest: dict,
    scope: str,
    status: SyncStatus | None,
    scope_index: int,
    scope_count: int,
) -> tuple[bool, dict]:
    old_items = _scope_manifest_items(old_manifest, scope)
    details = local_scope_details(scope, status, scope_index, scope_count)
    new_items: dict[str, dict] = {}
    scope_root = vfs_join(store, scope)
    if not ensure_dir(scope_root):
        if status is not None:
            status.errors += 1
        return False, {"addons": new_items}

    span = 85.0 / max(scope_count, 1)
    base = 5.0 + (scope_index * span)
    transfer_base = base + (span * 0.4)
    transfer_span = span * 0.6
    total = len(details)
    success = True

    for index, (addon_id, detail) in enumerate(details.items(), start=1):
        if status is not None:
            percent = int(transfer_base + transfer_span * (index / max(total, 1)))
            status.scope_item(scope, index, total, addon_id, percent, updating=True)

        source_hash = detail.get("hash")
        source_dir = detail.get("dir")
        if not source_hash or not source_dir or not dir_exists(source_dir):
            if status is not None:
                status.skipped += 1
            continue

        target_dir = scope_store_dir(store, scope, addon_id)
        old = old_items.get(addon_id, {})
        unchanged = (
            old_manifest.get("algorithm") == HASH_ALGORITHM
            and not old_manifest.get("legacy_layout")
            and old.get("hash") == source_hash
            and dir_exists(target_dir)
        )
        if not unchanged:
            log(f"Master [{scope}]: updating {addon_id}")
            if not _replace_tree_verified(source_dir, target_dir, source_hash):
                success = False
                if status is not None:
                    status.errors += 1
                if old and dir_exists(target_dir):
                    new_items[addon_id] = old
                continue
            if status is not None:
                status.updated += 1
        else:
            log(f"Master [{scope}]: {addon_id} already current")
            if status is not None:
                status.current += 1

        new_items[addon_id] = {
            "version": detail["version"],
            "hash": source_hash,
        }

    return success, {"addons": new_items}


def _sync_master_folder_scope(
    store: str,
    old_manifest: dict,
    scope: str,
    status: SyncStatus | None,
    scope_index: int,
    scope_count: int,
) -> tuple[bool, dict]:
    span = 85.0 / max(scope_count, 1)
    base = 5.0 + (scope_index * span)
    source = _work_dir(f"master-{scope}")
    if status is not None:
        status.update(
            int(base),
            localized(32042, "Master: checking {scope}", scope=scope_label(scope)),
        )

    if not build_folder_scope_snapshot(scope, source):
        if status is not None:
            status.errors += 1
        remove_tree(source)
        return False, {"folder": {}}

    source_hash = hash_tree(source)
    target = folder_scope_store_dir(store, scope)
    old = _scope_manifest_folder(old_manifest, scope)
    unchanged = (
        old_manifest.get("algorithm") == HASH_ALGORITHM
        and old.get("hash") == source_hash
        and source_hash is not None
        and dir_exists(target)
    )

    if status is not None:
        status.update(
            int(base + span * 0.65),
            localized(32061, "{scope}: synchronizing", scope=scope_label(scope)),
        )

    success = True
    if not source_hash:
        success = False
        if status is not None:
            status.errors += 1
    elif unchanged:
        log(f"Master [{scope}]: already current")
        if status is not None:
            status.current += 1
    else:
        log(f"Master [{scope}]: updating")
        if _replace_tree_verified(source, target, source_hash):
            if status is not None:
                status.updated += 1
        else:
            success = False
            if status is not None:
                status.errors += 1

    remove_tree(source)
    return success, {"folder": {"hash": source_hash or ""}}


def sync_master(store: str, status: SyncStatus | None = None) -> bool:
    if not ensure_dir(store):
        log(f"Central store is not writable/available: {store}", xbmc.LOGERROR)
        if status is not None:
            status.errors += 1
        return False

    scopes = selected_sync_scopes()
    if not scopes:
        log("No synchronization folders are selected", xbmc.LOGERROR)
        if status is not None:
            status.errors += 1
        return False

    old_manifest = read_manifest(store) or {"scopes": {}}
    new_scopes: dict[str, dict] = {}
    success = True
    scope_count = len(scopes)

    for scope_index, scope in enumerate(scopes):
        if scope in ADDON_SCOPES:
            scope_ok, scope_manifest = _sync_master_addon_scope(
                store, old_manifest, scope, status, scope_index, scope_count
            )
        else:
            scope_ok, scope_manifest = _sync_master_folder_scope(
                store, old_manifest, scope, status, scope_index, scope_count
            )
        new_scopes[scope] = scope_manifest
        success = scope_ok and success

    if status is not None:
        status.update(95, localized(32046, "Writing synchronization manifest"))
    if not write_manifest(store, new_scopes):
        success = False
        if status is not None:
            status.errors += 1
    return success

def _verify_remote_tree(source_dir: str, expected_hash: str, algorithm: str) -> str | None:
    if algorithm != HASH_ALGORITHM:
        return hash_tree(source_dir)
    remote_hash = hash_tree(source_dir)
    if remote_hash != expected_hash:
        return None
    return remote_hash


def _sync_slave_scope(
    store: str,
    manifest: dict,
    scope: str,
    installed: dict[str, dict],
    service_addons: set[str],
    code_updated: set[str],
    status: SyncStatus | None = None,
    scope_index: int = 0,
    scope_count: int = 1,
) -> tuple[bool, set[str]]:
    """Synchronize one folder scope and return (success, changed addon ids)."""
    remote_items = _apply_filter(_scope_manifest_items(manifest, scope))
    algorithm = manifest.get("algorithm", "")
    changed: set[str] = set()
    success = True
    total = len(remote_items)
    span = 85.0 / max(scope_count, 1)
    base = 5.0 + (scope_index * span)

    if status is not None:
        status.update(
            int(base),
            localized(32043, "Client: checking {scope}", scope=scope_label(scope)),
        )

    for index, (addon_id, remote) in enumerate(remote_items.items(), start=1):
        percent = int(base + span * (index / max(total, 1)))
        if status is not None:
            status.scope_item(scope, index, total, addon_id, percent)

        local_info = installed.get(addon_id)

        # Keep the historical behavior for addon_data-only setups: data for an
        # add-on that is not installed locally is ignored. If add-on files were
        # synchronized in this same run, its data can safely follow immediately.
        if scope == SCOPE_ADDON_DATA and local_info is None and addon_id not in code_updated:
            log(f"Client [{scope}]: skipping {addon_id}; add-on is not installed locally")
            if status is not None:
                status.skipped += 1
            continue

        if scope == SCOPE_ADDON_DATA and version_match_required() and addon_id not in code_updated:
            if local_info and local_info.get("version") != remote.get("version"):
                log(
                    f"Client [{scope}]: version mismatch for {addon_id}: "
                    f"local={local_info.get('version')} master={remote.get('version')}"
                )
                if status is not None:
                    status.skipped += 1
                continue

        source_dir = scope_store_dir(store, scope, addon_id, manifest)
        if not dir_exists(source_dir):
            log(f"Client [{scope}]: master data missing for {addon_id}: {source_dir}", xbmc.LOGERROR)
            success = False
            if status is not None:
                status.errors += 1
            continue

        expected_hash = remote.get("hash")
        if algorithm != HASH_ALGORITHM:
            expected_hash = hash_tree(source_dir)
        if not expected_hash:
            success = False
            if status is not None:
                status.errors += 1
            continue

        target_dir = scope_local_dir(scope, addon_id)
        local_hash = hash_tree(target_dir) if dir_exists(target_dir) else None
        if local_hash == expected_hash:
            log(f"Client [{scope}]: {addon_id} already current")
            if status is not None:
                status.current += 1
            continue

        if _verify_remote_tree(source_dir, expected_hash, algorithm) is None:
            log(
                f"Client [{scope}]: central data verification failed for {addon_id}",
                xbmc.LOGERROR,
            )
            success = False
            if status is not None:
                status.errors += 1
            continue

        if status is not None:
            status.scope_item(scope, index, total, addon_id, percent, updating=True)

        disabled_for_sync = addon_id in service_addons
        if disabled_for_sync:
            log(f"Client [{scope}]: stopping service add-on {addon_id}")
            _set_addon_enabled(addon_id, False)
            xbmc.Monitor().waitForAbort(0.5)

        try:
            log(f"Client [{scope}]: updating {addon_id}")
            if _replace_tree_verified(source_dir, target_dir, expected_hash):
                changed.add(addon_id)
                if status is not None:
                    status.updated += 1
            else:
                success = False
                if status is not None:
                    status.errors += 1
        finally:
            if disabled_for_sync:
                log(f"Client [{scope}]: starting service add-on {addon_id}")
                _set_addon_enabled(addon_id, True)

    return success, changed


def _sync_slave_folder_scope(
    store: str,
    manifest: dict,
    scope: str,
    status: SyncStatus | None = None,
    scope_index: int = 0,
    scope_count: int = 1,
) -> tuple[bool, bool]:
    """Synchronize Config/Playlists/Profiles. Returns (success, changed)."""
    remote = _scope_manifest_folder(manifest, scope)
    expected_hash = remote.get("hash", "")
    if not expected_hash:
        return True, False

    source = folder_scope_store_dir(store, scope)
    if not dir_exists(source):
        log(f"Client [{scope}]: master folder missing: {source}", xbmc.LOGERROR)
        if status is not None:
            status.errors += 1
        return False, False

    span = 85.0 / max(scope_count, 1)
    base = 5.0 + (scope_index * span)
    if status is not None:
        status.update(
            int(base),
            localized(32043, "Client: checking {scope}", scope=scope_label(scope)),
        )

    local_snapshot = _work_dir(f"client-{scope}")
    if not build_folder_scope_snapshot(scope, local_snapshot):
        if status is not None:
            status.errors += 1
        remove_tree(local_snapshot)
        return False, False
    local_hash = hash_tree(local_snapshot)
    remove_tree(local_snapshot)

    if local_hash == expected_hash:
        log(f"Client [{scope}]: already current")
        if status is not None:
            status.current += 1
        return True, False

    if _verify_remote_tree(source, expected_hash, manifest.get("algorithm", "")) is None:
        log(f"Client [{scope}]: central folder verification failed", xbmc.LOGERROR)
        if status is not None:
            status.errors += 1
        return False, False

    if status is not None:
        status.update(
            int(base + span * 0.7),
            localized(32061, "{scope}: synchronizing", scope=scope_label(scope)),
        )

    log(f"Client [{scope}]: updating")
    if _replace_folder_scope_verified(scope, source, expected_hash):
        if status is not None:
            status.updated += 1
        return True, True

    if status is not None:
        status.errors += 1
    return False, False


def _scope_has_remote_data(manifest: dict, scope: str) -> bool:
    if scope in ADDON_SCOPES:
        return bool(_scope_manifest_items(manifest, scope))
    return bool(_scope_manifest_folder(manifest, scope).get("hash"))


def sync_slave(store: str, status: SyncStatus | None = None) -> bool:
    if status is not None:
        status.update(3, localized(32048, "Reading synchronization manifest"))
    manifest = read_manifest(store)
    if not manifest:
        log(f"No manifest found in {store}", xbmc.LOGERROR)
        notify(32034)
        if status is not None:
            status.errors += 1
        return False

    scopes = selected_sync_scopes()
    if not scopes:
        log("No synchronization folders are selected", xbmc.LOGERROR)
        if status is not None:
            status.errors += 1
        return False

    installed = installed_addons(apply_filter=False)
    restart_services = _setting_bool("restartUpdatedServiceAddons", False)
    service_addons = _service_addons() if restart_services else set()
    success = True
    code_updated: set[str] = set()
    changed_folder_scopes: set[str] = set()

    active_scopes = [scope for scope in SCOPE_ORDER if scope in scopes and _scope_has_remote_data(manifest, scope)]
    scope_count = max(len(active_scopes), 1)
    scope_index = 0

    # Add-on program files are synchronized first. That allows addon_data for a
    # newly copied add-on to be synchronized in the same pass.
    for scope in active_scopes:
        if scope == SCOPE_ADDONS:
            scope_ok, code_updated = _sync_slave_scope(
                store,
                manifest,
                scope,
                installed,
                service_addons,
                set(),
                status,
                scope_index,
                scope_count,
            )
        elif scope == SCOPE_ADDON_DATA:
            scope_ok, _ = _sync_slave_scope(
                store,
                manifest,
                scope,
                installed,
                service_addons,
                code_updated,
                status,
                scope_index,
                scope_count,
            )
        else:
            scope_ok, changed = _sync_slave_folder_scope(
                store,
                manifest,
                scope,
                status,
                scope_index,
                scope_count,
            )
            if changed:
                changed_folder_scopes.add(scope)
        scope_index += 1
        success = scope_ok and success

    if code_updated:
        log(
            "Client: installed add-on files changed; a Kodi restart is recommended: "
            + ", ".join(sorted(code_updated)),
            xbmc.LOGINFO,
        )
        notify(32040, 7000)

    if changed_folder_scopes.intersection({SCOPE_CONFIG, SCOPE_PROFILES}):
        log(
            "Client: Kodi configuration/profile data changed; a Kodi restart is recommended",
            xbmc.LOGINFO,
        )
        notify(32062, 7000)

    return success

def sync_once(show_notifications: bool = False) -> bool:
    home = xbmcgui.Window(10000)
    if home.getProperty(LOCK_PROPERTY) == "true":
        log("Synchronization skipped because another AddonSync run is active")
        if show_notifications:
            notify(32035)
        return False

    scopes = selected_sync_scopes()
    if not scopes:
        log("No synchronization folders are selected", xbmc.LOGERROR)
        if show_notifications:
            notify(32039)
            ADDON.openSettings()
        return False

    store = central_store()
    if not store:
        log("Central store is not configured", xbmc.LOGERROR)
        if show_notifications:
            notify(32032)
            ADDON.openSettings()
        return False

    status_enabled = _setting_bool("showSyncStatus", True)
    status = SyncStatus(status_enabled)

    home.setProperty(LOCK_PROPERTY, "true")
    try:
        status.start()
        if show_notifications and not status.enabled:
            notify(32030, 2500)

        ok = sync_master(store, status) if is_master() else sync_slave(store, status)
        final_message = status.finish(ok)

        # Manual runs always report their final state. Automatic service runs
        # also report it when background sync-status notifications are enabled.
        if show_notifications or status_enabled:
            notify_text(final_message, 6000)
        return ok
    except Exception:
        log(f"Unhandled synchronization error: {traceback.format_exc()}", xbmc.LOGERROR)
        status.errors += 1
        final_message = status.finish(False)
        if show_notifications or status_enabled:
            notify_text(final_message or localized(32033, "Synchronization failed. See the Kodi log for details."))
        return False
    finally:
        status.close()
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
        {"enabled": "all", "installed": True, "properties": ["broken", "name"]},
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
