#!/usr/bin/env python3
"""Static validation for the AddonSync repository."""

from __future__ import annotations

import ast
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME_PY = [
    ROOT / "service.py",
    ROOT / "default.py",
    ROOT / "filter.py",
    ROOT / "resources" / "lib" / "addonsync.py",
]
XML_FILES = [ROOT / "addon.xml", ROOT / "resources" / "settings.xml"]
PO_FILES = sorted((ROOT / "resources" / "language").glob("*/strings.po"))


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def validate_python() -> None:
    for path in RUNTIME_PY:
        if not path.is_file():
            fail(f"missing runtime file: {path.relative_to(ROOT)}")
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            fail(f"Python syntax error in {path.relative_to(ROOT)}: {exc}")
    print(f"PASS: Python syntax ({len(RUNTIME_PY)} files)")


def validate_xml() -> None:
    for path in XML_FILES:
        if not path.is_file():
            fail(f"missing XML file: {path.relative_to(ROOT)}")
        try:
            ET.parse(path)
        except ET.ParseError as exc:
            fail(f"XML parse error in {path.relative_to(ROOT)}: {exc}")
    print(f"PASS: XML parse ({len(XML_FILES)} files)")


def validate_addon_manifest() -> None:
    root = ET.parse(ROOT / "addon.xml").getroot()
    if root.attrib.get("id") != "service.addonsync":
        fail("addon.xml id must remain service.addonsync")
    version = root.attrib.get("version", "")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        fail(f"unexpected add-on version format: {version!r}")
    print(f"PASS: addon.xml metadata (version {version})")


def parse_po_contexts(path: pathlib.Path) -> set[str]:
    contexts: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith('msgctxt "#') and line.endswith('"'):
            contexts.add(line[len('msgctxt "') : -1])
    return contexts


def validate_localization() -> None:
    if not PO_FILES:
        fail("no language catalogs found")

    settings_text = (ROOT / "resources" / "settings.xml").read_text(encoding="utf-8")
    referenced = set(re.findall(r'\b(?:label|help)="(3\d{4})"', settings_text))

    baseline = None
    for path in PO_FILES:
        text = path.read_text(encoding="utf-8")
        if 'msgid ""' not in text or 'Content-Type: text/plain; charset=UTF-8' not in text:
            fail(f"invalid PO header: {path.relative_to(ROOT)}")
        contexts = parse_po_contexts(path)
        missing = sorted(f"#{item}" for item in referenced if f"#{item}" not in contexts)
        if missing:
            fail(f"{path.relative_to(ROOT)} is missing settings labels: {', '.join(missing)}")
        if baseline is None:
            baseline = contexts
    print(f"PASS: localization ({len(PO_FILES)} catalogs, {len(referenced)} settings labels)")


def main() -> None:
    validate_python()
    validate_xml()
    validate_addon_manifest()
    validate_localization()
    print("PASS: repository validation complete")


if __name__ == "__main__":
    main()
