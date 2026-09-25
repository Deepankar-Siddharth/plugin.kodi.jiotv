#!/usr/bin/env python3
"""Build the static JioTV Direct Pages site into a release directory."""

from __future__ import print_function

import argparse
import html
import os
import re
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path


VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
REPOSITORY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
PLACEHOLDER_PATTERN = re.compile(r"\{\{[A-Z0-9_]+\}\}")


class LinkParser(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self.links = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in ("href", "src") and value:
                self.links.append(value)


def _fail(message):
    raise ValueError(message)


def _copy_assets(source_dir, output_dir):
    if not os.path.isdir(source_dir):
        _fail("Missing website asset directory: {0}".format(source_dir))
    if os.path.lexists(output_dir):
        if os.path.isdir(output_dir) and not os.path.islink(output_dir):
            shutil.rmtree(output_dir)
        else:
            os.remove(output_dir)
    shutil.copytree(
        source_dir,
        output_dir,
        ignore=shutil.ignore_patterns(".DS_Store", "__pycache__", "*.pyc", "*.pyo"),
    )


def _local_target(output_dir, value):
    path = value.split("#", 1)[0].split("?", 1)[0]
    if not path or path == "./":
        return output_dir
    if path.startswith("./"):
        path = path[2:]
    return output_dir / path


def _validate_site(output_dir, version, channel, repository_id):
    required = [
        output_dir / "index.html",
        output_dir / "style.css",
        output_dir / ".nojekyll",
        output_dir / "assets" / "logo.svg",
        output_dir / "addons.xml",
        output_dir / "addons.xml.md5",
        output_dir / "plugin.kodi.jiotv" / "plugin.kodi.jiotv-{0}.zip".format(version),
        output_dir / repository_id / "{0}-{1}.zip".format(repository_id, version),
    ]
    for path in required:
        if not path.is_file():
            _fail("Website validation failed; missing {0}".format(path))

    index_path = output_dir / "index.html"
    text = index_path.read_text(encoding="utf-8")
    if PLACEHOLDER_PATTERN.search(text):
        _fail("Website contains an unsubstituted placeholder")
    expected_links = {
        "./plugin.kodi.jiotv/plugin.kodi.jiotv-{0}.zip".format(version),
        "./{0}/{0}-{1}.zip".format(repository_id, version),
        "./addons.xml",
        "./addons.xml.md5",
    }
    for link in expected_links:
        if link not in text:
            _fail("Website is missing expected relative link: {0}".format(link))

    parser = LinkParser()
    parser.feed(text)
    cross_channel_links = {"./beta/", "../"}
    for value in parser.links:
        if value.startswith(("#", "mailto:", "http://", "https://", "//")):
            continue
        if value.startswith("/"):
            _fail("Website contains a root-relative URL: {0}".format(value))
        if value in cross_channel_links:
            continue
        target = _local_target(output_dir, value)
        if not target.exists():
            _fail("Website link does not resolve to a generated file: {0}".format(value))
    print("[PASS] Website files and relative links validated")
    print("[PASS] Website channel: {0}".format(channel))


def build_site(source_dir, output_dir, version, channel, repository_id, release_date, pages_base_url):
    if not VERSION_PATTERN.match(version or ""):
        _fail("Invalid release version: {0}".format(version))
    if channel not in ("stable", "beta"):
        _fail("Invalid channel: {0}".format(channel))
    if not REPOSITORY_ID_PATTERN.match(repository_id or "") or repository_id in (".", ".."):
        _fail("Invalid repository ID: {0}".format(repository_id))
    if not pages_base_url.startswith("https://"):
        _fail("Pages base URL must use HTTPS")

    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    index_source = source_dir / "index.html"
    style_source = source_dir / "style.css"
    if not index_source.is_file() or not style_source.is_file():
        _fail("Website source must contain index.html and style.css")

    output_dir.mkdir(parents=True, exist_ok=True)
    for path in (output_dir / "index.html", output_dir / "style.css", output_dir / ".nojekyll"):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()
    _copy_assets(source_dir / "assets", output_dir / "assets")

    stable_url = pages_base_url.rstrip("/") + "/"
    beta_url = stable_url + "beta/"
    cross_channel_url = "./beta/" if channel == "stable" else "../"
    values = {
        "VERSION": html.escape(version, quote=True),
        "CHANNEL_LABEL": "Beta channel" if channel == "beta" else "Stable channel",
        "RELEASE_DATE": html.escape(release_date or "Available on GitHub Releases", quote=True),
        "ADDON_ZIP": "./plugin.kodi.jiotv/plugin.kodi.jiotv-{0}.zip".format(version),
        "REPOSITORY_ZIP": "./{0}/{0}-{1}.zip".format(repository_id, version),
        "REPOSITORY_ID": html.escape(repository_id, quote=True),
        "STABLE_URL": html.escape(stable_url, quote=True),
        "BETA_URL": html.escape(beta_url, quote=True),
        "CROSS_CHANNEL_URL": cross_channel_url,
    }
    index_text = index_source.read_text(encoding="utf-8")
    for key, value in values.items():
        index_text = index_text.replace("{{" + key + "}}", value)
    with (output_dir / "index.html").open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(index_text)
    shutil.copy2(style_source, output_dir / "style.css")
    (output_dir / ".nojekyll").write_text("", encoding="ascii")

    _validate_site(output_dir, version, channel, repository_id)
    print("[PASS] Website generated: {0}".format(output_dir / "index.html"))
    print("[PASS] Website stylesheet generated: {0}".format(output_dir / "style.css"))
    print("[PASS] Website assets generated: {0}".format(output_dir / "assets"))
    return output_dir / "index.html"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", default="website")
    parser.add_argument("--output-dir", default="repo")
    parser.add_argument("--version", required=True)
    parser.add_argument("--channel", choices=("stable", "beta"), required=True)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--release-date", default="")
    parser.add_argument("--pages-base-url", default="https://deepankar-siddharth.github.io/plugin.kodi.jiotv/")
    args = parser.parse_args(argv)
    try:
        build_site(
            args.source_dir,
            args.output_dir,
            args.version,
            args.channel,
            args.repository_id,
            args.release_date,
            args.pages_base_url,
        )
    except (OSError, ValueError) as exc:
        print("[FAIL] {0}".format(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
