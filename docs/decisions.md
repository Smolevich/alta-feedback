# Decisions

- **A separate repo, not a page in an existing one.** A public service with its own
  rollout and its own secrets; nothing is shared with other projects.
- **Server-side templates, no bundler.** Forms and styles are served from templates, our
  scripts are three small dependency-free files, everything with
  `Cache-Control: no-store`/`no-cache` — so there is no asset-versioning problem behind a
  CDN cache. If interactivity grows, move to a bundler.
- **No messenger notifications.** Corrections and reports are pulled through the
  token-protected API (`/admin/...`), not pushed out.
- **Rate limit in the database, not in memory.** We count rows with the same `ip_hash`
  in the last hour: survives restarts and needs no extra state.
- **Account reports use the same database and service.** A separate `accounts` table,
  the same token and the same salt: a second service for one form does not pay off.
- **Voice is the browser's Web Speech API only.** Free and needs no server of ours, but
  the audio goes to the browser's recogniser (Google for Chrome, Apple for Safari) — this
  is stated under the button. Where the API is missing (Telegram/Instagram in-app
  browsers, Firefox), the phone keyboard's dictation remains. Server-side STT only if it
  turns out people do not dictate without it.
- **Searchable lists, not chips.** Chips with every bank and document took three phone
  screens. Now it is a field with a dropdown (our own `combo.js` without libraries,
  `<datalist>` as the fallback), and a custom value is typed into the same field. Our own
  list rather than a bare `datalist`: datalist suggestions are awkward on iOS, and
  documents need tags.
- **Proof-of-work instead of a captcha.** ALTCHA format, but our own implementation
  (~100 lines): the challenge is HMAC-signed and embedded in the page, so there are no
  external requests, cookies or `connect-src`. Cloudflare Turnstile was rejected — it is a
  third-party script. PoW will not stop a persistent bot with a real browser, but it makes
  mass submission expensive; together with the rate limit and the `website` honeypot that
  is enough for a form with no spam value.
- **The IP hash and browser name live 30 days.** The rate limit needs an hour; the rest is
  headroom to sort out a spam wave. After that the fields are wiped on the next
  submission of either form.
