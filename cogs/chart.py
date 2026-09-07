import asyncio
from io import BytesIO

import discord
from discord.ext import commands

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import pandas as pd
import yfinance as yf

from market.market_service import MarketService


VERSION = "MarketOps v2.9.4"


class Chart(commands.Cog):
    """Candlestick charts and fast market pulse.

    Plain English: this turns MarketOps from just headlines into price action.
    Public charts go in #market-charts. Private per-user charts use !mychart and
    are sent by DM so everyone is not forced to see the same ticker request.
    """

    PERIODS = {
        "1d": {"period": "1d", "interval": "5m", "label": "1 day / 5 minute candles"},
        "5d": {"period": "5d", "interval": "15m", "label": "5 days / 15 minute candles"},
        "1mo": {"period": "1mo", "interval": "1d", "label": "1 month / daily candles"},
        "3mo": {"period": "3mo", "interval": "1d", "label": "3 months / daily candles"},
        "6mo": {"period": "6mo", "interval": "1d", "label": "6 months / daily candles"},
        "1y": {"period": "1y", "interval": "1wk", "label": "1 year / weekly candles"},
    }

    SYMBOL_ALIASES = {
        "GOLD": "GC=F",
        "GC": "GC=F",
        "OIL": "CL=F",
        "WTI": "CL=F",
        "BTC": "BTC-USD",
        "BITCOIN": "BTC-USD",
        "ETH": "ETH-USD",
        "ES": "ES=F",
        "SPX": "ES=F",
        "SP500": "ES=F",
        "S&P": "ES=F",
        "NQ": "NQ=F",
        "NASDAQ": "NQ=F",
        "VIX": "^VIX",
        "DXY": "DX-Y.NYB",
        "US10Y": "^TNX",
        "10Y": "^TNX",
    }

    def __init__(self, bot):
        self.bot = bot
        self.market = MarketService()

    @commands.command(name="chart", aliases=["charts", "candlechart"])
    async def chart_prefix(self, ctx, symbol: str = "SPY", period: str = "5d"):
        """Public chart. Everyone in #market-charts can see it."""
        try:
            result = await asyncio.to_thread(self._build_chart, symbol, period, private=False)
            if not result.get("ok"):
                await ctx.send(result.get("message", "⚠️ Could not build that chart."))
                return

            file = discord.File(result["image"], filename=result["filename"])
            try:
                await ctx.send(
                    content=result["mobile_text"],
                    embed=result["embed"],
                    file=file,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.Forbidden:
                await ctx.send(
                    "⚠️ I built the chart, but Discord blocked me from posting the image. "
                    "In `#market-charts`, turn ON **Attach Files**, **Embed Links**, **Send Messages**, and **Read Message History** for the MarketOps Bot role."
                )
            except discord.HTTPException as error:
                print(f"❌ Discord could not upload chart image: {error}")
                await ctx.send("⚠️ I built the chart, but Discord could not upload the image file. Check bot/channel Attach Files permission.")
        except Exception as error:
            print(f"❌ !chart error: {error!r}")
            await ctx.send("⚠️ MarketOps had trouble building that chart. Check the terminal for the error.")

    @commands.command(name="mychart", aliases=["privatechart", "dmchart"])
    async def mychart_prefix(self, ctx, symbol: str = "SPY", period: str = "5d"):
        """Private chart. Sends the candlestick chart to the requester by DM."""
        try:
            result = await asyncio.to_thread(self._build_chart, symbol, period, private=True)
            if not result.get("ok"):
                await ctx.send(result.get("message", "⚠️ Could not build that chart."))
                return

            file = discord.File(result["image"], filename=result["filename"])
            try:
                await ctx.author.send(
                    content=result["mobile_text"],
                    embed=result["embed"],
                    file=file,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                await ctx.send(f"✅ Sent your private `{result['symbol']}` candlestick chart to your DMs.")
            except discord.Forbidden:
                await ctx.send(
                    "⚠️ I could not DM you. Turn on DMs for this server, or use `!chart SYMBOL PERIOD` in `#market-charts`."
                )
        except Exception as error:
            print(f"❌ !mychart error: {error!r}")
            await ctx.send("⚠️ MarketOps had trouble building your private chart. Check the terminal for the error.")

    @commands.command(name="candles", aliases=["candlehelp", "ohlc"])
    async def candles_prefix(self, ctx):
        await ctx.send(embed=self._candles_help_embed())

    @commands.command(name="pulse", aliases=["fastmarket", "marketpulse"])
    async def pulse_prefix(self, ctx):
        try:
            dashboard = await asyncio.to_thread(self.market.get_dashboard)
            await ctx.send(embed=self._pulse_embed(dashboard))
        except Exception as error:
            print(f"❌ !pulse error: {error!r}")
            await ctx.send("⚠️ MarketOps had trouble building the fast pulse. Check the terminal for the error.")

    def _build_chart(self, raw_symbol, raw_period, private=False):
        symbol = self._normalize_symbol(raw_symbol)
        period_key = (raw_period or "5d").strip().lower()
        settings = self.PERIODS.get(period_key)
        if settings is None:
            valid = ", ".join(self.PERIODS.keys())
            return {"ok": False, "message": f"⚠️ Use a period like `{valid}`. Example: `!chart TSLA 5d`."}

        ticker = yf.Ticker(symbol)
        history = ticker.history(
            period=settings["period"],
            interval=settings["interval"],
            prepost=True,
            auto_adjust=False,
        )

        if history is None or history.empty:
            return {"ok": False, "message": f"⚠️ No chart data found for `{symbol}`."}

        history = self._clean_history(history).tail(80)
        if history.empty:
            return {"ok": False, "message": f"⚠️ No usable OHLC candles found for `{symbol}`."}

        latest = history.iloc[-1]
        previous = history.iloc[-2] if len(history) >= 2 else latest
        candle = self._read_candle(latest)
        previous_close = self._safe_float(previous.get("Close")) or candle["open"]
        change = candle["close"] - previous_close
        change_percent = (change / previous_close * 100) if previous_close else 0

        image = self._make_candle_image(history, symbol, settings["label"])
        embed = self._chart_embed(symbol, settings["label"], candle, change, change_percent, len(history), private)
        mobile_text = self._mobile_text(symbol, candle, change_percent, private)

        return {
            "ok": True,
            "symbol": symbol,
            "image": image,
            "filename": f"marketops_{self._filename_symbol(symbol)}_{period_key}.png",
            "embed": embed,
            "mobile_text": mobile_text,
        }

    def _clean_history(self, history):
        if isinstance(history.columns, pd.MultiIndex):
            history.columns = history.columns.get_level_values(0)
        required = ["Open", "High", "Low", "Close"]
        for column in required:
            if column not in history.columns:
                return pd.DataFrame()
        return history[required].dropna()

    def _make_candle_image(self, history, symbol, label):
        fig, ax = plt.subplots(figsize=(10, 5))
        width = 0.62

        for index, (_, row) in enumerate(history.iterrows()):
            open_price = float(row["Open"])
            high_price = float(row["High"])
            low_price = float(row["Low"])
            close_price = float(row["Close"])
            color = "green" if close_price >= open_price else "red"

            ax.vlines(index, low_price, high_price, linewidth=1, color=color)
            lower = min(open_price, close_price)
            height = abs(close_price - open_price)
            if height <= 0:
                ax.hlines(close_price, index - width / 2, index + width / 2, linewidth=1.2, color=color)
            else:
                ax.add_patch(
                    Rectangle(
                        (index - width / 2, lower),
                        width,
                        height,
                        facecolor=color,
                        edgecolor=color,
                        alpha=0.75,
                    )
                )

        ax.set_title(f"MarketOps Candlestick Chart — {symbol} ({label})")
        ax.set_ylabel("Price")
        ax.grid(True, alpha=0.25)
        ax.set_xlim(-1, len(history))

        step = max(1, len(history) // 6)
        ticks = list(range(0, len(history), step))
        labels = []
        for tick in ticks:
            index_value = history.index[tick]
            try:
                labels.append(index_value.strftime("%m/%d %H:%M"))
            except Exception:
                labels.append(str(index_value)[:10])
        ax.set_xticks(ticks)
        ax.set_xticklabels(labels, rotation=30, ha="right")

        fig.tight_layout()
        output = BytesIO()
        fig.savefig(output, format="png", dpi=140)
        plt.close(fig)
        output.seek(0)
        return output

    def _chart_embed(self, symbol, period_label, candle, change, change_percent, candle_count, private=False):
        candle_color = self._candle_color(candle)
        upper_wick = candle["high"] - max(candle["open"], candle["close"])
        lower_wick = min(candle["open"], candle["close"]) - candle["low"]
        body = abs(candle["close"] - candle["open"])

        title_prefix = "🔒 Private" if private else "📈 MarketOps"
        embed = discord.Embed(
            title=f"{title_prefix} Chart — {symbol}",
            description=f"Candlestick chart with open/high/low/close explanation. Period: **{period_label}**.",
            color=discord.Color.green() if candle_color == "Green" else discord.Color.red() if candle_color == "Red" else discord.Color.gold(),
        )
        embed.add_field(
            name="Latest Candle OHLC",
            value=(
                f"Open: **{self._money(candle['open'])}**\n"
                f"High: **{self._money(candle['high'])}**\n"
                f"Low: **{self._money(candle['low'])}**\n"
                f"Close: **{self._money(candle['close'])}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="Move",
            value=(
                f"Change vs prior candle: **{change:+.2f}** / **{change_percent:+.2f}%**\n"
                f"Candle: **{candle_color}**\n"
                f"Candles shown: **{candle_count}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="Body + Wicks",
            value=(
                f"Body size: **{body:.2f}**\n"
                f"Upper wick: **{upper_wick:.2f}**\n"
                f"Lower wick: **{lower_wick:.2f}**"
            ),
            inline=False,
        )
        embed.add_field(name="Candle Read", value=self._candle_read(candle, body, upper_wick, lower_wick), inline=False)
        embed.add_field(
            name="Next Check",
            value="Compare this with news, calendar risk, volume, support/resistance, and whether the next candle confirms or rejects the move.",
            inline=False,
        )
        embed.set_footer(text=f"Candles are educational, not financial advice • {VERSION}")
        return embed

    def _candles_help_embed(self):
        embed = discord.Embed(
            title="🕯️ Candlestick Basics — Open / High / Low / Close",
            description="Use this before reading `!chart TSLA`, `!charts TSLA`, `!mychart TSLA`, `!chart SPY`, or `!chart GC=F`.",
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="OHLC",
            value=(
                "**Open** = first price of that candle.\n"
                "**High** = highest price reached.\n"
                "**Low** = lowest price reached.\n"
                "**Close** = final price of that candle."
            ),
            inline=False,
        )
        embed.add_field(
            name="Body",
            value=(
                "The body is the thick part between open and close.\n"
                "Green body = close finished above open, buyers won that candle.\n"
                "Red body = close finished below open, sellers won that candle."
            ),
            inline=False,
        )
        embed.add_field(
            name="Wicks",
            value=(
                "Upper wick = price went higher, then got pushed back down.\n"
                "Lower wick = price went lower, then buyers pushed it back up.\n"
                "Big wick means rejection. Big body means control."
            ),
            inline=False,
        )
        embed.add_field(
            name="Public vs Private",
            value=(
                "`!chart TSLA 5d` or `!charts TSLA 5d` posts publicly in `#market-charts`.\n"
                "`!mychart TSLA 5d` sends the chart to your DMs so each user gets their own chart privately."
            ),
            inline=False,
        )
        embed.add_field(
            name="How To Use It",
            value=(
                "One candle alone is not enough. Check the last few candles, trend direction, news, calendar risk, and whether the next candle confirms.\n\n"
                "Examples: `!chart TSLA 1d`, `!charts QQQ 5d`, `!mychart QQQ 5d`, `!chart GC=F 1mo`, `!pulse`."
            ),
            inline=False,
        )
        embed.set_footer(text=VERSION)
        return embed

    def _pulse_embed(self, dashboard):
        assets = dashboard.get("assets", {})
        embed = discord.Embed(
            title="⚡ MarketOps Fast Pulse",
            description="Fast shared snapshot. Use this to decide what deserves a live chart check.",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="Mood",
            value=f"**{dashboard.get('risk', 'Unknown')}** — Score **{dashboard.get('score', 'N/A')}/100** — {dashboard.get('theme', 'No theme')}",
            inline=False,
        )
        lines = []
        for key, label in [
            ("market", "S&P Futures"),
            ("tech", "Nasdaq Futures"),
            ("fear", "VIX"),
            ("oil", "Oil"),
            ("gold", "Gold"),
            ("dollar", "DXY"),
            ("rates", "US10Y"),
            ("bitcoin", "Bitcoin"),
        ]:
            text = assets.get(key, "Unavailable")
            compact = " / ".join(line.replace("**", "") for line in str(text).splitlines()[1:3])
            lines.append(f"• **{label}:** {compact or text}")
        embed.add_field(name="Snapshot", value="\n".join(lines)[:1024], inline=False)
        embed.add_field(name="Use Next", value="`!mychart SPY 1d` / `!mychart QQQ 1d` / `!chart GC=F 5d` / `!news post`", inline=False)
        embed.set_footer(text=f"Updated {dashboard.get('updated', 'Unknown')} PT • {VERSION}")
        return embed

    def _read_candle(self, row):
        return {
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
        }

    def _candle_color(self, candle):
        if candle["close"] > candle["open"]:
            return "Green"
        if candle["close"] < candle["open"]:
            return "Red"
        return "Doji / Flat"

    def _candle_read(self, candle, body, upper_wick, lower_wick):
        color = self._candle_color(candle)
        if color == "Green" and body > upper_wick and body > lower_wick:
            return "Buyers controlled this candle because price closed above the open and the body is bigger than the wicks."
        if color == "Red" and body > upper_wick and body > lower_wick:
            return "Sellers controlled this candle because price closed below the open and the body is bigger than the wicks."
        if upper_wick > body * 1.5 and upper_wick > lower_wick:
            return "Price pushed higher but got rejected. Sellers or profit-taking showed up near the top of the candle."
        if lower_wick > body * 1.5 and lower_wick > upper_wick:
            return "Price pushed lower but buyers defended it. This can show demand near the lower price area."
        return "Mixed candle. Do not read it alone. Wait for the next candle and compare with trend, volume, and news."

    def _mobile_text(self, symbol, candle, change_percent, private=False):
        privacy = "Private" if private else "Public"
        color = self._candle_color(candle)
        return f"📈 MarketOps {privacy} Chart: {symbol} — Close {self._money(candle['close'])} — {change_percent:+.2f}% — {color} candle"

    def _normalize_symbol(self, value):
        clean = (value or "SPY").strip().upper().replace("$", "")
        return self.SYMBOL_ALIASES.get(clean, clean)

    def _money(self, value):
        return f"${value:,.2f}"

    def _safe_float(self, value):
        try:
            return float(value)
        except Exception:
            return None

    def _filename_symbol(self, symbol):
        return symbol.replace("=", "").replace("^", "").replace("-", "_").replace(".", "_")


async def setup(bot):
    await bot.add_cog(Chart(bot))