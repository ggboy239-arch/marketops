# Host MarketOps on Railway

1. Sign in at https://railway.com with GitHub.
2. Create **New Project** → **Deploy from GitHub repo**.
3. Select `ggboy239-arch/marketops`.
4. Open the service **Variables** tab and copy every value from the local `.env`.
5. Confirm the deployment start command is `python bot.py`.
6. Open **Deployments → View Logs** and confirm the Discord bot reports ready.
7. Stop the local VS Code copy after the Railway copy is online. Only one copy should use the Discord token.

Required lead variables:

- `DISCORD_TOKEN`
- `KEEPA_API_KEY`
- `AMAZON_HOLD_LEADS_CHANNEL_ID`
- `AMAZON_STOCK_PRESSURE_CHANNEL_ID`
- `AMAZON_LEAD_REVIEW_CHANNEL_ID`
- `AMAZON_LEADS_CHECK_MINUTES=30`
- `AMAZON_LEADS_MIN_PROFIT=10`
- `AMAZON_LEADS_MIN_ROI=20`
- `AMAZON_LEADS_MAX_ROI=100`

Copy the other existing MarketOps provider variables too, including `MARKETAUX_API_KEY`, `OPENAI_API_KEY`, and any provider keys used by the news and market cogs.

## Persistent state

MarketOps stores deduplication state under `data/`. To preserve it across deployments, add a Railway Volume mounted at `/app/data`.

## Cost control

Use Railway's usage page to set a monthly alert or hard limit. A hard limit stops the bot when reached.
