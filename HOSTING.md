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
- `AMAZON_LEADS_MIN_ROI=40`
- `AMAZON_LEADS_MAX_ROI=100`

Copy the other existing MarketOps provider variables too, including `MARKETAUX_API_KEY`, `OPENAI_API_KEY`, and any provider keys used by the news and market cogs.

## Persistent state

MarketOps stores deduplication state under `data/`. To preserve it across deployments, add a Railway Volume mounted at `/app/data`.

The Amazon storefront monitor uses the existing `KEEPA_API_KEY` and saves its
seller/product history in `data/storefront_state.json`. Optional controls are
`STOREFRONT_CHECK_MINUTES=10` (minimum 5),
`STOREFRONT_PRODUCTS_PER_SCAN=20` (maximum 20), and
`STOREFRONT_PRODUCT_DELAY_SECONDS=20` (minimum 10). Products are requested one
at a time so Keepa tokens can refill between items. A Keepa refill response
pauses and resumes the same scan automatically.

Both Keepa systems now use one process-wide gate so the storefront monitor and
lead scanner cannot spend the same token pool simultaneously. Set
`STOREFRONT_BASELINE_ON_ADD=true` to ignore a seller's existing catalog and
alert only on listings discovered after the seller is added.

The Tomorrow Setup journal uses `data/prediction_journal.db`. Create a Discord
channel named `tomorrow-setup`, or override `TOMORROW_SETUP_CHANNEL`. Keep the
Railway volume mounted at `/app/data` so forecasts and graded results survive
deployments.

## Cost control

Use Railway's usage page to set a monthly alert or hard limit. A hard limit stops the bot when reached.
