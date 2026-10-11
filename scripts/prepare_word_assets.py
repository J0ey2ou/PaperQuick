"""Reproducibly prepare official CSL assets for the offline Word integration.

Run explicitly when rebuilding vendor assets; the application never downloads them.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "word-integration"
STYLES_COMMIT = "f2c83bb7374107239366dd168b616c4e75ffa36a"
LOCALES_COMMIT = "a89adece41013402236e2c9020972d7e931fbab8"
CITEPROC_VERSION = "2.4.63"
SELECTED = [
    "china-national-standard-gb-t-7714-2015-numeric",
    "china-national-standard-gb-t-7714-2015-author-date",
    "apa", "vancouver-nlm", "ieee", "chicago-author-date",
    "chicago-author-date-17th-edition", "modern-language-association",
    "harvard-cite-them-right", "nature", "science", "cell", "the-lancet",
    "the-new-england-journal-of-medicine", "american-medical-association",
    "american-medical-association-10th-edition", "american-chemical-society",
    "american-physics-society", "association-for-computing-machinery",
    "elsevier-harvard", "elsevier-vancouver", "springer-basic-author-date",
    "springer-basic-brackets", "springer-vancouver", "plos", "bmj",
    "biomed-central", "frontiers", "multidisciplinary-digital-publishing-institute",
    "iso690-author-date-en", "iso690-numeric-en",
]
NS = {"c": "http://purl.org/net/xbiblio/csl"}


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "PaperQuick-assets/1"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def archive(name: str, commit: str) -> zipfile.ZipFile:
    target = ROOT / "build" / "word-assets-cache" / (name + ".zip")
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(fetch(f"https://codeload.github.com/citation-style-language/{name}/zip/{commit}"))
    data = target.read_bytes()
    result = zipfile.ZipFile(io.BytesIO(data))
    if not result.namelist()[0].startswith(f"{name}-{commit}/"):
        raise ValueError(f"Cached {name} archive is not the pinned revision")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", type=Path, help="Official portable node.exe to bundle; defaults to PATH")
    args = parser.parse_args()
    for directory in ("styles", "locales", "vendor"):
        (ASSETS / directory).mkdir(parents=True, exist_ok=True)
    vendor = ASSETS / "vendor"
    package = json.loads(fetch(f"https://registry.npmjs.org/citeproc/{CITEPROC_VERSION}"))
    tarball = fetch(package["dist"]["tarball"])
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(tarball).digest()).decode()
    if integrity != package["dist"]["integrity"]:
        raise ValueError("citeproc package integrity check failed")
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as source:
        for src, dst in [("package/citeproc_commonjs.js", "citeproc.js"),
                         ("package/LICENSE", "CITEPROC-LICENSE")]:
            member = source.extractfile(src)
            if member is None:
                raise ValueError(f"Package missing {src}")
            (vendor / dst).write_bytes(member.read())

    styles = archive("styles", STYLES_COMMIT)
    members = {Path(name).stem: name for name in styles.namelist() if name.endswith(".csl")}
    copied = set()
    def copy_style(style_id):
        if style_id in copied:
            return
        data = styles.read(members[style_id])
        (ASSETS / "styles" / (style_id + ".csl")).write_bytes(data)
        copied.add(style_id)
        root = ET.fromstring(data)
        for link in root.findall("c:info/c:link", NS):
            if link.get("rel") == "independent-parent":
                copy_style(link.get("href").rstrip("/").split("/")[-1])
    for style_id in SELECTED:
        copy_style(style_id)
    locales = archive("locales", LOCALES_COMMIT)
    locale_count = 0
    for name in locales.namelist():
        if Path(name).name.startswith("locales-") and name.endswith(".xml"):
            (ASSETS / "locales" / Path(name).name).write_bytes(locales.read(name))
            locale_count += 1
    for zipped, target in [(styles, "CSL-STYLES-LICENSE"), (locales, "CSL-LOCALES-LICENSE")]:
        readme_name = next(n for n in zipped.namelist() if n.endswith("/README.md"))
        readme = zipped.read(readme_name).decode("utf-8")
        (vendor / target).write_text(readme[readme.rindex("Licensing\n"):], encoding="utf-8")
    (vendor / "CC-BY-SA-3.0-LEGALCODE.txt").write_bytes(fetch("https://creativecommons.org/licenses/by-sa/3.0/legalcode.txt"))
    (vendor / "CPAL-1.0.txt").write_bytes(fetch("https://raw.githubusercontent.com/Juris-M/citeproc-js/master/CPAL"))
    (vendor / "AGPL-3.0.txt").write_bytes(fetch("https://raw.githubusercontent.com/Juris-M/citeproc-js/master/AGPLv3"))
    node = args.node or Path(shutil.which("node") or "")
    if not node.is_file():
        raise SystemExit("Supply an official Windows Node executable with --node")
    version = subprocess.check_output([str(node), "--version"], text=True).strip()
    if not version.startswith("v") or not all(c.isdigit() or c == "." for c in version[1:]):
        raise ValueError("Unexpected Node version")
    if node.resolve() != (vendor / "node.exe").resolve():
        shutil.copy2(node, vendor / "node.exe")
    (vendor / "NODE-LICENSE").write_bytes(fetch(f"https://raw.githubusercontent.com/nodejs/node/{version}/LICENSE"))
    manifest = {"citeproc_version": CITEPROC_VERSION, "citeproc_integrity": integrity,
                "styles_commit": STYLES_COMMIT, "locales_commit": LOCALES_COMMIT,
                "styles": SELECTED, "dependencies": sorted(copied - set(SELECTED)),
                "locale_count": locale_count, "node_version": version,
                "node_sha256": hashlib.sha256(node.read_bytes()).hexdigest()}
    (vendor / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (vendor / "ATTRIBUTION.txt").write_text(
        "PaperQuick offline citation resources\n\n"
        f"citeproc-js {CITEPROC_VERSION}, Frank Bennett and contributors; CPAL-1.0 or AGPL-3.0.\n"
        "https://github.com/Juris-M/citeproc-js — see CITEPROC-LICENSE.\n\n"
        "Citation Style Language styles and locales, individual authors and CSL project;\n"
        "Creative Commons Attribution-ShareAlike 3.0 Unported.\n"
        "https://github.com/citation-style-language/styles\n"
        "https://github.com/citation-style-language/locales\n"
        "Original author, rights and source metadata remain in each unmodified XML file.\n"
        "See CSL-STYLES-LICENSE and CSL-LOCALES-LICENSE.\n\n"
        f"Node.js {version}, Node.js contributors; MIT and bundled third-party licenses.\n"
        "https://nodejs.org — see NODE-LICENSE.\n\n"
        "Pinned upstream revisions and checksums are recorded in manifest.json.\n",
        encoding="utf-8")
    print(f"Prepared {len(SELECTED)} styles + {len(copied) - len(SELECTED)} parents, {locale_count} locales, Node {version}.")


if __name__ == "__main__":
    main()
