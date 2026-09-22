import unittest
from unittest.mock import Mock, patch

import feedparser

from app import main


def xml(title, name):
    return ("""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>""" + name + """</title>
<item><title>""" + title + """</title><description><![CDATA[
<b>Short story</b> and more.]]></description>
<link>https://example.org/article</link>
<enclosure url="https://example.org/photo.jpg" type="image/jpeg" length="0"/>
<pubDate>Tue, 22 Sep 2026 09:00:00 GMT</pubDate>
</item></channel></rss>""").encode()


class ReaderTests(unittest.TestCase):
    def test_rss_turns_into_normal_article_data(self):
        feed = feedparser.parse(xml("Some news", "Local paper"))
        with patch.dict(main.CFG, {"news_images": True}):
            source, stories = main.parse_articles(feed, "", "https://example.org/rss")
        self.assertEqual(source, "Local paper")
        self.assertEqual(stories[0]["title"], "Some news")
        self.assertEqual(stories[0]["summary"], "Short story and more.")
        self.assertEqual(stories[0]["image"], "https://example.org/photo.jpg")
        self.assertIn("2026-09-22", stories[0]["published"])

    def test_named_feeds_get_mixed_instead_of_one_big_block(self):
        def fake_get(url, **kwargs):
            answer = Mock()
            answer.content = xml("A", "first") if "one" in url else xml("B", "second")
            answer.raise_for_status.return_value = None
            return answer

        sources = [("First", "https://example.org/one"), ("Second", "https://example.org/two")]
        with patch.object(main, "get_feeds", return_value=sources), patch.object(main.requests, "get", side_effect=fake_get):
            main.refresh()
        with main.app.test_client() as client:
            result = client.get("/api/articles")
            self.assertEqual(result.status_code, 200)
            stories = result.get_json()["articles"]
            self.assertEqual([story["source"] for story in stories], ["First", "Second"])
            self.assertEqual(client.get("/kiosk").status_code, 200)
            self.assertEqual(client.get("/inventory.txt").status_code, 404)

    def test_only_safe_article_links(self):
        self.assertEqual(main.http_url("javascript:alert(1)"), "")
        self.assertEqual(main.http_url("https://example.org/news"), "https://example.org/news")


if __name__ == "__main__":
    unittest.main()
