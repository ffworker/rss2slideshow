"""End-to-end playback test: Chromium + real Flask HTTP, no production data.

Run after copying config.example.yaml to config.yaml:
    pip install playwright==1.56.0
    python -m playwright install chromium
    PYTHONPATH=. python tests/browser_playback.py
"""
import base64
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

from app import main


def run():
    articles = [
        {"id": f"test-{i}", "title": f"Test article {i}", "summary": "Synthetic RSS",
         "source": "Test feed", "feed_index": 0, "feed_id": "test"}
        for i in range(1, 6)
    ]
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp) / "playlist-state.json"
        settings = Path(tmp) / "admin-settings.yaml"
        feed = Path(tmp) / "feeds.txt"
        feed.write_text("")
        with patch.object(main, "PLAYLIST_STATE_FILE", state), \
             patch.object(main, "ADMIN_SETTINGS_FILE", settings), \
             patch.object(main, "FEED_FILE", feed), \
             patch.dict(main.snapshot, {"articles": articles, "sources": ["Test"]}), \
             patch.dict(os.environ, {"ADMIN_USER": "test-admin", "ADMIN_PASSWORD": "test-password",
                                     "ADMIN_KIOSK_PATH": "/kiosk", "SLIDE_SECONDS": "5"}):
            server = make_server("127.0.0.1", 0, main.app, threaded=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                exercise(base, state)
            finally:
                server.shutdown()
                thread.join(timeout=5)
    print("PASS: browser playback integration")


def exercise(base, state):
    with main.app.test_client() as client:
        headers = {"Authorization": "Basic " + base64.b64encode(b"test-admin:test-password").decode()}
        def configure(seconds, resume):
            fields = {"csrf": main.admin_form_token(), "action": "save_settings",
                      "slide_seconds": str(seconds), "max_articles": "5",
                      "refresh_minutes": "10"}
            if resume:
                fields["resume_playback"] = "on"
            result = client.post("/admin", headers=headers, data=fields)
            assert result.status_code == 200
            api = client.get("/api/articles").get_json()
            assert api["slide_seconds"] == seconds and api["resume_playback"] is resume

        def cursor():
            return json.loads(state.read_text()).get("resume:all") if state.exists() else None

        configure(5, False)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.clock.install()
            def slide(i):
                expect(page.locator("#headline")).to_have_text(f"Test article {i}", timeout=10000)
                expect(page.locator("#counter")).to_have_text(f"{i:02d} / 05")
            def advance(ms):
                page.clock.run_for(ms)

            page.goto(base + "/kiosk")
            slide(1)
            advance(5100)
            slide(2)
            assert cursor() is None, "Standalone changed resume state"
            print("PASS: old URL and mode unchanged")

            configure(5, True)
            page.reload()
            slide(1)
            for i in range(2, 6):
                advance(5100)
                slide(i)
                assert cursor() == f"test-{i-1}"
            advance(1000)
            page.reload()
            slide(5)
            assert cursor() == "test-4", "Incomplete article was acknowledged"
            advance(5100)
            slide(1)
            assert cursor() == "test-5"
            print("PASS: all five slides, interruption by actual reload, wraparound")

            # Change interval through real admin POST while playback is active.
            configure(10, True)
            advance(5100)
            slide(2)
            advance(6000)
            slide(2)
            assert cursor() == "test-1"
            configure(20, True)
            advance(4100)
            slide(3)
            advance(11000)
            slide(3)
            assert cursor() == "test-2"
            configure(5, True)
            advance(9100)
            slide(4)
            assert cursor() == "test-3"
            print("PASS: live 5 -> 10 -> 20 -> 5 second update at article boundaries")

            # Model a webview that is kept alive but reports visibility changes.
            page.evaluate("""() => {
              Object.defineProperty(document, 'hidden', {configurable: true, value: true});
              document.dispatchEvent(new Event('visibilitychange'));
            }""")
            advance(25000)
            assert cursor() == "test-3", "Hidden player advanced"
            page.evaluate("""() => {
              Object.defineProperty(document, 'hidden', {configurable: true, value: false});
              document.dispatchEvent(new Event('visibilitychange'));
            }""")
            slide(4)
            assert cursor() == "test-3"
            advance(5100)
            slide(5)
            print("PASS: hidden/reused webview simulation")

            # Independent preview in another browser context cannot consume progress.
            page.close()
            before = cursor()
            preview_ctx = browser.new_context(http_credentials={"username": "test-admin",
                                                                 "password": "test-password"})
            preview = preview_ctx.new_page()
            preview.clock.install()
            preview.goto(base + "/admin")
            frame = preview.frame_locator("#design-preview")
            expect(frame.locator("#headline")).to_have_text("Test article 1", timeout=10000)
            preview.clock.run_for(5100)
            expect(frame.locator("#headline")).to_have_text("Test article 2", timeout=10000)
            assert cursor() == before
            preview_ctx.close()
            print("PASS: real admin iframe does not advance production cursor")

            configure(5, False)
            page = ctx.new_page()
            page.clock.install()
            page.goto(base + "/kiosk")
            slide(1)
            advance(5100)
            slide(2)
            assert cursor() == before
            assert not errors, errors
            browser.close()
            print("PASS: return to legacy playback without deleting cursor")


if __name__ == "__main__":
    run()
