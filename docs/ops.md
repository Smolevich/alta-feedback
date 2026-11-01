# Operations

## Links for the buttons on the write-up page

```
https://alta.smolevich.com/?s=<section id>&t=<section title, urlencoded>
https://alta.smolevich.com/account
https://alta.smolevich.com/account/stats
```

`s` is the id from `<h2 id="…">` (letters, digits, `_`, `-`, up to 40 characters;
anything else is dropped), `t` prefills the "Section" field, which the person can edit.
Links open in a new tab (`target="_blank" rel="noopener"`): the write-up lives in an
iframe and cannot send requests here itself.

## Moderation

Everything under `/admin/` requires the `ADMIN_TOKEN` (header
`Authorization: Bearer …`). Keep the token out of argv — curl reads the header from stdin:

```bash
# corrections; since — ISO in UTC, strictly after; status=new — not yet reviewed
printf 'Authorization: Bearer %s\n' "$ADMIN_TOKEN" | curl -fsS -H @- \
  'https://alta.smolevich.com/admin/suggestions?since=2026-10-31T00:00:00Z&status=new' | jq

# account reports
printf 'Authorization: Bearer %s\n' "$ADMIN_TOKEN" | curl -fsS -H @- \
  'https://alta.smolevich.com/admin/accounts?status=new' | jq

# change status: new, accepted, rejected, test, spam
printf 'Authorization: Bearer %s\n' "$ADMIN_TOKEN" | curl -fsS -H @- \
  -H 'Content-Type: application/json' -d '{"status":"accepted"}' \
  https://alta.smolevich.com/admin/accounts/7/status
```

A list response is `{"count": N, "items": [...]}`, ascending by `id`, up to 500 at a time.

- Correction: `{id, created_at, section_id, section_title, text, source, contact, ip_hash,
  user_agent_short, status}`. `contact` is never published — the form promises that.
- Report: `{id, created_at, bank, city, account_type, result, visit_date, residency,
  documents, comment, ip_hash, user_agent_short, status, branch}`. `branch` is `null` for
  reports sent before the field existed and when the person left it empty or chose
  «Не помню / не важно».

Only reports with status `accepted` make it into the stats and the public JSON.

## Public JSON

`GET /api/accounts/public` — no token, `accepted` only, most recent visits first, up to
2000:

```json
{"count": 1,
 "items": [{"id": 7, "visit_date": "2026-10-31", "bank": "OTP banka", "city": "Нови-Сад",
            "account_type": "entrepreneur", "result": "refused", "residency": "boravak",
            "documents": ["passport", "apr", "Справка из налоговой"], "comment": "…"}],
 "labels": {"account_type": {…}, "result": {…}, "residency": {…}, "documents": {…}}}
```

`branch` is shown only if at least two accepted reports name that branch of that bank,
otherwise it is `null` (the same rule as the stats page). `bank` and `city` are display names; `account_type`, `result`, `residency`, `documents`
are codes with captions in `labels`. `residency` and `documents` may also hold the
person's own text if they entered a value outside the list.

## Branch directory

`src/alta_feedback/data/branches.json` — branches of every bank in the form, taken only from
the banks' own sites (branch-locator JSON, page or PDF; never Google Maps). Each bank has
`source`, `collected_at`, `status` and `branches: [{city, name, address}]`. Rebuild:

```bash
uv run scripts/build_branches.py            # all banks
uv run scripts/build_branches.py otp erste  # only these
```

If a bank's site fails, the bank keeps its previous list and date; a bank with no list gets
`status: "unavailable"` and the form offers only free text for it. The form asks
`/account/branches?bank=…&city=…` for hints of that bank in that city. The file lives in the
package, not in `data/`: `data/` is the database directory and the deploy copies only `src/`.

## Deploy

GitHub Actions `deploy.yml` on push to `main` (and manually): tests and lint → copy to the
server over Tailscale → `uv sync` → restart the systemd unit → check `/healthz` and the
pages. The deploy reads `ADMIN_TOKEN` and `IP_SALT` from Vault and writes them to `.env`
next to the app; if the read fails, the previous values are kept.

- Repository secrets: `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET`, `VDS_HOST`, `VDS_PORT`,
  `VDS_USER`, `VDS_SSH_KEY`, `VDS_SSH_PASSPHRASE`.
- Repository variables: `VAULT_ROLE_ID_FILE`, `VAULT_SECRET_ID_FILE` (AppRole files on the
  server), `VAULT_ADMIN_TOKEN_PATH`, `VAULT_IP_SALT_PATH` (secret paths in Vault).
- **Do not change the salt without a reason:** every IP hash changes with it and the rate
  limit resets.
