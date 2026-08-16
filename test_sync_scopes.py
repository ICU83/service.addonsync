#!/usr/bin/env python3
"""Lightweight filesystem simulation for AddonSync's selectable sync scopes."""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import shutil
import sys
import tempfile
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / "resources" / "lib" / "addonsync.py"


class FakeKodiFile:
    def __init__(self, path: str, mode: str = "r"):
        path = path.rstrip("/\\")
        pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
        binary = "b" in mode
        if "w" in mode:
            self.handle = open(path, "wb" if binary else "w", encoding=None if binary else "utf-8")
        else:
            self.handle = open(path, "rb" if binary else "r", encoding=None if binary else "utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def read(self):
        return self.handle.read()

    def readBytes(self, size: int):
        if "b" not in self.handle.mode:
            # Hashing needs raw bytes even though Kodi's File object itself has
            # no separate binary open mode requirement.
            pos = self.handle.tell()
            self.handle.close()
            self.handle = open(self.handle.name, "rb")
            self.handle.seek(pos)
        return self.handle.read(size)

    def write(self, value):
        return self.handle.write(value)

    def close(self):
        if not self.handle.closed:
            self.handle.close()


class FakeAddon:
    settings: dict[str, str] = {}

    def __init__(self, id=None):
        self.id = id or "service.addonsync"

    def getSetting(self, key):
        return self.settings.get(key, "")

    def setSetting(self, key, value):
        self.settings[key] = str(value)

    def getLocalizedString(self, _key):
        return ""

    def getAddonInfo(self, key):
        if key == "version":
            return "102.2.0"
        return ""

    def openSettings(self):
        return None


class FakeWindow:
    props: dict[str, str] = {}

    def __init__(self, _id):
        pass

    def getProperty(self, key):
        return self.props.get(key, "")

    def setProperty(self, key, value):
        self.props[key] = value

    def clearProperty(self, key):
        self.props.pop(key, None)


class FakeDialog:
    def notification(self, *_args, **_kwargs):
        return None

    def ok(self, *_args, **_kwargs):
        return None

    def multiselect(self, *_args, **_kwargs):
        return None


class FakeDialogProgressBG:
    events: list[tuple] = []

    def create(self, *args):
        self.events.append(("create",) + args)

    def update(self, *args):
        self.events.append(("update",) + args)

    def close(self):
        self.events.append(("close",))


class FakeMonitor:
    def abortRequested(self):
        return False

    def waitForAbort(self, _seconds):
        return False


def install_fake_modules():
    xbmc = types.ModuleType("xbmc")
    xbmc.LOGDEBUG = 0
    xbmc.LOGINFO = 1
    xbmc.LOGERROR = 4
    xbmc.log = lambda *_args, **_kwargs: None
    xbmc.executeJSONRPC = lambda *_args, **_kwargs: json.dumps({"result": {"addons": []}})
    xbmc.Monitor = FakeMonitor
    sys.modules["xbmc"] = xbmc

    xbmcgui = types.ModuleType("xbmcgui")
    xbmcgui.Window = FakeWindow
    xbmcgui.Dialog = FakeDialog
    xbmcgui.DialogProgressBG = FakeDialogProgressBG
    sys.modules["xbmcgui"] = xbmcgui

    xbmcvfs = types.ModuleType("xbmcvfs")
    xbmcvfs.File = FakeKodiFile
    xbmcvfs.translatePath = lambda path: path
    xbmcvfs.exists = lambda path: os.path.exists(path.rstrip("/\\"))
    xbmcvfs.mkdirs = lambda path: (os.makedirs(path.rstrip("/\\"), exist_ok=True) is None) or True
    xbmcvfs.listdir = lambda path: _listdir(path)
    xbmcvfs.copy = lambda src, dst: _copy(src, dst)
    xbmcvfs.delete = lambda path: _delete(path)
    xbmcvfs.rmdir = lambda path, force=False: _rmdir(path, force)
    xbmcvfs.rename = lambda src, dst: _rename(src, dst)
    sys.modules["xbmcvfs"] = xbmcvfs

    xbmcaddon = types.ModuleType("xbmcaddon")
    xbmcaddon.Addon = FakeAddon
    sys.modules["xbmcaddon"] = xbmcaddon


def _listdir(path):
    base = path.rstrip("/\\")
    dirs, files = [], []
    for name in os.listdir(base):
        (dirs if os.path.isdir(os.path.join(base, name)) else files).append(name)
    return dirs, files


def _copy(src, dst):
    try:
        pathlib.Path(dst.rstrip("/\\")).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src.rstrip("/\\"), dst.rstrip("/\\"))
        return True
    except OSError:
        return False


def _delete(path):
    try:
        os.remove(path.rstrip("/\\"))
        return True
    except FileNotFoundError:
        return False


def _rmdir(path, force=False):
    try:
        target = path.rstrip("/\\")
        if force:
            shutil.rmtree(target)
        else:
            os.rmdir(target)
        return True
    except OSError:
        return False


def _rename(src, dst):
    try:
        os.rename(src.rstrip("/\\"), dst.rstrip("/\\"))
        return True
    except OSError:
        return False


def load_core():
    install_fake_modules()
    spec = importlib.util.spec_from_file_location("addonsync_test_core", CORE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def write(path: pathlib.Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main():
    core = load_core()

    # Native background notification must support start, progress and summary.
    FakeDialogProgressBG.events.clear()
    status = core.SyncStatus(True)
    status.start()
    status.scope_item(core.SCOPE_ADDON_DATA, 1, 2, "plugin.video.demo", 35)
    status.updated = 1
    summary = status.finish(True)
    assert "Updated: 1" in summary
    assert any(event[0] == "create" for event in FakeDialogProgressBG.events)
    assert any(event[0] == "update" and event[1] == 35 for event in FakeDialogProgressBG.events)
    assert FakeDialogProgressBG.events[-1][0] == "close"

    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp)
        master_addons = base / "master" / "addons"
        master_data = base / "master" / "addon_data"
        client_addons = base / "client" / "addons"
        client_data = base / "client" / "addon_data"
        master_profile = base / "master" / "userdata"
        client_profile = base / "client" / "userdata"
        work = base / "work"
        store = base / "store"

        addon_id = "plugin.video.demo"
        write(master_addons / addon_id / "addon.xml", '<addon id="plugin.video.demo" version="1.0.0"/>')
        write(master_addons / addon_id / "main.py", "VALUE = 1\n")
        write(master_data / addon_id / "settings.xml", "<settings><x>master</x></settings>\n")
        write(master_profile / "advancedsettings.xml", "<advancedsettings><master>1</master></advancedsettings>\n")
        write(master_profile / "keymaps" / "keyboard.xml", "<keymap><master>1</master></keymap>\n")
        write(master_profile / "playlists" / "video" / "demo.xsp", "<smartplaylist><master>1</master></smartplaylist>\n")
        write(master_profile / "profiles.xml", "<profiles><profile>Kids</profile></profiles>\n")
        write(master_profile / "profiles" / "Kids" / "guisettings.xml", "<settings><master>1</master></settings>\n")
        # Database/Thumbnails are deliberately excluded from the Config scope.
        write(master_profile / "Database" / "Videos999.db", "do-not-sync")
        write(master_profile / "Thumbnails" / "cache.jpg", "do-not-sync")

        FakeAddon.settings = {
            "syncAddonData": "true",
            "syncAddonFiles": "true",
            "syncConfig": "true",
            "syncPlaylists": "true",
            "syncProfiles": "true",
            "forceVersionMatch": "true",
            "filterType": "0",
            "restartUpdatedServiceAddons": "false",
        }

        current = {addon_id: {"version": "1.0.0", "name": "Demo"}}
        core.installed_addons = lambda apply_filter=True: dict(current)
        core.addon_install_dir = lambda aid: str(master_addons / aid) + os.sep
        core.addon_data_dir = lambda aid: str(master_data / aid) + os.sep
        core.master_profile_dir = lambda: str(master_profile) + os.sep
        core.playlists_dir = lambda: str(master_profile / "playlists") + os.sep
        core.profiles_dir = lambda: str(master_profile / "profiles") + os.sep
        core._work_dir = lambda name: str(work / name) + os.sep

        assert core.sync_master(str(store) + os.sep)
        manifest = json.loads((store / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["schema"] == 4
        assert addon_id in manifest["scopes"]["addons"]["addons"]
        assert addon_id in manifest["scopes"]["addon_data"]["addons"]
        assert manifest["scopes"]["config"]["folder"]["hash"]
        assert manifest["scopes"]["playlists"]["folder"]["hash"]
        assert manifest["scopes"]["profiles"]["folder"]["hash"]
        assert not (store / "config" / "content" / "Database").exists()
        assert not (store / "config" / "content" / "Thumbnails").exists()

        # Client starts without the add-on. Code scope must install the folder,
        # then addon_data must follow in the same synchronization pass.
        current.clear()
        write(client_profile / "advancedsettings.xml", "<advancedsettings><client>old</client></advancedsettings>\n")
        write(client_profile / "playlists" / "video" / "old.xsp", "old playlist")
        write(client_profile / "profiles.xml", "<profiles><profile>Old</profile></profiles>\n")
        write(client_profile / "profiles" / "Old" / "guisettings.xml", "old profile")
        core.addon_install_dir = lambda aid: str(client_addons / aid) + os.sep
        core.addon_data_dir = lambda aid: str(client_data / aid) + os.sep
        core.master_profile_dir = lambda: str(client_profile) + os.sep
        core.playlists_dir = lambda: str(client_profile / "playlists") + os.sep
        core.profiles_dir = lambda: str(client_profile / "profiles") + os.sep
        assert core.sync_slave(str(store) + os.sep)
        assert (client_addons / addon_id / "main.py").read_text(encoding="utf-8") == "VALUE = 1\n"
        assert "master" in (client_data / addon_id / "settings.xml").read_text(encoding="utf-8")
        assert "master" in (client_profile / "advancedsettings.xml").read_text(encoding="utf-8")
        assert (client_profile / "keymaps" / "keyboard.xml").exists()
        assert (client_profile / "playlists" / "video" / "demo.xsp").exists()
        assert not (client_profile / "playlists" / "video" / "old.xsp").exists()
        assert "Kids" in (client_profile / "profiles.xml").read_text(encoding="utf-8")
        assert (client_profile / "profiles" / "Kids" / "guisettings.xml").exists()
        assert not (client_profile / "profiles" / "Old").exists()

        # A second Master change must propagate to all selected scopes.
        write(master_addons / addon_id / "main.py", "VALUE = 2\n")
        write(master_data / addon_id / "settings.xml", "<settings><x>changed</x></settings>\n")
        write(master_profile / "advancedsettings.xml", "<advancedsettings><master>2</master></advancedsettings>\n")
        write(master_profile / "playlists" / "video" / "demo.xsp", "<smartplaylist><master>2</master></smartplaylist>\n")
        write(master_profile / "profiles" / "Kids" / "guisettings.xml", "<settings><master>2</master></settings>\n")
        current[addon_id] = {"version": "1.0.0", "name": "Demo"}
        core.addon_install_dir = lambda aid: str(master_addons / aid) + os.sep
        core.addon_data_dir = lambda aid: str(master_data / aid) + os.sep
        core.master_profile_dir = lambda: str(master_profile) + os.sep
        core.playlists_dir = lambda: str(master_profile / "playlists") + os.sep
        core.profiles_dir = lambda: str(master_profile / "profiles") + os.sep
        assert core.sync_master(str(store) + os.sep)

        core.addon_install_dir = lambda aid: str(client_addons / aid) + os.sep
        core.addon_data_dir = lambda aid: str(client_data / aid) + os.sep
        core.master_profile_dir = lambda: str(client_profile) + os.sep
        core.playlists_dir = lambda: str(client_profile / "playlists") + os.sep
        core.profiles_dir = lambda: str(client_profile / "profiles") + os.sep
        assert core.sync_slave(str(store) + os.sep)
        assert (client_addons / addon_id / "main.py").read_text(encoding="utf-8") == "VALUE = 2\n"
        assert "changed" in (client_data / addon_id / "settings.xml").read_text(encoding="utf-8")
        assert "master>2" in (client_profile / "advancedsettings.xml").read_text(encoding="utf-8")
        assert "master>2" in (client_profile / "playlists" / "video" / "demo.xsp").read_text(encoding="utf-8")
        assert "master>2" in (client_profile / "profiles" / "Kids" / "guisettings.xml").read_text(encoding="utf-8")

        # Disabling code synchronization must leave Client add-on code intact.
        FakeAddon.settings["syncAddonFiles"] = "false"
        write(master_addons / addon_id / "main.py", "VALUE = 3\n")
        core.addon_install_dir = lambda aid: str(master_addons / aid) + os.sep
        core.addon_data_dir = lambda aid: str(master_data / aid) + os.sep
        core.master_profile_dir = lambda: str(master_profile) + os.sep
        core.playlists_dir = lambda: str(master_profile / "playlists") + os.sep
        core.profiles_dir = lambda: str(master_profile / "profiles") + os.sep
        assert core.sync_master(str(store) + os.sep)
        core.addon_install_dir = lambda aid: str(client_addons / aid) + os.sep
        core.addon_data_dir = lambda aid: str(client_data / aid) + os.sep
        core.master_profile_dir = lambda: str(client_profile) + os.sep
        core.playlists_dir = lambda: str(client_profile / "playlists") + os.sep
        core.profiles_dir = lambda: str(client_profile / "profiles") + os.sep
        assert core.sync_slave(str(store) + os.sep)
        assert (client_addons / addon_id / "main.py").read_text(encoding="utf-8") == "VALUE = 2\n"

    print("PASS: selectable addon/addon_data/config/playlists/profiles synchronization scopes")


if __name__ == "__main__":
    main()
