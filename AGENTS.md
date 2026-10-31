# alta-feedback

Приём правок к публичной странице про банк ALTA (артефакт claude.ai). Страница живёт в
iframe с CSP `connect-src 'self'`, поэтому сама слать сюда ничего не может: у каждого
раздела кнопка-ссылка открывает в новой вкладке форму на `https://alta.smolevich.com/`.

- Starlette + Jinja, одна HTML-форма без JS, SQLite `data/feedback.db`.
- Прод: `bot-server`, `/opt/alta-feedback`, юнит `alta-feedback.service`, `127.0.0.1:8101`,
  наружу — туннель `telegram-bot` (ingress в `infra/fleet/hardening/cloudflared/config.yml`),
  **без** Cloudflare Access: форма публичная.
- Деплой только GitHub Actions (`deploy.yml`, push в `main`). Секреты — Vault через AppRole
  `alta-feedback-deploy` (политика и роль в репо `infra`).

## Запуск

```bash
uv sync
IP_SALT=dev ADMIN_TOKEN=dev uv run uvicorn --factory alta_feedback.main:create_app --port 8101
uv run ruff check src tests
uv run pytest -q
```

## Что знать до правок

- **Никаких сторонних скриптов и трекеров.** CSP `default-src 'none'`, стили встроенные;
  JS на странице нет вовсе — форма работает обычным POST с редиректом на `/spasibo`.
- **IP не хранится.** Только `sha256(соль:ip)`, соль `secret/alta-feedback/ip_salt`. Смена
  соли обнуляет лимит 5 правок/час с адреса — не менять без причины.
- **Спам:** скрытое поле `website` (заполнено — молча «спасибо», в базу не пишем), лимит
  5/час по хэшу IP (считается по базе, переживает рестарт), тело запроса до 16 КБ.
- **Чтение правок — только токеном** (`secret/alta-feedback/admin_token`), уведомлений в
  Telegram нет намеренно: координатор забирает сам, команда — в `README.md`.
- Тёмной темы нет: светлая всегда (правило Стаса).
