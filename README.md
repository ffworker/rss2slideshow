# rss2slideshow

ok so this started because theres already a raspberry pi at work running Binary Emotions Raspberry Slideshow and i want to throw some rss/news + our own stuff on the screen without reinstalling the whole thing. should be possible by just giving the pi a list of image urls... so thats what this does (or is supposed to do, still testing)

**current status:** work in progress. dont just deploy this somewhere and assume it works on every slideshow version. real pi test still missing.

rough idea:

rss (currently hessenschau) -> render a few jpgs -> put them on an existing docker host -> inventory.txt with the urls -> existing pi pulls them using media.conf/serverlist

plus our own slides/photos, weather and a clock image. clock isnt actually live btw, its just the time when that jpg was rendered. might change that later, not sure yet.

this is mainly notes for myself rn. proper instructions when i actually deployed it and know what works.

## stuff i need to do / remember

- [ ] verify the actual Binary Emotions version + how serverlist / media.refresh behaves on our pi
- [ ] internal docker host ip etc, make sure the pi can actually reach the url (not just my laptop...)
- [ ] company slides/photos/logo from our own storage. obviously NOT in this public repo
- [ ] check news / weather provider terms for displaying this at work, esp pictures. current news slides are text only
- [ ] try changing the inventory while it runs. does it pick up new jpgs? how much ends up on the pi sd card?
- [ ] think about slide order / ratios. 5 news items in a row and 1 company slide might be kinda stupid
- [ ] test docker + real pi together before calling any of this ready
- [ ] weather city / coords still need setting. weather disabled in the example config
- [ ] maybe a nicer layout later but first just get it working

## setup-ish (not final instructions)

needs an existing docker host. no extra server and definitely no need to reinstall the pi. copy the example configs first:

```bash
cp .env.example .env
cp config.example.yaml config.yaml
```

edit both. `BIND_IP` is the interface docker should listen on, `public_url` is the actual address the raspberry pi can reach. **the example values are placeholders**. dont accidentally use localhost as the public url or the pi will try connecting to itself.

drop approved images in `content/company/` and `content/photos/` if needed. then:

```bash
docker compose up -d --build
docker compose logs -f signage
```

try from the pi too, not only from the host:

```bash
curl http://YOUR_DOCKER_HOST:8085/healthz
curl http://YOUR_DOCKER_HOST:8085/inventory.txt
```

need to check `/slides/...` urls from inventory are accessible as well.

**BACK UP existing media.conf first**, then add/change the following as appropriate for the installed Binary Emotions version (syntax/refresh still needs a real-world test):

```ini
serverlist: http://YOUR_DOCKER_HOST:8085/inventory.txt
media.refresh: yes
```

leave other pi settings/sources alone unless theres a reason to change them.

## files / random notes

- `app/` builds images + inventory and serves the files over http
- `config.example.yaml` and `.env.example` are templates, actual values live in untracked local files
- `content/` = company slides / photos; `assets/` reserved for approved branding
- `output/` gets generated, dont commit it
- image names include a hash. if the picture changes the name changes too, so slideshow has a chance to notice the update. old images are kept a bit longer so clients dont get a 404 midway through downloading
- host/port should only be reachable from the company network. no reason to expose internal photos or announcements publicly
- current generator still needs a proper end-to-end test, also error handling/retention to review before production

## docs (later)

- [ ] **self / human:** actual README + install/maintenance steps written by me once ive used it on the real setup. these messy notes are not that.
- [ ] **AI-assisted / human verified:** separate clearly labeled documentation version. verify each step against what i actually installed/observed first; dont just copy generated instructions and call it done.

MIT for this code only. not affiliated with Binary Emotions, Hessenschau or Open-Meteo; their content/services have their own terms.
