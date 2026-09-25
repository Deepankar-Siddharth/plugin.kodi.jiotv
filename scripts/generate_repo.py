#!/usr/bin/env python3
"""Generate validated Kodi addon/repository archives and metadata."""

from __future__ import print_function

import argparse
import copy
import hashlib
import os
import re
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET


ADDON_ID = "plugin.kodi.jiotv"
DEFAULT_REPOSITORY_ID = "repository.jiotvdirect"
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
EXCLUDED_DIRS = frozenset((
    ".git",
    ".github",
    ".agents",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    "__pycache__",
    "build",
    "dist",
    "repo",
    "scratch",
    "scripts",
    "temp",
    "temp_repo",
    "test_scripts",
    "website",
))
EXCLUDED_FILES = frozenset((
    ".DS_Store",
    ".git",
    ".github",
    ".gitignore",
    "Thumbs.db",
    "kodi.log",
))
EXCLUDED_SUFFIXES = (
    ".7z",
    ".bz2",
    ".gz",
    ".log",
    ".pyc",
    ".pyo",
    ".s7z",
    ".swp",
    ".swo",
    ".tar",
    ".tmp",
    ".xz",
    ".zip",
    "~",
)


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
        raise ValueError(
            "{0} has id {1}, expected {2}".format(path, root.get("id"), expected_id)
        )
    if expected_version is not None and root.get("version") != expected_version:
        raise ValueError(
            "{0} has version {1}, expected {2}".format(
                path, root.get("version"), expected_version
            )
        )
    return root


def _load_inputs(repository_id, requested_version=None):
    if (
        not re.match(r"^[A-Za-z0-9._-]+$", repository_id or "")
        or repository_id in (".", "..")
    ):
        raise ValueError("Invalid repository ID: {0}".format(repository_id))
    main_path = os.path.join("temp", ADDON_ID, "addon.xml")
    repository_path = os.path.join("temp_repo", repository_id, "addon.xml")
    main_root = _read_addon(main_path, ADDON_ID)
    repository_root = _read_addon(repository_path, repository_id)

    version = main_root.get("version")
    repository_version = repository_root.get("version")
    if not version:
        raise ValueError("Addon manifest has no version")
    if not VERSION_PATTERN.match(version):
        raise ValueError("Invalid addon version: {0}".format(version))
    if repository_version != version:
        raise ValueError(
            "Addon/repository version mismatch: {0} != {1}".format(
                version, repository_version
            )
        )
    if requested_version is not None and requested_version != version:
        raise ValueError(
            "Requested version {0} does not match addon metadata {1}".format(
                requested_version, version
            )
        )
    return main_root, repository_root, version


def _clean_output_dir(output_dir):
    output_dir = output_dir or "repo"
    output_abs = os.path.abspath(output_dir)
    cwd = os.path.abspath(os.getcwd())
    if output_abs == cwd or os.path.commonpath([output_abs, cwd]) == output_abs:
        raise ValueError(
            "Refusing to clean the source/current directory: {0}".format(output_dir)
        )

    for protected_name in ("addon", "temp", "temp_repo", "scripts", ".git", ".github"):
        protected = os.path.abspath(protected_name)
        if os.path.commonpath([output_abs, protected]) == protected:
            raise ValueError(
                "Refusing to clean source directory: {0}".format(output_dir)
            )

    if os.path.lexists(output_abs):
        if os.path.isdir(output_abs) and not os.path.islink(output_abs):
            shutil.rmtree(output_abs)
        else:
            os.remove(output_abs)
    os.makedirs(output_abs)
    return output_dir


def _is_excluded(path, source_root):
    relative = os.path.relpath(path, source_root)
    parts = relative.split(os.sep)
    if any(part in EXCLUDED_DIRS for part in parts[:-1]):
        return True
    filename = parts[-1]
    if filename in EXCLUDED_FILES:
        return True
    lowered = filename.casefold()
    return any(lowered.endswith(suffix) for suffix in EXCLUDED_SUFFIXES)


def _write_zip(source_root, archive_path):
    if not os.path.isdir(source_root):
        raise ValueError("Missing package source directory: {0}".format(source_root))
    archive_dir = os.path.dirname(archive_path)
    if archive_dir:
        os.makedirs(archive_dir, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for root, directories, files in os.walk(source_root):
            directories[:] = sorted(
                directory for directory in directories
                if directory not in EXCLUDED_DIRS
                and not os.path.islink(os.path.join(root, directory))
            )
            for filename in sorted(files):
                path = os.path.join(root, filename)
                if os.path.islink(path):
                    continue
                if _is_excluded(path, source_root):
                    continue
                arcname = os.path.relpath(path, os.path.dirname(source_root))
                archive.write(path, arcname.replace(os.sep, "/"))


def _copy_if_present(source, destination):
    if not os.path.isfile(source):
        return
    destination_dir = os.path.dirname(destination)
    if destination_dir:
        os.makedirs(destination_dir, exist_ok=True)
    shutil.copy2(source, destination)


def _copy_release_assets(output_dir, repository_id):
    addon_source = os.path.join("temp", ADDON_ID)
    repository_source = os.path.join("temp_repo", repository_id)
    for filename in ("icon.png", "fanart.png"):
        addon_asset = os.path.join(addon_source, "resources", filename)
        _copy_if_present(
            addon_asset,
            os.path.join(output_dir, ADDON_ID, "resources", filename),
        )
        _copy_if_present(
            addon_asset,
            os.path.join(output_dir, ADDON_ID, filename),
        )
        _copy_if_present(
            os.path.join(repository_source, filename),
            os.path.join(output_dir, repository_id, "resources", filename),
        )
        _copy_if_present(
            os.path.join(repository_source, filename),
            os.path.join(output_dir, repository_id, filename),
        )


def _write_addons_xml(main_root, repository_root, output_dir):
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


def generate_addons_xml(repository_id, output_dir, version=None):
    """Generate metadata only for callers that already built package trees."""
    main_root, repository_root, _ = _load_inputs(repository_id, version)
    output_dir = output_dir or "repo"
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    return _write_addons_xml(main_root, repository_root, output_dir)


def generate_release(repository_id, output_dir, version=None):
    """Clean output, build both ZIPs, then generate final repository metadata."""
    output_dir = _clean_output_dir(output_dir)
    main_root, repository_root, resolved_version = _load_inputs(repository_id, version)
    addon_source = os.path.join("temp", ADDON_ID)
    repository_source = os.path.join("temp_repo", repository_id)
    addon_zip = os.path.join(
        output_dir, ADDON_ID, "{0}-{1}.zip".format(ADDON_ID, resolved_version)
    )
    repository_zip = os.path.join(
        output_dir, repository_id, "{0}-{1}.zip".format(repository_id, resolved_version)
    )

    _write_zip(addon_source, addon_zip)
    _write_zip(repository_source, repository_zip)
    _copy_release_assets(output_dir, repository_id)
    print(
        "[PASS] Release version resolved from addon metadata: {0}".format(
            resolved_version
        )
    )
    print("[PASS] Addon ZIP generated: {0}".format(addon_zip))
    print("[PASS] Repository ZIP generated: {0}".format(repository_zip))

    addons_path, md5_path, digest = _write_addons_xml(
        main_root, repository_root, output_dir
    )
    return {
        "version": resolved_version,
        "repository_id": repository_id,
        "addon_zip": addon_zip,
        "repository_zip": repository_zip,
        "addons_xml": addons_path,
        "addons_xml_md5": md5_path,
        "md5": digest,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository_id", nargs="?", default=DEFAULT_REPOSITORY_ID)
    parser.add_argument("--repository-id", dest="repository_id_option")
    parser.add_argument("--output-dir", default="repo")
    parser.add_argument("--version")
    args = parser.parse_args(argv)
    repository_id = args.repository_id_option or args.repository_id
    try:
        generate_release(repository_id, args.output_dir, args.version)
    except (OSError, ValueError, ET.ParseError, shutil.Error, zipfile.BadZipFile) as exc:
        print("[FAIL] {0}".format(exc), file=sys.stderr)
        return 1
    print("Release generation successful.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
