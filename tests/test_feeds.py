import tempfile
import unittest
from pathlib import Path

from app.feeds import get_feeds, mix_feeds


class FeedListTests(unittest.TestCase):
    def test_just_one_file_add_remove_and_rename_without_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feeds.txt"
            self.assertEqual(get_feeds(path), [])

            path.write_text(
                "# first source\nHessenschau | https://www.hessenschau.de/index.rss\n"
                "https://example.org/tech.xml\n"
                "https://www.hessenschau.de/index.rss\n",
                encoding="utf-8",
            )
            self.assertEqual(get_feeds(path), [
                ("Hessenschau", "https://www.hessenschau.de/index.rss"),
                ("", "https://example.org/tech.xml"),
            ])

            path.write_text("My feed | https://example.org/one.xml\n", encoding="utf-8")
            self.assertEqual(get_feeds(path), [
                ("My feed", "https://example.org/one.xml")
            ])

    def test_comments_bad_links_and_empty_lists(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feeds.txt"
            path.write_text(
                "# don't show this\nfile:///etc/passwd\n"
                "javascript:alert(1)\n"
                "https://user:pass@example.org/news\n"
                "valid | https://example.org/feed.xml\n",
                encoding="utf-8",
            )
            self.assertEqual(get_feeds(path), [
                ("valid", "https://example.org/feed.xml")
            ])
            path.write_text("# temporarily no feeds\n", encoding="utf-8")
            self.assertEqual(get_feeds(path), [])

    def test_round_robin_articles(self):
        self.assertEqual(
            mix_feeds([["a1", "a2", "a3"], ["b1"], ["c1", "c2"]]),
            ["a1", "b1", "c1", "a2", "c2", "a3"],
        )
        self.assertEqual(mix_feeds([]), [])


if __name__ == "__main__":
    unittest.main()
