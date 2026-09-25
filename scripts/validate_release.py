#!/usr/bin/env python3
"""Validate a JioTV Direct release before publication."""

from __future__ import print_function

import argparse
import hashlib
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET


ADDON_ID = "plugin.kodi.jiotv"
FORBIDDEN_PATHS = (
    ".git/", ".github/", ".agents/", "__pycache__/", ".pytest_cache/",
    "kodi.log", "test_scripts/", "scratch/", "scripts/",
)
FORBIDDEN_DISTRIBUTION_HOST = "dineshintry.github.io"
FORK_DISTRIBUTION_PREFIX = "https://deepankar-siddharth.github.io/plugin.kodi.jiotv/"
FORBIDDEN_FILENAMES = (
    ".env", "id_rsa", "id_ed25519", "credentials.json", "secrets.json",
)
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(rb"github_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
)


class ValidationError(Exception):
    pass


def ok(label):
    print("[PASS] {0}".format(label))


def fail(label, detail):
    raise ValidationError("{0}: {1}".format(label, detail))


def parse_xml(path, label):
    try:
        return ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        fail(label, str(exc))


def validate_version(version):
    if not re.match(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$", version or ""):
        fail("Version format", version or "<empty>")


def validate_manifest(path, expected_id, expected_version, label, require_fork_urls=False):
    root = parse_xml(path, label)
    if root.tag != "addon":
        fail(label, "root element is not addon")
    if root.get("id") != expected_id:
        fail(label, "id={0}, expected={1}".format(root.get("id"), expected_id))
    if root.get("version") != expected_version:
        fail(label, "version={0}, expected={1}".format(root.get("version"), expected_version))
    text = open(path, "r", encoding="utf-8").read()
    if FORBIDDEN_DISTRIBUTION_HOST in text:
        fail(label, "contains forbidden upstream distribution URL")
    if require_fork_urls and FORK_DISTRIBUTION_PREFIX not in text:
        fail(label, "does not contain the fork distribution URL")
    ok(label)
    return root


def validate_zip(path, expected_root, expected_manifest, expected_version, label):
    if not os.path.isfile(path):
        fail(label, "archive does not exist: {0}".format(path))
    try:
        archive = zipfile.ZipFile(path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        fail(label, str(exc))
    with archive:
        names = archive.namelist()
        top_level = {name.split("/", 1)[0] for name in names if name and not name.endswith("/")}
        if top_level != {expected_root}:
            fail(label, "unexpected top-level entries: {0}".format(sorted(top_level)))
        if not any(name == expected_manifest for name in names):
            fail(label, "missing {0}".format(expected_manifest))
        for name in names:
            if any(token in name for token in FORBIDDEN_PATHS):
                fail(label, "forbidden path: {0}".format(name))
            if name.rsplit("/", 1)[-1].casefold() in FORBIDDEN_FILENAMES:
                fail(label, "forbidden credential filename: {0}".format(name))
            if name.endswith((".pyc", ".pyo")):
                fail(label, "compiled Python file: {0}".format(name))
            if name.casefold().endswith((".pem", ".key", ".p12", ".pfx")):
                fail(label, "credential/key file: {0}".format(name))
            lowered = name.lower()
            if lowered.endswith((".txt", ".xml", ".py", ".json", ".yaml", ".yml", ".md", ".po", ".html", ".m3u")):
                try:
                    body = archive.read(name)
                except KeyError:
                    continue
                if FORBIDDEN_DISTRIBUTION_HOST.encode("utf-8") in body:
                    fail(label, "upstream distribution URL in {0}".format(name))
                for pattern in SECRET_PATTERNS:
                    if pattern.search(body):
                        fail(label, "credential-like material in {0}".format(name))
        manifest_path = expected_manifest
        manifest_data = archive.read(manifest_path)
        try:
            root = ET.fromstring(manifest_data)
        except ET.ParseError as exc:
            fail(label, "invalid manifest XML: {0}".format(exc))
        if root.get("id") != ADDON_ID and root.get("id") != expected_root:
            fail(label, "unexpected manifest id {0}".format(root.get("id")))
        if root.get("version") != expected_version:
            fail(label, "manifest version mismatch")
        if not any(name.startswith(expected_root + "/") for name in names):
            fail(label, "missing top-level addon directory")
    ok(label)


def validate_generated(output_dir, version, repository_id):
    addons_path = os.path.join(output_dir, "addons.xml")
    md5_path = os.path.join(output_dir, "addons.xml.md5")
    root = parse_xml(addons_path, "Generated addons.xml")
    if root.tag != "addons":
        fail("Generated addons.xml", "root element is not addons")
    ids = {node.get("id"): node for node in root.findall("addon")}
    if ADDON_ID not in ids:
        fail("Generated addons.xml", "main addon is missing")
    if repository_id not in ids:
        fail("Generated addons.xml", "repository addon is missing")
    if ids[ADDON_ID].get("version") != version:
        fail("Generated addons.xml", "main version mismatch")
    if ids[repository_id].get("version") != version:
        fail("Generated addons.xml", "repository version mismatch")
    body = open(addons_path, "rb").read()
    if FORBIDDEN_DISTRIBUTION_HOST.encode("utf-8") in body:
        fail("Generated addons.xml", "contains upstream distribution URL")
    if FORK_DISTRIBUTION_PREFIX.encode("utf-8") not in body:
        fail("Generated addons.xml", "does not contain the fork distribution URL")
    expected = hashlib.md5(body).hexdigest()
    actual = open(md5_path, "r", encoding="ascii").read().strip()
    if actual != expected:
        fail("addons.xml.md5", "expected {0}, got {1}".format(expected, actual))
    ok("Generated addons.xml")
    ok("addons.xml.md5")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--version")
    parser.add_argument("--repository-id", default="repository.jiotvdirect")
    parser.add_argument("--source-repository-id", default="repository.jiotvdirect")
    parser.add_argument("--source-only", action="store_true")
    parser.add_argument("--output-dir", default="repo")
    parser.add_argument("--addon-zip")
    parser.add_argument("--repository-zip")
    parser.add_argument("--source-root", default=".")
    args = parser.parse_args(argv)

    if args.version:
        version = args.version
    elif args.tag.startswith("v"):
        version = args.tag[1:]
    else:
        version = None
    if not version:
        fail("Tag", "version could not be derived")
    if args.tag.startswith("v") and args.tag[1:] != version:
        fail("Tag/version", "tag {0} does not match version {1}".format(args.tag, version))
    print("Release validation")
    validate_version(version)
    ok("Semantic version {0}".format(version))

    source_root = args.source_root
    validate_manifest(
        os.path.join(source_root, "addon.xml"), ADDON_ID, version,
        "Source addon.xml", require_fork_urls=True,
    )
    validate_manifest(
        os.path.join(source_root, "repository.jiotvdirect", "addon.xml"),
        args.source_repository_id, version, "Source repository addon.xml", require_fork_urls=True,
    )

    if args.source_only:
        print("Source validation successful.")
        return 0

    if args.addon_zip:
        validate_zip(
            args.addon_zip, ADDON_ID, ADDON_ID + "/addon.xml", version,
            "Addon ZIP",
        )
    if args.repository_zip:
        validate_zip(
            args.repository_zip, args.repository_id,
            args.repository_id + "/addon.xml", version,
            "Repository ZIP",
        )
    validate_generated(args.output_dir, version, args.repository_id)
    print("Release validation successful.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValidationError as exc:
        print("[FAIL] {0}".format(exc), file=sys.stderr)
        sys.exit(1)
