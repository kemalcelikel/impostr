"""Dedicated IMAGE BUILD only. No host installs; no parser execution at build.

Resolve closure against ONLY the locked snapshot and base, verify with APT's
signed Debian metadata, record artifact hashes and complete dpkg provenance.
"""

import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess


def call(args):
    return subprocess.check_output(args, text=True)


def launcher(lock):
    expected = lock["existing_launcher"]
    path = Path(expected["binary"])
    # Existing pinned-image package only; no apt/install fallback for a launcher.
    if (not path.is_file() or path.is_symlink() or
            stat.S_IMODE(path.stat().st_mode) != 0o755 or
            call(["dpkg-query", "-W", "-f=${Version}", expected["package"]]).strip() != expected["version"] or
            call([str(path), "--version"]).strip() != expected["release"]):
        raise SystemExit("existing launcher unavailable or drifted")
    return {"package": expected["package"], "version": expected["version"],
            "release": expected["release"], "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    lock = json.loads(Path("/build/dependencies.lock.json").read_text())
    if call(["dpkg", "--print-architecture"]).strip() != lock["architecture"]:
        raise SystemExit("unsupported architecture")
    existing_launcher = launcher(lock)
    shutil.rmtree("/etc/apt/sources.list.d")
    Path("/etc/apt/sources.list.d").mkdir()
    Path("/etc/apt/sources.list").write_text("\n".join([
        "deb [check-valid-until=no signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] "
        f"https://snapshot.debian.org/archive/{archive}/{lock['snapshot']}/ {suite} main"
        for archive, suite in (("debian", "bookworm"), ("debian-security", "bookworm-security"))]) + "\n")
    # Disabling expiration only is needed for immutable snapshots. Signature and
    # strong package hashes remain mandatory; no trusted=yes/allow-unauthenticated.
    call(["apt-get", "update"])
    packages = [f"{key}={version}" for key, version in lock["packages"].items()]
    options = ["apt-get", "-y", "--no-install-recommends", "-o", "APT::Keep-Downloaded-Packages=true",
               "-o", "Binary::apt-get::APT::Keep-Downloaded-Packages=true"]
    call(options + ["--download-only", "install"] + packages)
    debs = sorted(Path("/var/cache/apt/archives").glob("*.deb"))
    if not debs:
        raise SystemExit("missing dependency artifacts")
    artifacts = [{"file": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        "control": call(["dpkg-deb", "-f", str(p), "Package", "Version", "Source", "Architecture"])}
        for p in debs]
    call(options + ["--no-download", "install"] + packages)
    for key, version in lock["packages"].items():
        if call(["dpkg-query", "-W", "-f=${Version}", key]).strip() != version:
            raise SystemExit("dependency drift")
    if launcher(lock) != existing_launcher:
        raise SystemExit("existing launcher changed during parser installation")
    provenance = {"lock": lock, "debs": artifacts, "launcher": existing_launcher,
        "installed": call(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${source:Package}\t${source:Version}\n"]),
        "indexes": [{"file": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in sorted(Path("/var/lib/apt/lists").glob("*")) if p.is_file()],
        "executables": {name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
            for name in ("/usr/bin/qpdf", "/usr/bin/pdftotext", "/usr/bin/unshare")}}
    Path("/build/build.json").write_text(json.dumps(provenance, sort_keys=True, indent=2) + "\n")
    call(["groupadd", "--gid", "10001", "pdf-api"])
    call(["groupadd", "--gid", "10002", "pdf-extractor"])
    call(["useradd", "--uid", "10002", "--gid", "10002", "--groups", "10001",
          "--no-create-home", "--shell", "/usr/sbin/nologin", "pdf-extractor"])
    channel = Path("/run/impostr-pdf")
    channel.mkdir()
    channel.chmod(0o711)
    shutil.chown(channel, 10002, 10002)
    shutil.rmtree("/var/lib/apt/lists")
    shutil.rmtree("/var/cache/apt/archives")


if __name__ == "__main__":
    main()
