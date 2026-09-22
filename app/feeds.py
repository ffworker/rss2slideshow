"""Read the kiosk's one RSS feed list."""
import logging
from pathlib import Path
from urllib.parse import urlsplit


def get_feeds(feed_file):
    """Each non-comment line: URL or Name | URL. Read again on every check."""
    feeds = []
    seen = set()
    path = Path(feed_file)
    if not path.is_file():
        return feeds
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        logging.exception("could not read feeds.txt")
        return feeds

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            label, url = line.split("|", 1)
            label, url = label.strip(), url.strip()
        else:
            label, url = "", line
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("invalid feed URL")
        except ValueError:
            logging.warning("skipping invalid feed URL in feeds.txt: %s", url)
            continue
        if url not in seen:
            seen.add(url)
            feeds.append((label, url))
    return feeds


def mix_feeds(groups):
    """One article from each feed at a time instead of a block per source."""
    mixed = []
    for i in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if i < len(group):
                mixed.append(group[i])
    return mixed
