# Updating safely

RSS feeds, credentials, uploaded logos and design settings are **installation-owned data**. They live under `.env`, `config.yaml`, `content/`, `branding/` and `assets/` on the host, not in Git or the application image.

Use the guarded manual update script for an existing running installation:

```sh
python3 scripts/safe_update.py check
python3 scripts/safe_update.py update
```

The script requires a clean `main` checkout and a working Docker Compose service. It backs up local data to a private location outside the checkout, checks incoming Git paths, updates code, rebuilds the container and compares persistent file fingerprints and effective display settings.

After rebuilding, it waits up to 45 seconds for the HTTP health endpoint
before comparing the effective display settings. This avoids treating a freshly
started, not-yet-ready web server as an immediate update failure. A timeout
still stops the update and requires operator attention; it never silently
rolls back or restores local configuration.

It stops on detected configuration drift without silently overwriting live editor changes. It does not guarantee pixel-identical rendering after arbitrary future HTML/CSS changes; always inspect the actual screen. For stopped services, `--no-ui-check` skips live UI comparison with reduced protection.

Backups include credentials and must be protected. Pause editor changes during updates. Check `git remote -v` first: new
public clones should fetch from `https://github.com/ffworker/rss2slideshow.git`,
not the former private/archived repository. For a custom Compose project
name, use the matching `COMPOSE_PROJECT_NAME` environment variable for the
entire update session. The old SSH deploy key is not necessary for public
read-only HTTPS clones; revoke it only after confirming nothing else uses it. Avoid `git reset --hard`, `git clean -fdx` and destructive container cleanup commands while troubleshooting.
