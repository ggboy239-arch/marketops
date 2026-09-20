# Toy trend and Amazon stock-pressure monitoring

MarketOps can keep early toy-demand headlines separate from confirmed Keepa
candidates. Create a Discord channel such as `#toy-trends`, give the bot View
Channel, Send Messages, and Embed Links, then add these Railway variables:

```env
TOY_TRENDS_CHANNEL_ID=your_discord_channel_id
TOY_TRENDS_CHECK_MINUTES=30
TOY_TRENDS_LOOKBACK=7d
TOY_YOUTUBE_FEEDS=
AMAZON_LEADS_NEW_LISTING_DAYS=45
AMAZON_LEADS_QUICK_SELLOUT_DAYS=7
```

`TOY_YOUTUBE_FEEDS` is optional. It accepts comma-separated public YouTube RSS
channel-feed URLs. Use `!toytrends now` for an immediate scan or `!toytrends`
for status. Headlines are posted as watch signals only. The Amazon lead scanner
must still confirm the exact ASIN, rank momentum, Amazon stock cycling, price
expansion, seller trend, and a real source price before a candidate is treated
as profitable.

The Amazon scanner also has a **Quick Sellout** review type. It looks for a
recently listed toy ASIN that Amazon stocked and then sold out within seven
days. It accepts lighter early velocity because new releases do not yet have
complete 30/90-day history, but it never labels the item profitable without a
verified source cost.
