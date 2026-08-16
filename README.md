# AddonSync — modernized fork

AddonSync synchronizes selected Kodi add-on folders from one designated **Master** installation to one or more **Clients** through a shared storage location. Version 102.2.x can synchronize add-on data, user-installed add-on program files, Kodi configuration, playlists and profiles as independently selectable scopes.

This repository contains the modernized **102.x** line. It keeps the original Kodi add-on id, `service.addonsync`, while replacing synchronization code that no longer behaved correctly on Python 3/current Kodi installations.

> **Fork status:** community modernization of the original project. This repository is not an official release from the upstream maintainer unless your fork is later merged upstream.


AddonSync can show a native Kodi background progress notification while synchronization is running, including the active scope, current add-on, progress, and a final summary. This can be disabled in the add-on settings.

## Compatibility target

- Kodi 21 (Omega)
- Kodi 22 (Piers) compatibility target
- Python 3 / `xbmc.python >= 3.0.0`
- Local storage and Kodi VFS-backed network locations such as SMB/NFS

The manifest still declares `xbmc.python >= 3.0.0`, so the add-on may load on Kodi 19+, but the maintained test target for this fork is current Kodi.

## What changed in 102.x

- Correct Python 3 hashing.
- Correct Master update detection.
- Kodi VFS for recursive reads/copies and network paths.
- SHA-256 tree hashes in `manifest.json`.
- Legacy `hashdata.xml` read fallback.
- Staged and hash-verified client copies before replacement.
- Working root-level service/manual entry points.
- Working manual sync/filter actions.
- Kodi-compatible language catalogs, including German, English (UK) and English (US).
- Selectable synchronization scopes: add-on data, installed add-ons, Config, Playlists and Profiles.
- Master-to-Client deployment/update of user-installed add-on folders.
- Verified folder snapshots for Config, Playlists and Profiles with Client rollback.

See [`CHANGELOG.md`](CHANGELOG.md) for the detailed list.

## Synchronization folders

The **Synchronization folders** page lets each Kodi installation choose which scopes it participates in:

- **Add-on data** — `special://profile/addon_data/<addon-id>` (enabled by default).
- **Installed add-on files** — `special://home/addons/<addon-id>` (disabled by default).
- **Config** — portable files from `special://masterprofile` plus `keymaps` and `library`; databases, thumbnails, playlists, profiles and add-on data are excluded (disabled by default).
- **Playlists** — `special://profile/playlists` for the active profile (disabled by default).
- **Profiles** — `special://masterprofile/profiles` together with `profiles.xml` (disabled by default).

The existing Include/Exclude add-on filter applies only to the two add-on scopes. Add-on files are synchronized before add-on data so a missing add-on can be copied to a Client and receive its data in the same pass. Config, Playlists and Profiles are whole-folder scopes and do not use the add-on filter.

## Safety model

AddonSync intentionally uses a **single-source-of-truth** model:

- **Master:** publishes the selected folders to the central store.
- **Client:** copies matching Master content into its selected local folders.

There is no conflict resolution. A Client can have local content replaced by the Master's copy. Back up Kodi before enabling Config or Profiles synchronization. Client content in selected scopes is replaced by the Master snapshot.

Add-on program files may contain platform-specific/native components. Only enable **Installed add-on files** between compatible Kodi installations (for example the same OS/CPU/Kodi generation). Kodi should be restarted after add-on program files change.

AddonSync never synchronizes its own `service.addonsync` program folder. The historical safety exclusions for metadata, repositories, language resources and skins are also retained.

## Installation in Kodi

### From a release ZIP

1. Build or download `service.addonsync-<version>.zip`.
2. In Kodi open **Add-ons → Install from zip file**.
3. Select the ZIP.
4. Open AddonSync settings and configure the role and central storage path.
5. Under **Synchronization folders**, choose any combination of **Add-on data**, **Installed add-on files**, **Config**, **Playlists** and **Profiles**.
6. Configure the Include/Exclude filter if only selected add-ons should be synchronized.
7. Test with one Master and one Client before enabling it everywhere.

### Upgrade from an older AddonSync

The add-on id and important setting ids were retained so 102.x can be installed over the older build. Before upgrading, back up both your Kodi profile and the shared AddonSync storage.

## Development

The runtime intentionally depends only on modules available inside Kodi and Python's standard library.

Run the repository validation locally:

```bash
python tests/validate_repo.py
```

Build a Kodi-installable ZIP:

```bash
python scripts/build_zip.py
```

The resulting package is written to `dist/` and contains the required top-level `service.addonsync/` directory.

## Repository layout

```text
service.addonsync/
├── .github/workflows/validate.yml
├── docs/
│   └── COMMIT_PLAN.md
├── resources/
│   ├── language/
│   ├── lib/addonsync.py
│   └── settings.xml
├── scripts/build_zip.py
├── tests/validate_repo.py
├── addon.xml
├── default.py
├── filter.py
├── service.py
├── CHANGELOG.md
├── LICENSE
├── NOTICE.md
└── README.md
```

## Fork setup

After copying these files into your GitHub fork, update the `<source>` URL in `addon.xml` from the upstream repository to your own fork URL. Keep the upstream link in [`NOTICE.md`](NOTICE.md) for attribution.

A suggested logical commit sequence is documented in [`docs/COMMIT_PLAN.md`](docs/COMMIT_PLAN.md).

## License

This fork keeps the add-on source under the **Mozilla Public License 2.0 (MPL-2.0)**. See [`LICENSE`](LICENSE) and [`NOTICE.md`](NOTICE.md).

Upstream project: https://github.com/RogueScholar/service.addonsync
