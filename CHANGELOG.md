# Changelog

All notable changes to this fork are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Version numbers follow the existing AddonSync numbering scheme.

## [102.0.2] - 2026-08-16

### Changed

- Pointed the Kodi add-on source metadata to the maintained fork at `ICU83/service.addonsync`.
- Updated provider and localization support metadata for the ICU83-maintained 102.x line.
- Documented the fork repository and upstream attribution explicitly.

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
