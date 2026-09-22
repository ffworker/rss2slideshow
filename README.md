# rss2slideshow

ok so this thing changed a bit lol. started as a way to feed jpg slides to an existing raspberry slideshow at work, but that got way too roundabout. the actual thing i want now: **a standalone RSS news kiosk in a browser**. one docker service, open the URL on the display, it shows articles from the feeds i chose. nobody needs to click anything. despite the repo name it is NOT converting feeds into jpgs anymore.

this is still my working-notes README, not some polished install guide. i'll clean stuff up after actually using it on the real screen for a while. things might change.

## what it does rn

- `/` or `/kiosk`: full-screen news reader. headline, summary, image if there is one, source name and publication time. next article shows automatically.
- feeds are mixed: one article from feed A, one from B etc. so a single source doesn't hog the display. max articles **per feed** is in `config.yaml`.
- keeps a small live clock. timezone and how long an article stays up are set in `.env`.
- if a feed is temporarily broken it tries to keep its last working articles; if there are no articles at all the page waits and tries again.
- no special player or OS needed. any browser that can run the page. i still need to test the intended kiosk device properly.
- the old `inventory.txt`, JPG slides, separate clock page and Binary Emotions stuff are gone. not part of this project anymore.

## setup-ish (fresh install)

on your docker host:

```bash
git clone https://github.com/ffworker/rss2slideshow.git
cd rss2slideshow
cp .env.example .env
cp config.example.yaml config.yaml
cp content/feeds.example.txt content/feeds.txt
```

edit `.env` first: `BIND_IP` must be an address the display can actually reach. the example uses `127.0.0.1` on purpose, so it'll only work on the docker host until you change it. don't expose your internal display stuff to the whole internet just because it runs in a browser.

then add your RSS URLs in `content/feeds.txt` (see below), change brand/colors in `config.yaml` if you want, and start it:

```bash
docker compose up -d --build
docker compose logs -f signage
```

open `http://YOUR_DOCKER_HOST:8085/` in a browser. the same thing is at `/kiosk`. put Chromium in fullscreen/kiosk mode on the actual display if that's what you're using. no mouse, menus or interaction needed once it's running.

use `http://YOUR_DOCKER_HOST:8085/healthz` to see whether the backend is alive and has articles. `/api/articles` is the JSON that the website actually reads (handy when debugging).

## all the feeds live HERE, nowhere else

`content/feeds.txt` is the **one list**. no default feed hidden somewhere in `config.yaml`. one RSS URL per line, optionally put your own name in front:

```text
Hessenschau | https://www.hessenschau.de/index.rss
My tech news | https://example.org/rss.xml
https://example.org/some-other-feed.xml
```

(the example.org URLs are just placeholders, not real feed recommendations.)

`Name | URL` = that name on the screen. just `URL` = use the name from the RSS feed itself, or its hostname if it doesn't provide one. blank lines and lines starting with `#` get ignored. duplicate URLs get skipped. remove a line to remove a source; add `#` in front if you only want to pause it.

**existing installation / important once:** if you're upgrading from the earlier version which had `rss_url` and `news_source_label` in `config.yaml`, copy that old main feed into `content/feeds.txt` BEFORE updating/restarting. keep the extra feeds already in there, just add the old main feed as another line. e.g. `Hessenschau | https://www.hessenschau.de/index.rss` if that was yours. don't overwrite your real `feeds.txt` with the example file! from this version on the old `rss_url` and `news_source_label` settings are **ignored**, so removing them from your local `config.yaml` is fine once you've moved the URL.

after that: edit `content/feeds.txt` whenever you like. no docker restart/build needed just to add, remove or rename feeds. the server checks for a changed list about every 30 sec, fetches it and the browser checks for updates about every 30 sec. normal news refresh uses `refresh_minutes` (default 10). slow/broken feeds can delay that a little.

## few questions i already had

**why two files, .env and config.yaml?** neither contains any feed URLs. `.env` is for the docker port binding + clock timezone + article timing; `config.yaml` is the app look and refresh/article limits. the actual sources are ONLY `content/feeds.txt`.

**can i change the display time / timezone?** yup, `SLIDE_SECONDS=20` and `DISPLAY_TZ=Europe/Berlin` in `.env` (use an IANA timezone, e.g. `UTC`). since those settings are passed to the container when it starts, run `docker compose up -d` after editing them. feed list edits don't need this. timezone affects the clock / published times.

**can i brand it?** `brand_name` and `accent_color` in `config.yaml`, optional `assets/logo.png` for the little logo. no html/python changes needed. the logo file and actual configs stay local / untracked. restart/recreate the service after config changes. the repo has a default news-ish look on purpose, not trying to invent a giant UI here.

**where are the pictures?** set `news_images: true` in `config.yaml` *after* checking you're allowed to show those feeds' pictures on your display. the image has to exist in the RSS content and the image host has to allow the browser to load it; some feeds have no image or block hotlinking, so text-only articles are normal. this is not a full-article scraper.

**what if a feed fails?** check `docker compose logs --tail=50 signage`. other working sources should keep showing, and it keeps the last successfully fetched articles for a temporarily failing feed. no feed configured / no articles? the screen waits, it doesn't need someone to click Retry.

**how do i change the displayed sources?** edit the text file; no feed picker on the kiosk screen. it's supposed to run unattended. an interactive browse/admin mode can be a separate thing later if there's an actual need for it.

**do i need Binary Emotions / inventory.txt / media.conf?** no, none of that. the display points at this website, that's it.

## random notes / still need to check

- [ ] actual kiosk browser: readability from a few meters, portrait vs landscape, how it behaves when the network drops and comes back
- [ ] check publisher rules, especially pictures and showing stories on a work display. the app being open source doesn't grant rights to the feeds themselves.
- [ ] feed formats vary wildly, try a bunch of real sources and see where titles/images/summaries are missing
- [ ] browser + docker health over a long running session; don't call this production ready just because it starts once
- [ ] maybe add a separate browse mode later. NOT interactive menus on the kiosk.
- [ ] testing + proper docs once i've verified the real-world setup. until then these are working notes.

MIT applies to this code, not anyone else's RSS content or pictures.
