#!/usr/bin/env python3
"""Build a Kodi-installable AddonSync ZIP from the repository."""

from __future__ import annotations

import pathlib
import xml.etree.ElementTree as ET
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
ADDON_ID = "service.addonsync"
DIST = ROOT / "dist"

# Files useful for GitHub/development but not needed inside Kodi's add-on folder.
EXCLUDED_TOP_LEVEL = {
    ".git",
    ".github",
    ".gitignore",
    ".editorconfig",
    "docs",
    "scripts",
    "tests",
    "dist",
    "build",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def addon_version() -> str:
    root = ET.parse(ROOT / "addon.xml").getroot()
    if root.attrib.get("id") != ADDON_ID:
        raise RuntimeError(f"Expected addon id {ADDON_ID!r}")
    return root.attrib["version"]


def should_include(path: pathlib.Path) -> bool:
    rel = path.relative_to(ROOT)
    if rel.parts and rel.parts[0] in EXCLUDED_TOP_LEVEL:
        return False
    if path.suffix in EXCLUDED_SUFFIXES:
        return False
    if "__pycache__" in rel.parts:
        return False
    return path.is_file()


def main() -> None:
    version = addon_version()
    DIST.mkdir(exist_ok=True)
    output = DIST / f"{ADDON_ID}-{version}.zip"
    if output.exists():
        output.unlink()

    files = sorted(path for path in ROOT.rglob("*") if should_include(path))
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in files:
            arcname = pathlib.PurePosixPath(ADDON_ID) / pathlib.PurePosixPath(path.relative_to(ROOT).as_posix())
            zf.write(path, arcname.as_posix())

    print(output)


if __name__ == "__main__":
    main()
