#!/usr/bin/env python3
"""Generate validated Kodi repository metadata for a packaged release."""

from __future__ import print_function

import argparse
import copy
import hashlib
import os
import sys
import xml.etree.ElementTree as ET


ADDON_ID = "plugin.kodi.jiotv"
DEFAULT_REPOSITORY_ID = "repository.jiotvdirect"


def _read_addon(path, expected_id, expected_version=None):
    if not os.path.isfile(path):
        raise ValueError("Missing manifest: {0}".format(path))
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError("Invalid XML in {0}: {1}".format(path, exc))
    if root.tag != "addon":
        raise ValueError("{0} is not an addon manifest".format(path))
    if root.get("id") != expected_id:
        raise ValueError("{0} has id {1}, expected {2}".format(path, root.get("id"), expected_id))
    if expected_version is not None and root.get("version") != expected_version:
        raise ValueError(
            "{0} has version {1}, expected {2}".format(
                path, root.get("version"), expected_version
            )
        )
    return root


def generate_addons_xml(repository_id, output_dir, version=None):
    output_dir = output_dir or "repo"
    main_path = os.path.join("temp", ADDON_ID, "addon.xml")
    repository_path = os.path.join("temp_repo", repository_id, "addon.xml")
    main_root = _read_addon(main_path, ADDON_ID, version)
    repository_root = _read_addon(repository_path, repository_id, version)

    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

    combined = ET.Element("addons")
    combined.append(copy.deepcopy(main_root))
    combined.append(copy.deepcopy(repository_root))
    xml_text = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    xml_text += ET.tostring(combined, encoding="unicode")
    if not xml_text.endswith("\n"):
        xml_text += "\n"
    ET.fromstring(xml_text)

    addons_path = os.path.join(output_dir, "addons.xml")
    md5_path = os.path.join(output_dir, "addons.xml.md5")
    with open(addons_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(xml_text)
    digest = hashlib.md5(xml_text.encode("utf-8")).hexdigest()
    with open(md5_path, "w", encoding="ascii", newline="") as handle:
        handle.write(digest)

    print("[PASS] XML manifests parsed")
    print("[PASS] Addon/repository IDs and versions validated")
    print("[PASS] addons.xml generated: {0}".format(addons_path))
    print("[PASS] MD5 generated: {0}".format(md5_path))
    return addons_path, md5_path, digest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository_id", nargs="?", default=DEFAULT_REPOSITORY_ID)
    parser.add_argument("--repository-id", dest="repository_id_option")
    parser.add_argument("--output-dir", default="repo")
    parser.add_argument("--version")
    args = parser.parse_args(argv)
    repository_id = args.repository_id_option or args.repository_id
    try:
        generate_addons_xml(repository_id, args.output_dir, args.version)
    except (OSError, ValueError, ET.ParseError) as exc:
        print("[FAIL] {0}".format(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
