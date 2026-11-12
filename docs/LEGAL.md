# Legal and source compliance

MangaPoisk Reborn is a **catalogue and reader interface**.  It does not claim
ownership of manga, translations or images.  All metadata and page images
belong to their respective rights holders and are fetched from third-party
sources.

## Rules the code follows

1. **Public data only.**  Adapters read public catalogue pages/APIs.  No
   account takeover, no paywall/DRM circumvention, no CAPTCHA solving.
2. **No bypass.**  If a source blocks the service, the adapter returns an
   error.  We do not rotate proxies to evade blocks.
3. **Politeness.**  Per-source token bucket (default 30 req/min), exponential
   backoff, `Retry-After`, aggressive caching.  Do not lower these limits
   without a good reason.
4. **Minimal personal data.**  The library stores email, display name, password
   hash, bookmarks and reading progress.  No IP/cookie tracking.  Refresh
   tokens are stored as SHA-256 hashes.
5. **Optional cookies.**  Operators may supply their own session cookies for
   sources that show more content to signed-in users.  Cookies stay in `.env`,
   are never logged and are never sent to clients.
6. **Attribution.**  The UI shows the source name and a link to the source
   page.  Exports include a footer identifying MangaPoisk Reborn.

## Notice for rights holders

If you believe content indexed by this software infringes your rights, open an
issue in the repository or contact the repository owner.  The project can
remove a source adapter or a catalogue entry without affecting the rest of the
stack.  Because the software is self-hosted, the operator of a deployment is
responsible for its content and for complying with local law.

## Software licence

The source code is MIT licensed (see `LICENSE`).  The licence does **not**
grant rights to third-party manga, translations, images or trademarks.

## Operator checklist

- [ ] Set a real `JWT_SECRET`, `INTERNAL_TOKEN`, `ADMIN_PASSWORD` and
      `CONTROL_SECRET_KEY`.
- [ ] Put the stack behind HTTPS.
- [ ] Keep `MEDIA_ALLOWED_HOSTS` restricted to the CDNs you actually use.
- [ ] Configure backups and a retention policy for exports.
- [ ] Respect a source's request to stop indexing.
- [ ] Do not enable sources whose robots.txt forbids the API (Remanga is
      disabled by default for this reason).
