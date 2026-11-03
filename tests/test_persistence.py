"""Regression tests for customer-owned state across code updates."""
from pathlib import Path
import stat
import subprocess
import tarfile
import tempfile
import unittest

import yaml

from scripts.safe_update import (
    backup, changed_keys, fingerprint, is_protected_path,
    unexpected_tracked, UpdateError,
)

ROOT = Path(__file__).resolve().parents[1]


class PersistenceTests(unittest.TestCase):
    def test_state_snapshot_and_private_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkout"
            root.mkdir()
            (root / ".env").write_text("ADMIN_PASSWORD=local-secret\n")
            (root / "config.yaml").write_text("max_articles: 5\n")
            (root / "content").mkdir()
            (root / "content" / "feeds.txt").write_text("Example | https://example.org/rss\n")
            (root / "content" / "ui-settings.yaml").write_text("brand_name: My screen\n")
            (root / "content" / "new-setting-for-future-version.json").write_text("{}")
            (root / "content" / "feeds.example.txt").write_text("old example")
            (root / "branding").mkdir()
            (root / "branding" / "brand.yaml").write_text("layout: featured\n")
            (root / "branding" / "logo.png").write_bytes(b"local-logo")
            (root / "assets").mkdir()
            (root / "assets" / "custom.jpg").write_bytes(b"local-image")
            initial = fingerprint(root)
            self.assertEqual(len(initial), 8)
            (root / "application.py").write_text("updated code")
            (root / "content" / "feeds.example.txt").write_text("new example")
            self.assertEqual(fingerprint(root), initial)
            destination = Path(tmp) / "private-backups"
            archive = backup(root, destination)
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o600)
            with tarfile.open(archive, "r:gz") as saved:
                names = set(saved.getnames())
                self.assertIn(".env", names)
                self.assertIn("branding/brand.yaml", names)
                self.assertIn("branding/logo.png", names)
                self.assertIn("content/ui-settings.yaml", names)
                self.assertIn("content/new-setting-for-future-version.json", names)
            (root / "branding" / "logo.png").unlink()
            self.assertEqual(changed_keys(initial, fingerprint(root)), ["branding/logo.png"])

    def test_symlinked_user_data_requires_explicit_backup_handling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkout"
            (root / "content").mkdir(parents=True)
            target = Path(tmp) / "external-state"
            target.write_text("external")
            (root / "content" / "image-link.png").symlink_to(target)
            with self.assertRaises(UpdateError):
                fingerprint(root)

    def test_refuses_backups_inside_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(UpdateError):
                backup(root, root / "backups")

    def test_future_git_commits_must_not_track_runtime_data(self):
        for path in (
            ".env", "config.yaml", "branding/brand.yaml",
            "branding/logo.svg", "content/ui-settings.yaml",
            "content/another-future-setting.json", "assets/private-logo.png",
        ):
            self.assertTrue(is_protected_path(path))
            self.assertNotIn(path, ["content/feeds.example.txt"])
            self.assertEqual(
                subprocess.run(
                    ["git", "check-ignore", "--quiet", path],
                    cwd=ROOT, check=False
                ).returncode, 0,
                msg=path + " must be Git-ignored",
            )
        self.assertEqual(unexpected_tracked([
            "app/main.py", "content/feeds.example.txt", "assets/.gitkeep",
            "branding/brand.yaml", "content/new-user-setting.yaml",
        ]), ["branding/brand.yaml", "content/new-user-setting.yaml"])

    def test_docker_uses_host_mounts_not_image_for_customization(self):
        compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
        volumes = compose["services"]["signage"]["volumes"]
        self.assertIn("./content:/app/content", volumes)
        self.assertIn("./branding:/app/branding:ro", volumes)
        self.assertIn("./assets:/app/assets:ro", volumes)
        self.assertTrue(any(
            isinstance(entry, dict)
            and entry.get("source") == "./config.yaml"
            and entry.get("read_only") is True
            for entry in volumes
        ))


if __name__ == "__main__":
    unittest.main()
