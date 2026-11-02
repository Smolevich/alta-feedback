# alta-feedback — notes for agents

`CLAUDE.md` is a symlink to this file: one source for Claude Code and Codex.

Feedback forms for a public write-up about the Serbian bank ALTA: corrections to the
write-up (`/`) and anonymous "where did you open an account" reports (`/account`, stats at
`/account/stats`, JSON at `/api/accounts/public`). The repository is public. The forms
and pages are in Russian; issues and PRs may be in English, Serbian or Russian.

- Stack: Python 3.13, Starlette + Jinja, SQLite. Own scripts live in
  `src/alta_feedback/static/` — no libraries, no bundler.
- Code: `main.py` routes and middleware, `accounts.py` account-report parsing and
  `scrub_pii`, `validate.py` correction form and IP hashing, `store.py` SQLite,
  `pow.py` ALTCHA-style proof-of-work, `stats.py` public stats, `branches.py` the bank
  branch directory (`data/branches.json`, rebuilt by `uv run scripts/build_branches.py`), `nbs.py`
  official National Bank of Serbia figures per bank on the stats page (`data/nbs_banks.json`,
  quarter 2026Q2, computed from each bank's NBS balance sheet and income statement; a figure
  without an https `source_url` is not rendered).

```bash
uv sync
uv run pytest -q
uv run ruff check src tests
IP_SALT=dev ADMIN_TOKEN=dev uv run uvicorn --factory alta_feedback.main:create_app --port 8101
```

The database goes to `$DATA_DIR/feedback.db` (default `data/`).

## Rules

- **No personal data is stored.** No logins, raw IPs or contacts in account reports.
  Every free-text value of an account report (comment, custom bank/city/status/document/branch)
  goes through `accounts.scrub_pii` before it is written — a new text field without it is
  not accepted. Corrections (`/`) are not scrubbed: their optional `contact` is private
  and never published.
- **IP is only a salted hash.** It and the short User-Agent are wiped after 30 days
  (`TRACE_TTL`); the wipe runs lazily on the next submission of either form.
- **Public output is `accepted` reports only**, answer fields only
  (`PUBLIC_ACCOUNT_COLUMNS`) — no `ip_hash`, User-Agent or `created_at`. Corrections are
  never public.
- **No third-party scripts, fonts or trackers.** CSP is `default-src 'none'`; only
  `/account` adds `script-src 'self'` and `connect-src 'self'` (fresh PoW challenge).
- **A test for every behaviour and a regression test for every bug**; pytest tests
  behaviour, not implementation.
- **Deploy only through CI** (push to `main`), no manual changes on the server. No secrets
  or server addresses in the repository — they live in GitHub secrets and variables.
- Light theme always; page texts in plain Russian. Code comments and UI strings stay in
  Russian.

What is stored and why — `README.md`; moderation and deploy — `docs/ops.md`; decisions —
`docs/decisions.md`.
