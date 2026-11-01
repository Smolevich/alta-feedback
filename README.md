# alta-feedback

Feedback for a public write-up about the bank ALTA (Serbia): what happened to the bank
and what its depositors should do — <https://claude.ai/artifact/RrfqFLbzQh5wEkb9RxC7UQ>.

The forms and pages are in Russian. Issues and pull requests are welcome in English,
Serbian or Russian.

The service runs at <https://alta.smolevich.com/> and collects two kinds of answers:

- **"Suggest a correction"** (`/`) — every section of the write-up has a button: a person
  writes what is inaccurate and, optionally, a source.
- **"Where did you open an account"** (`/account`) — after ALTA lost its licence,
  depositors are looking for a new bank. A thirty-second anonymous form: bank, city,
  personal or sole-proprietor (preduzetnik) account, the outcome, which documents were
  requested. Verified answers are public at
  [`/account/stats`](https://alta.smolevich.com/account/stats) and as JSON at
  [`/api/accounts/public`](https://alta.smolevich.com/api/accounts/public).

No logins, ads or third-party scripts: pages load only their own styles and three small
scripts of their own.

## What is stored

The code is open so that this can be checked. Everything lives in one SQLite database on
the server.

**Correction:** page section, text, source, contact (if given — never published),
submission time.

**Account report:** bank, city, branch (if given), personal or sole-proprietor account,
outcome, visit date, residence status in Serbia (if given), requested documents, comment,
submission time.

**Numbers are scrubbed from account reports before they are written.** From the comment
and any custom-text field the server removes anything that looks like an email, IBAN,
account number (18 digits or 3-13-2), JMBG (13 digits) and any group of 9+ digits —
phone and passport numbers. They are replaced with `[скрыто]` ("hidden"). The code is
`scrub_pii` in [`src/alta_feedback/accounts.py`](src/alta_feedback/accounts.py).

**IP is not stored.** For spam protection (at most 5 submissions per hour from one
address) only a hash is kept: the first 32 characters of `sha256("<secret salt>:<IP>")`.
Only the server knows the salt, so the IP cannot be recovered from the hash. The first
120 characters of the browser name (User-Agent) are also kept to tell bots apart. The
server logs do not record the IP either: access logs are off.

**Retention.** The answers themselves — while the service runs. The IP hash and the
browser name are wiped after 30 days. Used anti-bot challenges — after 30 minutes.

**What is public.** Only account reports checked by the author, and only the answer
fields: bank, city, account type, outcome, visit date, status, documents, comment. No
submission time, hash or browser. The branch is shown only when at least two checked
reports name the same branch of the same bank; otherwise it is hidden ("other branches"),
so a single answer cannot point at one person. Corrections are not public.

**Voice.** The "Голосом" (voice) button uses the browser's speech recognition: Chrome
sends the audio to Google, Safari to Apple. We never receive or store the audio — only
the resulting text arrives, and only if you submit it. You can skip the button and use
the keyboard's dictation instead.

**Bot check** — proof-of-work in the [ALTCHA](https://altcha.org) format behind an
"I'm not a robot" checkbox: ticking it makes the browser solve a task for a second or
two. No cookies and no requests to third-party services.

## Want to fix or add something

Open a [pull request](https://github.com/Smolevich/alta-feedback/pulls) — I will review
it. Bugs and ideas go to [issues](https://github.com/Smolevich/alta-feedback/issues).
Corrections to the write-up itself are easiest to send through the form on the site.

## Running locally

You need Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
IP_SALT=dev ADMIN_TOKEN=dev uv run uvicorn --factory alta_feedback.main:create_app --port 8101
uv run ruff check src tests
uv run pytest -q
```

The form is at <http://127.0.0.1:8101/account>, the database at `data/feedback.db`.

## How it works

- Starlette + Jinja, SQLite, styles inlined in the templates
  (`src/alta_feedback/templates/`).
- Scripts (`src/alta_feedback/static/`): `combo.js` — searchable lists, `pow.js` — bot
  check, `voice.js` — voice input. The forms open without scripts too, but an account
  report is not accepted without the bot check.
- Deploy — GitHub Actions on push to `main`: tests and lint, then upload to the server and
  restart. Secrets live in Vault on the server and in the repository secrets, never in the
  code.

Moderation, public JSON and deploy details — [`docs/ops.md`](docs/ops.md); why it is built
this way — [`docs/decisions.md`](docs/decisions.md).

## License

[MIT](LICENSE) © Stanislav Shupilkin
