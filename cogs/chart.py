import asyncio
from io import BytesIO

import discord
from discord.ext import commands

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter
import pandas as pd
import yfinance as yf

from market.market_service import MarketService


VERSION = "MarketOps v2.9.5"


class Chart(commands.Cog):
    """Candlestick charts and fast market pulse.

    Plain English: public charts go in #market-charts. Private per-user charts
    use !mychart and are sent by DM.
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

    GREEN = "#22c55e"
    RED = "#ef4444"
    GOLD = "#f59e0b"
    BLUE = "#38bdf8"
    BG = "#070b14"
    PANEL = "#0f172a"
    GRID = "#334155"
    TEXT = "#e5e7eb"
    MUTED = "#94a3b8"
    BORDER = "#1e293b"

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
                print(f"❌ Discord could not upload chart image: {error!r}")
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
                await ctx.send(f"✅ Sent your private `{result['symbol']}` premium chart to your DMs.")
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

        history = self._clean_history(history).tail(90)
        if history.empty:
            return {"ok": False, "message": f"⚠️ No usable OHLC candles found for `{symbol}`."}

        latest = history.iloc[-1]
        previous = history.iloc[-2] if len(history) >= 2 else latest
        candle = self._read_candle(latest)
        previous_close = self._safe_float(previous.get("Close")) or candle["open"]
        change = candle["close"] - previous_close
        change_percent = (change / previous_close * 100) if previous_close else 0

        image = self._make_candle_image(
            history=history,
            symbol=symbol,
            label=settings["label"],
            change_percent=change_percent,
        )
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

        keep = list(required)
        if "Volume" in history.columns:
            keep.append("Volume")

        clean = history[keep].dropna(subset=required).copy()
        if "Volume" not in clean.columns:
            clean["Volume"] = 0
        clean["Volume"] = clean["Volume"].fillna(0)
        return clean

    def _make_candle_image(self, history, symbol, label, change_percent):
        closes = history["Close"].astype(float)
        has_volume = "Volume" in history.columns and float(history["Volume"].fillna(0).sum()) > 0

        if has_volume:
            fig, (ax, volume_ax) = plt.subplots(
                2,
                1,
                figsize=(12.8, 7.2),
                sharex=True,
                gridspec_kw={"height_ratios": [4.2, 1.1], "hspace": 0.04},
            )
        else:
            fig, ax = plt.subplots(figsize=(12.8, 6.4))
            volume_ax = None

        fig.patch.set_facecolor(self.BG)
        ax.set_facecolor(self.PANEL)
        if volume_ax is not None:
            volume_ax.set_facecolor(self.PANEL)

        width = 0.62
        candle_colors = []

        for index, (_, row) in enumerate(history.iterrows()):
            open_price = float(row["Open"])
            high_price = float(row["High"])
            low_price = float(row["Low"])
            close_price = float(row["Close"])
            is_green = close_price >= open_price
            color = self.GREEN if is_green else self.RED
            candle_colors.append(color)

            ax.vlines(index, low_price, high_price, linewidth=1.35, color=color, alpha=0.95)
            lower = min(open_price, close_price)
            height = abs(close_price - open_price)

            if height <= 0:
                ax.hlines(close_price, index - width / 2, index + width / 2, linewidth=1.6, color=color)
            else:
                ax.add_patch(
                    Rectangle(
                        (index - width / 2, lower),
                        width,
                        height,
                        facecolor=color,
                        edgecolor=color,
                        alpha=0.88,
                        linewidth=0.8,
                    )
                )

        if len(closes) >= 9:
            ax.plot(range(len(history)), closes.rolling(9).mean(), color=self.BLUE, linewidth=1.45, alpha=0.95, label="MA 9")
        if len(closes) >= 21:
            ax.plot(range(len(history)), closes.rolling(21).mean(), color=self.GOLD, linewidth=1.45, alpha=0.95, label="MA 21")

        last_close = float(closes.iloc[-1])
        last_color = self.GREEN if change_percent >= 0 else self.RED
        ax.axhline(last_close, color=last_color, linewidth=1.0, linestyle="--", alpha=0.78)
        ax.text(
            len(history) + 0.15,
            last_close,
            f" {self._price(last_close)} ",
            va="center",
            ha="left",
            color=self.TEXT,
            fontsize=9,
            fontweight="bold",
            bbox={"boxstyle": "round,pad=0.25", "facecolor": last_color, "edgecolor": "none", "alpha": 0.95},
        )

        high_series = history["High"].astype(float)
        low_series = history["Low"].astype(float)
        high_pos = int(high_series.values.argmax())
        low_pos = int(low_series.values.argmin())
        high_value = float(high_series.iloc[high_pos])
        low_value = float(low_series.iloc[low_pos])
        price_range = max(high_value - low_value, max(abs(last_close) * 0.01, 1))

        ax.annotate(
            f"H {self._price(high_value)}",
            xy=(high_pos, high_value),
            xytext=(high_pos, high_value + price_range * 0.06),
            color=self.TEXT,
            fontsize=8,
            ha="center",
            arrowprops={"arrowstyle": "-", "color": self.MUTED, "lw": 0.8},
        )
        ax.annotate(
            f"L {self._price(low_value)}",
            xy=(low_pos, low_value),
            xytext=(low_pos, low_value - price_range * 0.08),
            color=self.TEXT,
            fontsize=8,
            ha="center",
            arrowprops={"arrowstyle": "-", "color": self.MUTED, "lw": 0.8},
        )

        if volume_ax is not None:
            volumes = history["Volume"].fillna(0).astype(float)
            for index, volume in enumerate(volumes):
                volume_ax.bar(index, volume, color=candle_colors[index], alpha=0.35, width=0.62)
            volume_ax.set_ylabel("VOL", color=self.MUTED, fontsize=8)
            volume_ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: self._short_number(y)))
            self._style_axis(volume_ax, show_x=True)
        else:
            self._style_axis(ax, show_x=True)

        self._style_axis(ax, show_x=False)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: self._price(y)))
        ax.yaxis.tick_right()
        ax.yaxis.set_label_position("right")
        ax.set_ylabel("PRICE", color=self.MUTED, fontsize=8)
        ax.set_xlim(-1, len(history) + 4)

        if ax.get_legend_handles_labels()[0]:
            legend = ax.legend(
                loc="upper left",
                frameon=True,
                facecolor=self.PANEL,
                edgecolor=self.BORDER,
                labelcolor=self.TEXT,
                fontsize=8,
            )
            legend.get_frame().set_alpha(0.65)

        target_ax = volume_ax if volume_ax is not None else ax
        self._set_time_labels(target_ax, history)

        close_color = self.GREEN if change_percent >= 0 else self.RED
        fig.text(0.04, 0.965, f"{symbol}  •  MARKETOPS PRO CHART", color=self.TEXT, fontsize=18, fontweight="bold")
        fig.text(
            0.04,
            0.928,
            f"{label}  •  Last {self._price(last_close)}  •  {change_percent:+.2f}%  •  MA 9 / MA 21  •  Volume",
            color=close_color,
            fontsize=10,
            fontweight="bold",
        )
        fig.text(
            0.04,
            0.025,
            "Candles: green closes above open, red closes below open. Use with news, volume, calendar risk, and confirmation.",
            color=self.MUTED,
            fontsize=8,
        )

        fig.subplots_adjust(top=0.88, bottom=0.13, left=0.055, right=0.92)

        output = BytesIO()
        fig.savefig(output, format="png", dpi=160, facecolor=fig.get_facecolor())
        plt.close(fig)
        output.seek(0)
        return output

    def _style_axis(self, ax, show_x):
        ax.grid(True, color=self.GRID, alpha=0.23, linewidth=0.75)
        ax.tick_params(axis="x", colors=self.MUTED, labelsize=8)
        ax.tick_params(axis="y", colors=self.MUTED, labelsize=8)
        for spine in ax.spines.values():
            spine.set_color(self.BORDER)
            spine.set_linewidth(0.8)
        if not show_x:
            ax.tick_params(labelbottom=False)

    def _set_time_labels(self, ax, history):
        step = max(1, len(history) // 7)
        ticks = list(range(0, len(history), step))
        if ticks and ticks[-1] != len(history) - 1:
            ticks.append(len(history) - 1)

        labels = []
        for tick in ticks:
            index_value = history.index[tick]
            try:
                labels.append(index_value.strftime("%m/%d %H:%M"))
            except Exception:
                labels.append(str(index_value)[:10])

        ax.set_xticks(ticks)
        ax.set_xticklabels(labels, rotation=0, ha="center", color=self.MUTED)

    def _chart_embed(self, symbol, period_label, candle, change, change_percent, candle_count, private=False):
        candle_color = self._candle_color(candle)
        upper_wick = candle["high"] - max(candle["open"], candle["close"])
        lower_wick = min(candle["open"], candle["close"]) - candle["low"]
        body = abs(candle["close"] - candle["open"])

        title_prefix = "🔒 Private" if private else "📈 MarketOps Pro"
        embed = discord.Embed(
            title=f"{title_prefix} Chart — {symbol}",
            description=f"Premium candlestick chart with volume, MA 9/21, last-price line, and high/low markers. Period: **{period_label}**.",
            color=discord.Color.green() if candle_color == "Green" else discord.Color.red() if candle_color == "Red" else discord.Color.gold(),
        )
        embed.add_field(
            name="Latest Candle",
            value=(
                f"Open **{self._price(candle['open'])}** • High **{self._price(candle['high'])}**\n"
                f"Low **{self._price(candle['low'])}** • Close **{self._price(candle['close'])}**"
            ),
            inline=False,
        )
        embed.add_field(
            name="Move",
            value=f"Prior-candle move: **{change:+.2f}** / **{change_percent:+.2f}%** • Candle: **{candle_color}** • Shown: **{candle_count}**",
            inline=False,
        )
        embed.add_field(
            name="Candle Read",
            value=self._candle_read(candle, body, upper_wick, lower_wick),
            inline=False,
        )
        embed.set_footer(text=f"Charts are educational, not financial advice • {VERSION}")
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
                "`!mychart TSLA 5d` sends the chart to your DMs."
            ),
            inline=False,
        )
        embed.add_field(
            name="How To Use It",
            value=(
                "One candle alone is not enough. Check trend, volume, news, calendar risk, and whether the next candle confirms.\n\n"
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
            return "Buyers controlled the latest candle: close finished above open and body is stronger than the wicks."
        if color == "Red" and body > upper_wick and body > lower_wick:
            return "Sellers controlled the latest candle: close finished below open and body is stronger than the wicks."
        if upper_wick > body * 1.5 and upper_wick > lower_wick:
            return "Price pushed higher but got rejected near the top. Watch for profit-taking or resistance."
        if lower_wick > body * 1.5 and lower_wick > upper_wick:
            return "Price pushed lower but buyers defended it. Watch for demand/support."
        return "Mixed candle. Do not read it alone. Wait for confirmation from the next candles, volume, and news."

    def _mobile_text(self, symbol, candle, change_percent, private=False):
        privacy = "Private" if private else "Public"
        color = self._candle_color(candle)
        return f"📈 MarketOps Pro {privacy} Chart: {symbol} — Close {self._price(candle['close'])} — {change_percent:+.2f}% — {color}"

    def _normalize_symbol(self, value):
        clean = (value or "SPY").strip().upper().replace("$", "")
        return self.SYMBOL_ALIASES.get(clean, clean)

    def _price(self, value):
        try:
            value = float(value)
        except Exception:
            return "N/A"
        if abs(value) >= 1000:
            return f"${value:,.0f}"
        return f"${value:,.2f}"

    def _short_number(self, value):
        try:
            value = float(value)
        except Exception:
            return "0"
        if abs(value) >= 1_000_000_000:
            return f"{value / 1_000_000_000:.1f}B"
        if abs(value) >= 1_000_000:
            return f"{value / 1_000_000:.1f}M"
        if abs(value) >= 1_000:
            return f"{value / 1_000:.0f}K"
        return f"{value:.0f}"

    def _safe_float(self, value):
        try:
            return float(value)
        except Exception:
            return None

    def _filename_symbol(self, symbol):
        return symbol.replace("=", "").replace("^", "").replace("-", "_").replace(".", "_")


async def setup(bot):
    await bot.add_cog(Chart(bot))
