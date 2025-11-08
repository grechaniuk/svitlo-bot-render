Deploy on Render, no terminal:
1) Upload this folder to a GitHub repo via web.
2) In Render → New → Blueprint → pick repo. It finds render.yaml.
3) After it creates a Worker, set Environment variables: TELEGRAM_BOT_TOKEN (required), OPENAI_API_KEY (optional), DEFAULT_LANG, DEFAULT_COUNTRY.
4) Click Deploy. Open Telegram, /start.
