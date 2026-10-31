# alta-feedback

Форма «Предложить правку» для страницы про банк ALTA: `https://alta.smolevich.com/`.

## Ссылка для кнопок на странице

```
https://alta.smolevich.com/?s=<id раздела>&t=<заголовок раздела, urlencoded>
```

`s` — id из `<h2 id="…">` (буквы, цифры, `_`, `-`, до 40 знаков; иначе отбрасывается),
`t` — подставляется в поле «Раздел», человек может его поправить. Ссылка открывается в
новой вкладке (`target="_blank" rel="noopener"`).

## Как читать правки (координатор)

Токен лежит в Vault `secret/alta-feedback/admin_token` (поле `token`), достаётся по ssh
root-токеном из Keychain (см. `~/pet-projects/docs/secrets.md`). В argv токен не попадает:
curl читает заголовок из stdin.

```bash
RT=$(security find-generic-password -s vault-hetzner-root-token -w)
TOKEN=$(printf '%s' "$RT" | ssh -o ClearAllForwardings=yes bot-server '
  IFS= read -r VAULT_TOKEN; export VAULT_TOKEN VAULT_ADDR=http://127.0.0.1:8200
  vault kv get -field=token secret/alta-feedback/admin_token')

# новые с момента прошлого забора (ISO, UTC); status=new — только непросмотренные
printf 'Authorization: Bearer %s\n' "$TOKEN" | curl -fsS -H @- \
  'https://alta.smolevich.com/admin/suggestions?since=2026-10-31T00:00:00Z&status=new' | jq
```

Ответ: `{"count": N, "items": [{id, created_at, section_id, section_title, text, source,
contact, ip_hash, user_agent_short, status}, …]}`, по возрастанию `id`, до 500 за раз.
`since` — строго позже указанного момента; без `since` — все.

Сменить статус (`new`, `accepted`, `rejected`, `test`, `spam`):

```bash
printf 'Authorization: Bearer %s\n' "$TOKEN" | curl -fsS -H @- \
  -H 'Content-Type: application/json' -d '{"status":"accepted"}' \
  https://alta.smolevich.com/admin/suggestions/42/status
```

`contact` не публикуется — это обещано на форме.

## Инфраструктура

- Ingress `alta.smolevich.com → http://127.0.0.1:8101` и AppRole `alta-feedback-deploy` —
  в репо `infra`.
- Секреты Vault: `secret/alta-feedback/admin_token` (`token`), `secret/alta-feedback/ip_salt` (`salt`).
