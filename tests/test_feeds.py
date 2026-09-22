import tempfile
import unittest
from pathlib import Path

from app.feeds import get_feeds, mix_feeds


class FeedListTests(unittest.TestCase):
    def test_add_more_feeds_without_restarting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feeds.txt"
            primary = "https://www.hessenschau.de/index.rss"
            self.assertEqual(get_feeds(primary, "Hessenschau", path),
                             [("Hessenschau", primary)])

            path.write_text("# extra sources\nOther news | https://example.org/rss.xml\n"
                            "https://example.org/tech.xml\n"
                            + primary + "\n", encoding="utf-8")
            self.assertEqual(get_feeds(primary, "Hessenschau", path), [
                ("Hessenschau", primary),
                ("Other news", "https://example.org/rss.xml"),
                ("", "https://example.org/tech.xml")
            ])

            path.write_text("https://example.org/one.xml\n", encoding="utf-8")
            self.assertEqual(get_feeds(primary, "Hessenschau", path), [
                ("Hessenschau", primary),
                ("", "https://example.org/one.xml")
            ])

    def test_invalid_lines_are_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feeds.txt"
            path.write_text("just a note\nfile:///etc/passwd\n"
                            "valid | https://example.org/feed.xml\n", encoding="utf-8")
            self.assertEqual(get_feeds(None, None, path),
                             [("valid", "https://example.org/feed.xml")])

    def test_queue_alternates_between_feeds(self):
        self.assertEqual(mix_feeds([["a1", "a2", "a3"], ["b1"], ["c1", "c2"]]),
                         ["a1", "b1", "c1", "a2", "c2", "a3"])
        self.assertEqual(mix_feeds([]), [])


if __name__ == "__main__":
    unittest.main()
