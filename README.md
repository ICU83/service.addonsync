# AddonSync — modernized fork

AddonSync synchronizes Kodi add-on settings from one designated **Master** installation to one or more **Clients** through a shared storage location.

This repository contains the modernized **102.x** line. It keeps the original Kodi add-on id, `service.addonsync`, while replacing synchronization code that no longer behaved correctly on Python 3/current Kodi installations.

**Maintained fork:** https://github.com/ICU83/service.addonsync

> This is a community-maintained modernization of the original AddonSync project. It is not an official upstream release.

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

See [`CHANGELOG.md`](CHANGELOG.md) for the detailed list.

## Safety model

AddonSync intentionally uses a **single-source-of-truth** model:

- **Master:** publishes add-on settings to the central store.
- **Client:** mirrors matching settings from the Master.

There is no conflict resolution. A Client can have local settings replaced by the Master's copy. Back up Kodi's `userdata/addon_data` directory before first rollout.

## Installation in Kodi

### From a release ZIP

1. Build or download `service.addonsync-<version>.zip`.
2. In Kodi open **Add-ons → Install from zip file**.
3. Select the ZIP.
4. Open AddonSync settings and configure the role and central storage path.
5. Test with one Master and one Client before enabling it everywhere.

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

## Repository

Maintained fork: https://github.com/ICU83/service.addonsync

Issue tracker: https://github.com/ICU83/service.addonsync/issues

Upstream attribution is preserved in [`NOTICE.md`](NOTICE.md). A suggested logical commit sequence for applying the modernization on top of the existing fork history is documented in [`docs/COMMIT_PLAN.md`](docs/COMMIT_PLAN.md).

## License

This fork keeps the add-on source under the **Mozilla Public License 2.0 (MPL-2.0)**. See [`LICENSE`](LICENSE) and [`NOTICE.md`](NOTICE.md).

Upstream project: https://github.com/RogueScholar/service.addonsync
