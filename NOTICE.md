# Attribution and licensing notice

This repository is a modernized derivative of **AddonSync** (`service.addonsync`).

Upstream project:

- Repository: https://github.com/RogueScholar/service.addonsync
- Original add-on id: `service.addonsync`
- Original maintainers/contributors include Rob Webset, Robert Hudson and Peter J. Mello.

The upstream repository states that its contents are governed by the Mozilla Public License 2.0 unless a file says otherwise. This fork keeps the Kodi add-on source under **MPL-2.0** and preserves upstream attribution where applicable.

The complete MPL-2.0 license text is in [`LICENSE`](LICENSE).

## Modernization

The 102.x line is a compatibility-focused modernization for Python 3 / current Kodi releases. It replaces broken synchronization, hashing, entry-point and localization behavior while retaining the original add-on id and the Master/Client synchronization model.

If upstream artwork or other files with their own `.license` metadata are reintroduced later, keep those per-file license notices with the corresponding assets.
