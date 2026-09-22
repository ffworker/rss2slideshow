"""Tiny helpers for adding extra RSS sources without changing Python or restarting Docker."""
import logging
from pathlib import Path
from urllib.parse import urlsplit


def get_feeds(primary_url, primary_label, feed_file):
    """rss_url from config is still the first feed. Each new line adds another."""
    feeds = []
    seen = set()

    def add(url, label=""):
        url = str(url or "").strip()
        if not url:
            return
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            logging.warning("skipping invalid feed URL: %s", url)
            return
        if url in seen:
            return
        seen.add(url)
        feeds.append((label.strip(), url))

    add(primary_url, primary_label or "RSS")
    path = Path(feed_file)
    if path.is_file():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "|" in line:
                    label, url = line.split("|", 1)
                    add(url, label)
                else:
                    add(line)
        except OSError:
            logging.exception("could not read feeds.txt; keeping primary feed")
    return feeds


def mix_feeds(groups):
    """Take one slide from each feed at a time (no feed hogging the screen)."""
    mixed = []
    for i in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if i < len(group):
                mixed.append(group[i])
    return mixed
