# Toy trend and Amazon stock-pressure monitoring

MarketOps can keep early toy-demand headlines separate from confirmed Keepa
candidates. Create a Discord channel such as `#toy-trends`, give the bot View
Channel, Send Messages, and Embed Links, then add these Railway variables:

```env
TOY_TRENDS_CHANNEL_ID=your_discord_channel_id
TOY_TRENDS_CHECK_MINUTES=30
TOY_TRENDS_LOOKBACK=7d
TOY_YOUTUBE_FEEDS=
```

`TOY_YOUTUBE_FEEDS` is optional. It accepts comma-separated public YouTube RSS
channel-feed URLs. Use `!toytrends now` for an immediate scan or `!toytrends`
for status. Headlines are posted as watch signals only. The Amazon lead scanner
must still confirm the exact ASIN, rank momentum, Amazon stock cycling, price
expansion, seller trend, and a real source price before a candidate is treated
as profitable.
