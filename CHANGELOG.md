# Changelog

All notable changes to this fork are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Version numbers follow the existing AddonSync numbering scheme.

## 102.2.0 - 2026-08-16

- Added separately selectable **Config**, **Playlists** and **Profiles** synchronization scopes.
- Config synchronizes portable master-profile configuration files plus `keymaps` and `library`; Kodi databases, thumbnails and the separately selectable add-on/playlists/profiles payloads are excluded.
- Playlists synchronizes the active profile's `playlists` directory.
- Profiles synchronizes both `profiles.xml` and the `profiles/` directory.
- Folder scopes use staged SHA-256 snapshots, verified central copies, Client backups and rollback on verification failure.
- Manifest schema is now version 4 while schema 1-3 data remains readable.
- Config/Profile changes recommend a Kodi restart.

## 102.1.1 - 2026-08-16

- Added native Kodi `DialogProgressBG` synchronization status.
- Shows active scope, current add-on and approximate progress during Master and Client synchronization.
- Final notification includes updated, already-current and skipped counts.
- Added `Show synchronization status` setting, enabled by default.

## [102.1.0] - 2026-08-16

### Added

- Added a **Synchronization folders** settings page.
- Added independent switches for `userdata/addon_data` and installed add-on program files.
- Added Master-to-Client synchronization of user-installed add-ons from `special://home/addons`.
- Added support for copying an add-on that is missing on a Client; its `addon_data` can follow in the same synchronization pass.
- Added a restart recommendation when Client add-on program files changed.

### Changed

- Manifest schema is now version 3 with separate `addon_data` and `addons` scopes.
- The existing add-on include/exclude filter applies to both synchronization scopes.
- Disabled but installed add-ons are now visible to synchronization/filter discovery.
- 102.0.x JSON manifests and older `hashdata.xml` stores remain readable for migration.

### Safety

- Add-on file synchronization is **disabled by default** and must be explicitly enabled.
- `service.addonsync` itself and the existing safety-excluded add-on classes are not copied.
- Add-on program files can be platform-specific; use this feature only between compatible Kodi installations and restart Kodi after code changes.

## [102.0.1] - 2026-08-16

### Fixed

- Fixed blank or missing labels in Kodi's add-on settings dialog.
- Normalized Kodi gettext (`strings.po`) catalogs.
- Added an explicit `resource.language.en_us` fallback catalog.

## [102.0.0] - 2026-08-16

### Changed

- Reworked the Kodi service and manual entry points for Python 3.
- Moved synchronization behavior into a single modernized core module.
- Replaced the old timestamp/hash index with a JSON SHA-256 manifest.
- Added compatibility reading for legacy `hashdata.xml` data.
- Switched recursive file operations to Kodi VFS so local, SMB and NFS paths use the same code path.
- Stage and verify client copies before replacing local add-on settings.
- Preserve the existing AddonSync add-on id and important setting ids for in-place upgrades.

### Fixed

- Fixed hashing code that passed Python strings to `hashlib.update()` under Python 3.
- Fixed dictionary access that accidentally used Python's built-in `hash` object instead of the string key `"hash"`.
- Fixed Master updates being skipped for add-ons already present in the manifest.
- Fixed manifest regeneration occurring in the wrong exception path.
- Fixed recursive copy target paths being written as the literal string `"{root_target_dir}{file}"`.
- Fixed the manual synchronization action referencing a missing `resources/lib/default.py` file.
- Fixed broken package-relative imports in the former entry-point layout.

## Upstream 101.x

The 101.x history belongs to the upstream project. See the upstream repository for the complete pre-fork history:
https://github.com/RogueScholar/service.addonsync
