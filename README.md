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

## Форма «Где открыли счёт» — `/account`

Анонимный отчёт вкладчика за 30–40 секунд: банк (18 действующих банков по реестру NBS на
01.11.2026 + «другой»), город, личный счёт или ИП, результат (открыли / отказали / в
процессе), дата визита (по умолчанию сегодня, Белград), статус в Сербии (необязательно: ВНЖ/ПМЖ,
только белый картон, ничего нет, гражданин), какие документы просили и свободный комментарий.

- **Голосовой ввод** в комментарий — кнопка-микрофон на Web Speech API браузера (`ru-RU`),
  без нашего сервера. Нет `SpeechRecognition` в браузере — кнопки нет, остаётся микрофон
  клавиатуры телефона.
- **Личные данные** вырезаются до записи: email, IBAN, счёт 18 цифр / 3-13-2, JMBG
  (13 цифр), любые группы от 9 цифр (телефоны, паспорта). Даты через точку не трогаются.
- **Спам** — как у правок: скрытое поле `website`, 5 отчётов в час с хэша IP (лимит отдельный
  от правок), тело до 16 КБ.

Ссылка для кнопки на странице: `https://alta.smolevich.com/account`.

### Чтение и модерация (координатор)

Тот же токен, что для правок:

```bash
printf 'Authorization: Bearer %s\n' "$TOKEN" | curl -fsS -H @- \
  'https://alta.smolevich.com/admin/accounts?since=2026-11-01T00:00:00Z&status=new' | jq

printf 'Authorization: Bearer %s\n' "$TOKEN" | curl -fsS -H @- \
  -H 'Content-Type: application/json' -d '{"status":"accepted"}' \
  https://alta.smolevich.com/admin/accounts/7/status
```

Элемент: `{id, created_at, bank, city, account_type, result, visit_date, residency,
documents: [коды], comment, ip_hash, user_agent_short, status}`. Статусы: `new`,
`accepted`, `rejected`, `test`, `spam`.

### Публичный JSON

`GET https://alta.smolevich.com/api/accounts/public` — без токена, только `accepted`, свежие
визиты сверху, до 2000:

```json
{"count": 1,
 "items": [{"id": 7, "visit_date": "2026-10-31", "bank": "OTP banka", "city": "Нови-Сад",
            "account_type": "entrepreneur", "result": "refused", "residency": "boravak",
            "documents": ["passport", "apr"], "comment": "…"}],
 "labels": {"account_type": {…}, "result": {…}, "residency": {…}, "documents": {…}}}
```

`bank` и `city` — уже готовые названия (или текст «другого»), остальное — коды, подписи к
ним в `labels`. Времени отправки, `ip_hash` и UA в ответе нет.

## Инфраструктура

- Ingress `alta.smolevich.com → http://127.0.0.1:8101` и AppRole `alta-feedback-deploy` —
  в репо `infra`.
- Секреты Vault: `secret/alta-feedback/admin_token` (`token`), `secret/alta-feedback/ip_salt` (`salt`).
