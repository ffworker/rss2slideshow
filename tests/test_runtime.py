"""Regression checks for the production WSGI server and guarded restart."""
import importlib
import re
import shutil
import subprocess
import json
import tempfile
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


    def test_anthias_playlist_advances_only_with_a_new_request_and_persists(self):
        items = [
            {"id": "a", "feed_index": 0, "feed_id": "hessenschau", "title": "One"},
            {"id": "b", "feed_index": 0, "feed_id": "hessenschau", "title": "Two"},
            {"id": "c", "feed_index": 1, "feed_id": "regional", "title": "Other"},
        ]
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            main, "PLAYLIST_STATE_FILE", Path(tmp) / "playlist-state.json"
        ), patch.dict(main.snapshot, {"articles": items}):
            with main.app.test_client() as client:
                first = client.get("/api/playlist-next?feed=0")
                second = client.get("/api/playlist-next?feed=0")
                independent = client.get("/api/playlist-next?feed=1")
                third = client.get("/api/playlist-next?feed=0")
                bad = client.get("/api/playlist-next?feed=../etc")
                unavailable = client.get("/api/playlist-next?feed=99")
                persisted = json.loads(main.PLAYLIST_STATE_FILE.read_text())
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.headers.get("Cache-Control"), "no-store")
        self.assertEqual([res.get_json()["article"]["id"] for res in (first, second, third)],
                         ["a", "b", "a"])
        self.assertEqual(independent.get_json()["article"]["id"], "c")
        self.assertEqual(persisted["feed:hessenschau"], "a")
        self.assertEqual(persisted["feed:regional"], "c")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(unavailable.status_code, 404)

    def test_browser_scripts_are_parseable_javascript(self):
        if not shutil.which("node"):
            self.skipTest("Node.js is not available")
        for filename in ("app/player.html", "app/templates/admin.html"):
            with self.subTest(filename=filename):
                page = (ROOT / filename).read_text(encoding="utf-8")
                inline = re.search(r"<script>(.*?)</script>", page, re.DOTALL)
                self.assertIsNotNone(inline)
                result = subprocess.run(
                    ["node", "--check", "--input-type=commonjs"],
                    input=inline.group(1), capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_bistro_player_has_website_one_article_mode(self):
        player = (ROOT / "app/player.html").read_text(encoding="utf-8")
        self.assertIn('playlistParams.get("playlist") === "1"', player)
        self.assertIn('"/api/playlist-next"', player)
        self.assertIn('visibilitychange', player)
        self.assertIn('var(--ui-content-top', player)
        self.assertIn('var(--ui-clock-size', player)


if __name__ == "__main__":
    unittest.main()
