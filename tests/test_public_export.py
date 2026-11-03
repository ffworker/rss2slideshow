"""Public snapshot must omit private runtime content and original Git history."""
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.export_public import ROOT, export, public_files


class PublicSourceExportTests(unittest.TestCase):
    def test_audit_and_file_allowlist(self):
        names = {path.relative_to(ROOT).as_posix() for path in public_files()}
        for name in (".env.example", "LICENSE", "app/main.py", "tests/test_branding.py",
                     "docs/branding.md", "scripts/export_public.py"):
            self.assertIn(name, names)
        for name in (".env", "config.yaml", "content/feeds.txt",
                     "content/ui-settings.yaml", "branding/brand.yaml",
                     "docs/status.md", "docs/manual-vm-deploy.md"):
            self.assertNotIn(name, names)
        self.assertFalse(any(name.startswith(".git/") for name in names))

    def test_archive_excludes_history_and_local_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "source-only.zip"
            export(destination)
            with zipfile.ZipFile(destination) as saved:
                files = set(saved.namelist())
                self.assertEqual(files, {
                    p.relative_to(ROOT).as_posix() for p in public_files()
                })
                self.assertNotIn(".git/HEAD", files)
                self.assertNotIn("branding/brand.yaml", files)
                self.assertIn("README.md", files)


if __name__ == "__main__":
    unittest.main()
