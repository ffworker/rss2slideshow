"""Regression checks for the production WSGI server and guarded restart."""
import importlib
from pathlib import Path
import unittest
from unittest.mock import patch

import yaml

from app import main
from scripts import safe_update

ROOT = Path(__file__).resolve().parents[1]


class RuntimeTests(unittest.TestCase):
    def test_gunicorn_wsgi_starts_exactly_one_refresh_thread(self):
        with patch("threading.Thread") as thread:
            wsgi = importlib.import_module("app.wsgi")
        self.assertIs(wsgi.app, main.app)
        thread.assert_called_once_with(
            target=main.worker, daemon=True, name="rss-feed-refresh"
        )
        thread.return_value.start.assert_called_once()

    def test_image_uses_one_worker_and_wsgi_app_without_preload(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn('"gunicorn"', dockerfile)
        self.assertIn('"--workers", "1"', dockerfile)
        self.assertIn('"--threads", "4"', dockerfile)
        self.assertIn('"app.wsgi:app"', dockerfile)
        self.assertNotIn('"--preload"', dockerfile)
        self.assertNotIn('CMD ["python", "-m", "app.main"]', dockerfile)

    def test_healthcheck_is_in_container_not_externally_published(self):
        compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
        service = compose["services"]["signage"]
        check = service["healthcheck"]
        self.assertEqual(check["test"][:3], ["CMD", "python", "-c"])
        self.assertIn("127.0.0.1:8080/healthz", check["test"][3])
        self.assertIn("timeout=3", check["test"][3])
        self.assertEqual(service["ports"], ["${BIND_IP:-127.0.0.1}:${HTTP_PORT:-8085}:8080"])

    def test_restart_readiness_retries_transient_refusal(self):
        with patch.object(safe_update, "command", side_effect=[
            safe_update.UpdateError("connection refused"), ""
        ]) as run, patch.object(safe_update.time, "sleep") as sleep:
            safe_update.wait_for_service_ready(timeout=5)
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_restart_readiness_fails_closed_on_timeout(self):
        with patch.object(safe_update, "command", side_effect=safe_update.UpdateError("not ready")), \
             self.assertRaisesRegex(safe_update.UpdateError, "did not answer /healthz"):
            safe_update.wait_for_service_ready(timeout=0)


if __name__ == "__main__":
    unittest.main()
