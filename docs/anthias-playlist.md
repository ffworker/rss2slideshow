# Anthias / digital signage: one RSS article per playlist visit

This is an **optional single-screen integration**. The normal `/kiosk` remains an
independent, continuously rotating news display.

## Why use playlist mode?

When a website appears between images/videos in an Anthias playlist, showing
*all* articles at once would delay the next playlist asset. Playlist mode shows
**one article per website visit**. Anthias controls how long that asset stays on
the screen, while RSS2Slideshow chooses the next article and persists progress.

### URLs

Set up the URL as a **website** asset in Anthias:

- `https://your-display.example/kiosk?playlist=1` – rotate between *all* configured RSS feeds.
- `https://your-display.example/kiosk?playlist=1&feed=0` – only the first feed listed in RSS2Slideshow.
- `https://your-display.example/kiosk?playlist=1&feed=1` – second feed, etc.

Each website is a separate Anthias asset and can have its **own duration**,
for example 12 seconds for one source and 18 seconds for another. Do not use
`/admin` as the website URL. No changes are required in Anthias Hub.

For each load of the website, the kiosk calls `/api/playlist-next` exactly once,
advances to the next article for that feed, and persists the last article ID in
`content/playlist-state.json`. The same page remains on the chosen article until
Anthias switches assets. If the webview survives and becomes hidden/visible
instead of reloading, a visibility event attempts to advance it again.

RSS article refresh and the standalone kiosk timer are unrelated to Anthias
asset durations. Changing feed order changes the meaning of `feed=0`,
`feed=1` etc. Include `content/playlist-state.json` in normal content backups.

## One-TV acceptance checklist

1. Use a 1920×1080 (16:9) TV signal, 100% browser zoom, and disable overscan if available.
2. Adjust design in `/admin`: top/bottom padding, clock size, image side, QR
   placement/size. The embedded preview renders a **1920×1080 CSS-pixel canvas**
   scaled down to fit the browser; it cannot force the physical Pi/TV resolution.
3. Add one website asset in Anthias with a 10–20 second duration. Check that
   the next playlist item starts promptly; do not wait for all RSS articles.
4. Add a second website asset with another `feed=N` if per-source durations are
   wanted. Verify at the **actual TV** that reentry after other media displays
   the next article from the selected feed.
5. Ensure a feed contains at least **two** valid articles. If it only has one,
   a different article on the next visit is logically impossible.
6. Restart RSS2Slideshow and verify that per-feed progression survives. Check
   the article has not been cut off by the footer on a long-headline case.

Browser/webview reuse, remote image loading, and HDMI display settings vary
by Anthias/Pi model; a successful Flask or CI test is **not** a substitute
for testing actual asset transitions on the screen.

The endpoint is intentionally read-only for feed content but it **advances
the playlist cursor**, so don't poll it from monitoring or previews. Use
`/healthz` and `/api/articles` for health checks instead.
