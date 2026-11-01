# Эксплуатация

## Ссылки для кнопок на странице разбора

```
https://alta.smolevich.com/?s=<id раздела>&t=<заголовок раздела, urlencoded>
https://alta.smolevich.com/account
https://alta.smolevich.com/account/stats
```

`s` — id из `<h2 id="…">` (буквы, цифры, `_`, `-`, до 40 знаков; иначе отбрасывается),
`t` — подставляется в поле «Раздел», человек может его поправить. Ссылки открываются в
новой вкладке (`target="_blank" rel="noopener"`): разбор живёт в iframe и сам слать
запросы сюда не может.

## Модерация

Всё под `/admin/` закрыто токеном `ADMIN_TOKEN` (заголовок `Authorization: Bearer …`).
Токен в argv не кладём — curl читает заголовок из stdin:

```bash
# правки; since — ISO в UTC, строго позже; status=new — непросмотренные
printf 'Authorization: Bearer %s\n' "$ADMIN_TOKEN" | curl -fsS -H @- \
  'https://alta.smolevich.com/admin/suggestions?since=2026-10-31T00:00:00Z&status=new' | jq

# отчёты о счетах
printf 'Authorization: Bearer %s\n' "$ADMIN_TOKEN" | curl -fsS -H @- \
  'https://alta.smolevich.com/admin/accounts?status=new' | jq

# сменить статус: new, accepted, rejected, test, spam
printf 'Authorization: Bearer %s\n' "$ADMIN_TOKEN" | curl -fsS -H @- \
  -H 'Content-Type: application/json' -d '{"status":"accepted"}' \
  https://alta.smolevich.com/admin/accounts/7/status
```

Ответ списка: `{"count": N, "items": [...]}` по возрастанию `id`, до 500 за раз.

- Правка: `{id, created_at, section_id, section_title, text, source, contact, ip_hash,
  user_agent_short, status}`. `contact` не публикуется — это обещано на форме.
- Отчёт: `{id, created_at, bank, city, account_type, result, visit_date, residency,
  documents, comment, ip_hash, user_agent_short, status}`.

В статистику и публичный JSON попадают только отчёты со статусом `accepted`.

## Публичный JSON

`GET /api/accounts/public` — без токена, только `accepted`, свежие визиты сверху, до 2000:

```json
{"count": 1,
 "items": [{"id": 7, "visit_date": "2026-10-31", "bank": "OTP banka", "city": "Нови-Сад",
            "account_type": "entrepreneur", "result": "refused", "residency": "boravak",
            "documents": ["passport", "apr", "Справка из налоговой"], "comment": "…"}],
 "labels": {"account_type": {…}, "result": {…}, "residency": {…}, "documents": {…}}}
```

`bank` и `city` — готовые названия; `account_type`, `result`, `residency`, `documents` —
коды с подписями в `labels`. В `residency` и `documents` может прийти и свой текст
человека, если он вписал значение не из списка.

## Деплой

GitHub Actions `deploy.yml` на push в `main` (и вручную): тесты и линт → копирование на
сервер через Tailscale → `uv sync` → перезапуск systemd-юнита → проверка `/healthz` и
страниц. `ADMIN_TOKEN` и `IP_SALT` деплой читает из Vault и кладёт в `.env` рядом с
приложением; прочитать не вышло — оставляет прежние значения.

- Секреты репозитория: `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET`, `VDS_HOST`, `VDS_PORT`,
  `VDS_USER`, `VDS_SSH_KEY`, `VDS_SSH_PASSPHRASE`.
- Переменные репозитория: `VAULT_ROLE_ID_FILE`, `VAULT_SECRET_ID_FILE` (файлы AppRole на
  сервере), `VAULT_ADMIN_TOKEN_PATH`, `VAULT_IP_SALT_PATH` (пути секретов в Vault).
- **Соль не менять без причины:** с ней меняются все хэши IP, и лимит частоты обнуляется.
