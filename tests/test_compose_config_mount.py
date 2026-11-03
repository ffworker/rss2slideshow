"""Safety regression: RSS config.yaml must be an existing regular host file."""
from pathlib import Path
import unittest
import yaml


class ComposeConfigMountTests(unittest.TestCase):
    def test_config_yaml_bind_refuses_missing_source(self):
        compose_file = Path(__file__).resolve().parents[1] / "compose.yaml"
        compose = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
        mounts = compose["services"]["signage"]["volumes"]
        matches = [
            mount for mount in mounts
            if isinstance(mount, dict) and mount.get("target") == "/app/config.yaml"
        ]
        self.assertEqual(len(matches), 1, "config.yaml must have one explicit bind mount")
        config_mount = matches[0]
        self.assertEqual(config_mount["type"], "bind")
        self.assertEqual(config_mount["source"], "./config.yaml")
        self.assertIs(config_mount["read_only"], True)
        self.assertIs(
            config_mount["bind"]["create_host_path"], False,
            "Docker Compose must not turn a missing config.yaml into a directory",
        )


if __name__ == "__main__":
    unittest.main()
