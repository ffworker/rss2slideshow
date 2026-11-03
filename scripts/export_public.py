#!/usr/bin/env python3
"""Create a source-only archive for a new Git repository, without old history."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import stat
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    ".env.example", ".gitignore", "Dockerfile", "LICENSE", "README.md",
    "compose.yaml", "config.example.yaml", "requirements.txt",
    "content/feeds.example.txt", "content/company/.gitkeep",
    "content/photos/.gitkeep", "assets/.gitkeep",
}
DOC_FILES = {
    "docs/README.md", "docs/deployment.md",
    "docs/branding.md", "docs/update-safety.md",
}
SOURCE_DIRS = ("app", "addons", "scripts", "tests", ".github/workflows")
ALLOWED_EXTENSIONS = {".py", ".html", ".md", ".txt", ".yaml", ".yml"}
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", ".venv", ".git"}
# Generic patterns only; do not embed the private employer's identifiers in source.
SENSITIVE_PATTERNS = (
    re.compile(r"\b(?:10\.(?:\d{1,3}\.){2}\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"),
    re.compile(r"\b[\w.-]+\.local\b", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    re.compile(r"\b(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}\b"),
)


def public_files(root: Path = ROOT) -> list[Path]:
    missing = sorted(
        rel for rel in ROOT_FILES | DOC_FILES
        if not (root / rel).is_file()
    )
    if missing:
        raise ValueError("Missing public project files: " + ", ".join(missing))
    extras = sorted(
        p.relative_to(root).as_posix()
        for p in (root / "docs").rglob("*")
        if p.is_file() and p.relative_to(root).as_posix() not in DOC_FILES
    )
    if extras:
        raise ValueError("Unexpected docs would be excluded from public export: " + ", ".join(extras))
    files = {root / rel for rel in ROOT_FILES | DOC_FILES}
    for directory in SOURCE_DIRS:
        for candidate in (root / directory).rglob("*"):
            if candidate.is_symlink():
                raise ValueError("Source symlink requires explicit review: " + str(candidate))
            if not candidate.is_file():
                continue
            if EXCLUDED_PARTS.intersection(candidate.relative_to(root).parts):
                continue
            if candidate.suffix in ALLOWED_EXTENSIONS:
                files.add(candidate)
    result = sorted(files, key=lambda p: p.relative_to(root).as_posix())
    for item in result:
        rel = item.relative_to(root).as_posix()
        if item.is_symlink():
            raise ValueError("Export symlink blocked: " + rel)
        if item.stat().st_size > 1_000_000:
            raise ValueError("Unexpected large file: " + rel)
        text = item.read_text(encoding="utf-8")
        if any(pattern.search(text) for pattern in SENSITIVE_PATTERNS):
            raise ValueError("Potential private data in: " + rel)
    return result


def export(destination: Path, root: Path = ROOT) -> None:
    selected = public_files(root)
    destination = destination.expanduser().resolve()
    root = root.resolve()
    if destination == root or root in destination.parents:
        raise ValueError("Export ZIP must be outside the source checkout")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in selected:
            rel = item.relative_to(root).as_posix()
            info = zipfile.ZipInfo(rel, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, item.read_bytes())
    print("Created clean source ZIP:", destination)
    print("This archive has no .git directory or old commit history.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Audit only")
    parser.add_argument("--output", type=Path, help="ZIP destination outside checkout")
    args = parser.parse_args()
    try:
        checked = public_files()
        if args.check:
            print("Public export audit passed:", len(checked), "source files")
        else:
            export(args.output or ROOT.parent / "rss2slideshow-clean-source.zip")
        return 0
    except (ValueError, OSError, UnicodeError) as error:
        print("Public export blocked:", error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
