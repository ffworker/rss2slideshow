#!/usr/bin/env python3
"""Conservative, manual in-place updater for RSS2Slideshow.

Only changes tracked application code. Host-local state is backed up and
fingerprinted before pulling, then checked after Git and Docker operations.
Never restores files automatically or silently overwrites concurrent edits.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
STATE_PATHS = (".env", "config.yaml", "content", "branding", "assets")
# Only source-controlled placeholders / sample data may live under state dirs.
ALLOWED_TRACKED = frozenset({
    "content/feeds.example.txt",
    "content/company/.gitkeep",
    "content/photos/.gitkeep",
    "assets/.gitkeep",
})
DISPLAY_FIELDS = (
    "brand_name", "tagline", "layout", "font_family",
    "accent_color", "background_color", "text_color",
    "header_color", "footer_color", "logo_mode",
    "logo_url", "group_logo_url", "footer_banner_url",
    "show_group_logo", "source_in_header", "footer_names",
    "design_enabled", "headline_color", "summary_color",
    "overlay_headline_color", "overlay_summary_color",
    "header_height", "footer_height", "logo_size", "image_width",
    "headline_size", "summary_size", "image_fit", "story_layout",
    "show_clock", "show_source", "show_footer_names",
)
# Execute inside the service, so no secret or published host port is needed.
HEALTH_SCRIPT = (
    "import json, urllib.request; "
    "response=urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3); "
    "data=json.load(response); "
    "assert data.get('status') == 'ok'"
)
API_SCRIPT = (
    "import json, urllib.request; "
    "response=urllib.request.urlopen('http://127.0.0.1:8080/api/articles', timeout=8); "
    "data=json.load(response); "
    "print(json.dumps(data, ensure_ascii=True, sort_keys=True))"
)


class UpdateError(RuntimeError):
    pass


def command(*args: str, cwd: Path = ROOT) -> str:
    try:
        proc = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise UpdateError("Missing command: " + args[0]) from exc
    if proc.returncode:
        reason = (proc.stderr or proc.stdout or "").strip()[-900:]
        raise UpdateError("Command failed: " + " ".join(args[:3]) + "\n" + reason)
    return proc.stdout.strip()


def is_protected_path(name: str) -> bool:
    return name in (".env", "config.yaml") or name.startswith(
        ("content/", "branding/", "assets/")
    )


def unexpected_tracked(paths: list[str]) -> list[str]:
    return sorted(
        p for p in paths
        if is_protected_path(p) and p not in ALLOWED_TRACKED
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(root: Path) -> dict[str, str]:
    """Content-based signatures of *all* local files, including future data."""
    found: dict[str, str] = {}
    for name in STATE_PATHS:
        target = root / name
        if target.is_symlink():
            raise UpdateError("Persistent state root must not be a symlink: " + name)
        if target.is_file():
            found[name] = sha256_file(target)
        elif target.is_dir():
            for child in sorted(target.rglob("*")):
                relative = child.relative_to(root).as_posix()
                if relative in ALLOWED_TRACKED:
                    continue  # versioned samples/placeholders may legitimately change in a release
                if child.is_symlink():
                    raise UpdateError("Local state contains a symlink; archive would not include its target: " + relative)
                if child.is_file():
                    found[relative] = sha256_file(child)
    return found


def backup(root: Path, destination: Path) -> Path:
    root = root.resolve()
    destination = destination.expanduser().resolve()
    if destination == root or root in destination.parents:
        raise UpdateError("Backup directory must be outside the Git checkout")
    destination.mkdir(parents=True, mode=0o700, exist_ok=True)
    if stat.S_IMODE(destination.stat().st_mode) & 0o077:
        raise UpdateError("Backup directory is accessible by others; use chmod 700")
    filename = "rss2slideshow-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f") + ".tar.gz"
    path = destination / filename
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            with tarfile.open(fileobj=stream, mode="w:gz") as archive:
                for name in STATE_PATHS:
                    source = root / name
                    if source.exists():
                        archive.add(source, arcname=name, recursive=True)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def changed_keys(before: dict[str, object], after: dict[str, object]) -> list[str]:
    return sorted(
        key for key in (set(before) | set(after)) if before.get(key) != after.get(key)
    )


def wait_for_service_ready(timeout: float = 45) -> None:
    """Wait until the restarted web process serves HTTP, not just Docker 'running'."""
    deadline = time.monotonic() + timeout
    last_error = None
    while True:
        try:
            command("docker", "compose", "exec", "-T", "signage", "python", "-c", HEALTH_SCRIPT)
            return
        except UpdateError as exc:
            last_error = exc
        if time.monotonic() >= deadline:
            raise UpdateError(
                "Restarted service did not answer /healthz within "
                + str(timeout) + " seconds"
            ) from last_error
        time.sleep(1)


def display_snapshot() -> dict[str, object]:
    data = json.loads(command("docker", "compose", "exec", "-T", "signage", "python", "-c", API_SCRIPT))
    if not isinstance(data, dict) or "brand_name" not in data:
        raise UpdateError("Live /api/articles returned no branding data")
    return {key: data.get(key) for key in DISPLAY_FIELDS}


def preflight() -> None:
    if Path(command("git", "rev-parse", "--show-toplevel")).resolve() != ROOT:
        raise UpdateError("Run updater from its own Git checkout")
    if command("git", "branch", "--show-current") != "main":
        raise UpdateError("Updater requires checked-out main branch")
    if command("git", "status", "--porcelain", "--untracked-files=no"):
        raise UpdateError("Tracked Git files have local changes. Review them before updating")
    if not (ROOT / "config.yaml").is_file():
        raise UpdateError("config.yaml is missing or not a regular file")
    for directory in ("content", "branding", "assets"):
        if not (ROOT / directory).is_dir():
            raise UpdateError(directory + "/ is missing; do not update before checking the mount")
    command("docker", "compose", "config", "--quiet")


def review_target() -> None:
    command("git", "fetch", "origin", "main")
    tracked = command("git", "ls-tree", "-r", "--name-only", "FETCH_HEAD").splitlines()
    offenders = unexpected_tracked(tracked)
    if offenders:
        raise UpdateError(
            "Incoming commit tracks local state; update blocked: " + ", ".join(offenders)
        )


def verify_files(before: dict[str, str], when: str) -> None:
    current = fingerprint(ROOT)
    differences = changed_keys(before, current)
    if differences:
        raise UpdateError(
            "Persistent data changed " + when + ": " + ", ".join(differences[:20])
            + ". Do not restore automatically: another editor may be active."
        )


def update(directory: Path, no_ui_check: bool = False) -> None:
    preflight()
    prior_display = None if no_ui_check else display_snapshot()
    review_target()
    previous_commit = command("git", "rev-parse", "HEAD")
    signatures = fingerprint(ROOT)
    archive = backup(ROOT, directory)
    print("Backup (private, includes credentials):", archive, flush=True)
    print("Previous commit:", previous_commit, flush=True)
    command("git", "merge", "--ff-only", "FETCH_HEAD")
    verify_files(signatures, "during git update")
    command("docker", "compose", "up", "-d", "--build", "signage")
    wait_for_service_ready()
    verify_files(signatures, "during container rebuild")
    if prior_display is not None:
        current_display = display_snapshot()
        difference = changed_keys(prior_display, current_display)
        if difference:
            raise UpdateError(
                "Live design values changed: " + ", ".join(difference)
                + ". Original files are backed up. Inspect before accepting the update."
            )
    print("Update passed persistence checks:", command("git", "rev-parse", "HEAD"))
    print("Please verify the real kiosk display; HTML/CSS rendering is not pixel-tested.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "update"))
    parser.add_argument(
        "--backup-dir", type=Path,
        default=Path.home() / "rss2slideshow-backups",
        help="Private backup location outside the repository",
    )
    parser.add_argument(
        "--no-ui-check", action="store_true",
        help="Allow maintenance while display service is stopped; skips live visual-setting verification",
    )
    args = parser.parse_args()
    try:
        if args.action == "check":
            preflight()
            current = fingerprint(ROOT)
            print("Local state files:", len(current))
            if not args.no_ui_check:
                display_snapshot()
                print("Active display settings: readable")
            print("Preflight passed. No files changed.")
        else:
            update(args.backup_dir, no_ui_check=args.no_ui_check)
    except (UpdateError, OSError, ValueError, json.JSONDecodeError) as exc:
        print("SAFE UPDATE STOPPED:", exc, file=sys.stderr)
        print("Do not use git reset --hard or delete volumes. Check the backup and running screen.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
