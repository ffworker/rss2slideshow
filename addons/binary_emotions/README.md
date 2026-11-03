# Optional JPEG output for older signage players

The normal RSS2Slideshow kiosk is a webpage at `/`. Some older signage players consume JPEG slide URLs instead. For those devices, you can set `BINARY_EMOTIONS_ADDON=true` in your local `.env`.

- `/addons/binary-emotions/inventory.txt` lists the generated JPEG URLs.
- `/addons/binary-emotions/slides/<article-id>.jpg` returns 1920×1080 slides.

Only article text and the configured local theme are rendered; the add-on does not fetch remote article images.

These endpoints are not separately authenticated when enabled. Restrict access at the network or reverse proxy. The external player's scheduling and configuration are outside the scope of this project.
