# MarketOps

Discord-first market learning, news routing, and Amazon sourcing assistant.

## What it does

- Routes fresh news to `#breaking-news`, `#general-news`, `#ai-news`, `#fed`,
  `#geopolitics`, `#crypto`, and `#reddit-hot`.
- Builds a live dashboard from ES, NQ, VIX, oil, gold, DXY, US10Y, and BTC.
- Posts morning briefs, market-change explanations, and stock-move lessons.
- Creates a probability-based Tomorrow Setup and stores the prediction before
  the next session so it can be graded against the actual result.
- Finds Keepa toy leads and watches multiple Amazon storefronts while sharing
  one Keepa token gate.

## Tomorrow Setup commands

- `!tomorrow` — build and save the next-session bias, probability, signals,
  catalysts, confirmation, and invalidation rules.
- `!reviewsetup [yes|no] [lesson]` — grade the oldest open setup using the
  current ES change. Use `yes` if the original setup was invalidated.
- `!journal` — show the current unreviewed setup or journal statistics.
- `!tomorrow stats` — directional accuracy, average probability, invalidation
  rate, and calibration gap for up to 60 graded observations.

The automatic setup defaults to 5:30 PM Pacific on weekdays and posts to
`#tomorrow-setup`. It captures an opening snapshot at 6:35 AM Pacific. At 1:15
PM Pacific, it records the ES result and posts the review automatically. It stores data in
`data/prediction_journal.db`.

## Keepa commands

- `!amazonleads` / `!keepaleads` — scanner status.
- `!amazonleads now` — run a lead scan.
- `!storefront add <URL or seller ID>` — watch another seller.
- `!storefront list` — seller health and destination channels.
- `!storefront scan` — scan immediately.
- `!storefront remove <seller ID>` — stop watching a seller.

Default lead criteria now target at least 40% ROI, a preferred 50% ROI, rank
1–150,000, at least 10 rank drops in 30 days, 30 monthly sales, and 3–20 new
offers. These remain discovery estimates; eligibility and exact Amazon fees
must be checked before purchasing.

`STOREFRONT_BASELINE_ON_ADD=false` backfills a storefront once and then posts
new or relisted ASINs. Set it to `true` to treat the existing catalog as a
baseline and alert only on later additions.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python bot.py
```

Keep `.env` private. On Railway, mount a persistent volume at `/app/data`.
Only one running bot instance should use the Discord token.

## Tests

```bash
pip install pytest
pytest -q
```

GitHub Actions runs these tests for pull requests and pushes to `main`.
