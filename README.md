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
cp branding/brand.example.yaml branding/brand.yaml
```

edit `.env` first: `BIND_IP` must be an address the display can actually reach. the example uses `127.0.0.1` on purpose, so it'll only work on the docker host until you change it. don't expose your internal display stuff to the whole internet just because it runs in a browser.

then add your RSS URLs in `content/feeds.txt` (see below), change the customer look in `branding/brand.yaml` if you want, and start it:

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

## first customer test / branding

ok this is the bit i actually want to try with a real customer now. **one installation = one customer look** for now. their colors/font/logo should NOT need me editing python/html or copying a whole new repo.

`branding/brand.yaml` is the customer file (copy the example if you don't have it yet). `content/feeds.txt` is still the ONLY list for RSS URLs + their source labels, totally separate from customer branding.

```yaml
brand_name: "Kundenname"
accent_color: "#8b3932"
background_color: "#f8f7f3"
text_color: "#242424"
font_family: news
```

`brand_name` is the name in the kiosk header, NOT the RSS source name. `accent_color` is for small UI details (source label/line), not a giant colored background. background/text colors are optional; check contrast/readability on the actual screen if you change those. hex colors like `#123456` or `#abc` work.

**logo:** put a PNG at `branding/logo.png`. **customer font:** if they have a webfont file that we're actually licensed to serve, put it at `branding/font.woff2`. the kiosk uses it for headlines and body. do not commit customer logos, client details or licensed font files in this public repo. the local branding folder is mounted into the container read-only, but the browser WILL download that font when it opens the kiosk, so the webfont license needs to allow this usage.

if i only get a font *name*, put it under `font_family` for now, e.g. `font_family: Verdana`. it will only look right if that font is installed on the kiosk device. `news` gives the old Arial/Georgia mix; `sans`, `serif`, `mono` are the other easy presets. a supplied `font.woff2` takes priority so different kiosk devices will look the same.

**quick customer rehearsal:** copy the brand example, put their color/name/font in there and look at `http://YOUR_DOCKER_HOST:8085/`. edit `branding/brand.yaml` while it's running, or replace the logo/font file. the kiosk picks up the new look on its next ~30s browser poll, without changing the RSS feeds or rebuilding Docker. first time after this feature lands you still need `docker compose up -d --build` to get the new code and branding mount. older installations can keep using their existing `brand_name`/`accent_color` in `config.yaml` until they create `branding/brand.yaml` (then that new file takes over).

if a customer needs a totally separate set of feeds **and** different branding at the same time, that's another installation/container configuration for now. this is not a multi-customer login system or an on-screen settings menu.

## actual first customer demo (bistro connect)

first attempt looked pretty bad on screen tbh. huge group logo on a white slab, orange everywhere, and news cramped into the remaining space. the screenshot made that obvious.

changed it so **Bistro Connect is the main name**: round bistro logo beside the name + meet · eat · chill. the company's wide group logo is just a small optional thing in the header when the screen is big enough. hidden below ~1600px wide / 800px tall, because it's not worth making the news tiny just to squeeze in 5 more logos.

palette from their supplied file is orange #ec6608 and yellow #ffdd00, but covering a whole TV in both looked wild. this version keeps orange as a thin header edge / footer, uses a really pale yellow (#fff7d9) behind the actual news and a light header (#fff9ef) instead. need to see it on the real TV before deciding if the colors are right. Calibri requested, falls back to Carlito / Arial if missing on the kiosk; haven't committed any proprietary fonts.

files for the approved public example:

- `branding/examples/logserv/brand.yaml` – name/colors/font/layout, can tweak that
- `branding/examples/logserv/logo.png` – little Bistro Connect round logo, primary
- `branding/examples/logserv/group-logo.png` – group wordmark, only when there's room

`http://YOUR_DOCKER_HOST:8085/demo/logserv` is the sample preview. `/` stays my existing normal kiosk. both read the same `content/feeds.txt` for now; demo isn't a second account or some multi-tenant mess. actual customer's files are public here because they explicitly allowed this example, not because we're going to put everyone else's logos in git.

layout is one article at a time, no clickable controls, and uses available space rather than fixed FHD pixel coordinates. at 1280×720 it should show the Bistro identity, clock, one picture and readable article text without group logo; at 1920×1080 it has room for more. gotta verify both on the actual kiosk/browser, not just assume it's perfect from CSS.

the 'Friedrich Friedrich wünscht guten Appetit' idea can go in later if they still want it, not cluttering this first version.

## few questions i already had

**why different files?** `.env` is for docker/network + clock timezone + article timing. `config.yaml` is for article limits, refresh interval and turning feed pictures on/off. `branding/brand.yaml` is the customer look. `content/feeds.txt` is the ONLY list for actual RSS URLs. keeping those apart means i can swap a customer look without touching their feeds.

**can i change the display time / timezone?** yup, `SLIDE_SECONDS=20` and `DISPLAY_TZ=Europe/Berlin` in `.env` (use an IANA timezone, e.g. `UTC`). since those settings are passed to the container when it starts, run `docker compose up -d` after editing them. feed list edits don't need this. timezone affects the clock / published times.

**can i brand it?** yep, see the customer test above. name, colors and font in `branding/brand.yaml`; optional local `branding/logo.png` and `branding/font.woff2`. no code changes or restart for those after the upgraded container is running. the existing `assets/logo.png` still works as a fallback for my older setup.

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
