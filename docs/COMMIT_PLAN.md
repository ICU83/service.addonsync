# Suggested commit structure for the fork

Do not squash everything into one opaque "fix addon" commit if you want a reviewable Git history. A clean modernization can be represented by these logical commits.

## Commit 1 — Modernize runtime and entry points

```text
refactor: modernize AddonSync runtime for Python 3
```

Include:

- `service.py`
- `default.py`
- `filter.py`
- `resources/lib/addonsync.py`
- removal of obsolete/broken legacy runtime modules if they still exist in your fork

Purpose: isolate the functional rewrite from metadata/documentation changes.

## Commit 2 — Update Kodi settings and localization

```text
fix: update Kodi settings UI and localization
```

Include:

- `resources/settings.xml`
- `resources/language/**/strings.po`
- `addon.xml` version, provider and `ICU83/service.addonsync` source metadata

Purpose: keep the settings-dialog/localization repair easy to review or revert independently.

## Commit 3 — Add validation and reproducible packaging

```text
build: add repository validation and release zip builder
```

Include:

- `tests/validate_repo.py`
- `scripts/build_zip.py`
- `.github/workflows/validate.yml`
- `.gitignore`
- `.editorconfig`

Purpose: make future releases reproducible and catch malformed XML/PO/Python before pushing a release.

## Commit 4 — Document the maintained fork

```text
docs: document 102.x modernization and licensing
```

Include:

- `README.md`
- `CHANGELOG.md`
- `NOTICE.md`
- `LICENSE`
- `docs/COMMIT_PLAN.md`

Purpose: preserve attribution and clearly distinguish the fork from upstream.

## Applying the structure to an existing GitHub fork

For the existing fork at `https://github.com/ICU83/service.addonsync`, copy the prepared files into your local clone and stage the file groups above separately. Verify the remote first:

```bash
git remote -v
# origin should point to https://github.com/ICU83/service.addonsync.git (or the SSH equivalent)
```

Then create the modernization branch:

```bash
git checkout -b modernize-kodi-21-22

git add service.py default.py filter.py resources/lib/addonsync.py
git commit -m "refactor: modernize AddonSync runtime for Python 3"

git add addon.xml resources/settings.xml resources/language
git commit -m "fix: update Kodi settings UI and localization"

git add .gitignore .editorconfig .github scripts tests
git commit -m "build: add repository validation and release zip builder"

git add README.md CHANGELOG.md NOTICE.md LICENSE docs
git commit -m "docs: document 102.x modernization and licensing"

git push -u origin modernize-kodi-21-22
```

Then merge the branch into your fork's default branch through a pull request or locally after testing.

If your fork contains old runtime files that are no longer used, stage their deletions in Commit 1 as well (`git add -A ...`).
