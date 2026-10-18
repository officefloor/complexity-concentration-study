"""Non-pip replication dependencies (PMD, CK): where to download them, the exact pins they must
match, and where the project keeps them so the CLI can default to those locations.

pip installs the Python side (see pyproject). The two Java tools are not on PyPI, so `setup.sh`
(or `god-complexity deps`) downloads them here into ./lib, each verified against the sha256 the
study pins, and the CLI then defaults --pmd/--ck to these paths -- a replication run needs only
the key flags. Override the location with --lib or $GODC_LIB, or point --pmd/--ck elsewhere.

Everything is plain, inspectable code: the source URLs, the sha256 each artifact must match, and
the extraction. A download that does not match its pinned sha256 is removed and raises, so a
replication never proceeds on the wrong bytes."""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
import urllib.request
import zipfile

from . import study

# The project root (the directory holding this package), so lib/ and results/ resolve the same
# way regardless of the current working directory.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_lib() -> str:
    """Where downloaded (non-pip) dependencies live: $GODC_LIB, else <project>/lib."""
    return os.environ.get("GODC_LIB") or os.path.join(PROJECT_ROOT, "lib")


def default_results() -> str:
    """Base directory for run output: $GODC_RESULTS, else <project>/results."""
    return os.environ.get("GODC_RESULTS") or os.path.join(PROJECT_ROOT, "results")


# --- PMD: the GitHub release zip, pinned by study.PMD_VERSION and by the zip's sha256 ---------
PMD_URL = (f"https://github.com/pmd/pmd/releases/download/pmd_releases%2F{study.PMD_VERSION}"
           f"/pmd-dist-{study.PMD_VERSION}-bin.zip")
PMD_ZIP_SHA256 = "4ae396ffaf2b0d3ef0b73a10b2925e77066f73d57a4ce9078c60e7302bcddec9"

# --- CK: the Maven Central jar-with-dependencies, pinned by study.CK_VERSION and study.CK_SHA256
CK_URL = (f"https://repo1.maven.org/maven2/com/github/mauricioaniche/ck/{study.CK_VERSION}"
          f"/ck-{study.CK_VERSION}-jar-with-dependencies.jar")


def pmd_path(lib: str | None = None) -> str:
    return os.path.join(lib or default_lib(), f"pmd-bin-{study.PMD_VERSION}", "bin", "pmd")


def ck_path(lib: str | None = None) -> str:
    return os.path.join(lib or default_lib(), "ck", f"ck-{study.CK_VERSION}.jar")


def default_pmd(lib: str | None = None) -> str | None:
    """The project's PMD binary if setup has downloaded it, else None (CLI then omits the panel)."""
    p = pmd_path(lib)
    return p if os.path.exists(p) else None


def default_ck(lib: str | None = None) -> str | None:
    """The project's CK jar if setup has downloaded it, else None."""
    p = ck_path(lib)
    return p if os.path.isfile(p) else None


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_verified(url: str, sha256: str, dest: str) -> None:
    """Download `url` to `dest`, failing (and removing the partial file) unless it matches the
    pinned sha256 -- so a replication never silently proceeds on unexpected bytes."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    print(f"  downloading {url}", flush=True)
    urllib.request.urlretrieve(url, tmp)
    got = _sha256(tmp)
    if got != sha256:
        os.remove(tmp)
        raise RuntimeError(f"sha256 mismatch for {url}\n    expected {sha256}\n    got      {got}")
    os.replace(tmp, dest)


def fetch(lib: str | None = None, force: bool = False) -> dict:
    """Download PMD and CK into `lib` (default ./lib), each verified against its pinned sha256 and
    placed where the CLI defaults look. Idempotent: an artifact already present with the right
    bytes is left as-is unless `force`. Returns {'pmd': path, 'ck': path}."""
    lib = lib or default_lib()
    print(f"dependencies -> {lib}", flush=True)

    pmd = pmd_path(lib)
    if force or not os.path.exists(pmd):
        with tempfile.TemporaryDirectory(prefix="godc-pmd-dl-") as td:
            zpath = os.path.join(td, "pmd.zip")
            _download_verified(PMD_URL, PMD_ZIP_SHA256, zpath)
            shutil.rmtree(os.path.join(lib, f"pmd-bin-{study.PMD_VERSION}"), ignore_errors=True)
            os.makedirs(lib, exist_ok=True)
            with zipfile.ZipFile(zpath) as z:
                z.extractall(lib)                      # yields lib/pmd-bin-<ver>/
        bindir = os.path.join(lib, f"pmd-bin-{study.PMD_VERSION}", "bin")
        for f in os.listdir(bindir):                   # zip extraction drops the unix exec bit
            p = os.path.join(bindir, f)
            os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print(f"  PMD {study.PMD_VERSION} -> {pmd}", flush=True)
    else:
        print(f"  PMD {study.PMD_VERSION} already present -> {pmd}", flush=True)

    ck = ck_path(lib)
    if force or not os.path.isfile(ck) or _sha256(ck) != study.CK_SHA256:
        _download_verified(CK_URL, study.CK_SHA256, ck)
        print(f"  CK {study.CK_VERSION} -> {ck}", flush=True)
    else:
        print(f"  CK {study.CK_VERSION} already present -> {ck}", flush=True)
    return {"pmd": pmd, "ck": ck}
