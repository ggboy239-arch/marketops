import asyncio
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from market.market_service import MarketService
from market.prediction_journal import PredictionJournal
from market.tomorrow_setup_engine import TomorrowSetupEngine


class TomorrowSetup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.engine = TomorrowSetupEngine()
        self.journal = PredictionJournal()
        self.market = MarketService()
        self.channel_name = os.getenv("TOMORROW_SETUP_CHANNEL", "tomorrow-setup").strip()
        self.post_time = os.getenv("TOMORROW_SETUP_TIME_PT", "17:30").strip()
        self.review_time = os.getenv("TOMORROW_REVIEW_TIME_PT", "13:15").strip()
        self.open_time = os.getenv("TOMORROW_OPEN_CAPTURE_TIME_PT", "06:35").strip()
        self.auto_post = os.getenv("TOMORROW_SETUP_AUTO_POST", "true").lower() in {"1", "true", "yes", "on"}
        self.last_posted_date = None
        if self.auto_post:
            self.scheduler.start()
            self.open_scheduler.start()
            self.review_scheduler.start()

    def cog_unload(self):
        if self.scheduler.is_running():
            self.scheduler.cancel()
        if self.review_scheduler.is_running():
            self.review_scheduler.cancel()
        if self.open_scheduler.is_running():
            self.open_scheduler.cancel()

    @commands.command(name="tomorrow", aliases=["tomorrowsetup", "nextday"])
    async def tomorrow(self, ctx, action="now"):
        action = action.lower()
        if action in {"stats", "accuracy"}:
            await ctx.send(embed=self._stats_embed())
            return
        setup = await asyncio.to_thread(self.engine.build)
        saved = self.journal.save_setup(setup)
        await ctx.send(embed=self._setup_embed(saved), allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="reviewsetup", aliases=["reviewtomorrow", "setupreview"])
    async def review_setup(self, ctx, invalidated: str = "no", *, lesson: str = None):
        open_item = self.journal.latest_open()
        if not open_item:
            await ctx.send("There is no unreviewed Tomorrow Setup.")
            return
        dashboard = await asyncio.to_thread(self.market.get_dashboard)
        raw = dashboard.get("raw", {})
        actual_change = raw.get("market", {}).get("change_percent")
        if actual_change is None:
            await ctx.send("⚠️ No fresh ES result is available yet; the setup was not graded.")
            return
        was_invalidated = invalidated.lower() in {"yes", "y", "true", "1", "invalidated"}
        reviewed = self.journal.review(
            open_item["session_date"], raw, actual_change, was_invalidated,
            "Marked through Discord review" if was_invalidated else None, lesson,
        )
        await ctx.send(embed=self._review_embed(reviewed))

    @commands.command(name="journal", aliases=["predictionjournal"])
    async def journal_command(self, ctx):
        latest = self.journal.latest_open()
        if latest:
            await ctx.send(embed=self._setup_embed(latest))
        else:
            await ctx.send(embed=self._stats_embed())

    @tasks.loop(seconds=30)
    async def scheduler(self):
        await self.bot.wait_until_ready()
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        if now.weekday() >= 5 or now.strftime("%H:%M") != self.post_time:
            return
        today = now.strftime("%Y-%m-%d")
        if self.last_posted_date == today:
            return
        setup = await asyncio.to_thread(self.engine.build)
        saved = self.journal.save_setup(setup)
        for guild in self.bot.guilds:
            channel = discord.utils.find(lambda c: c.name.lower().endswith(self.channel_name.lower()), guild.text_channels)
            if channel:
                await channel.send(embed=self._setup_embed(saved), allowed_mentions=discord.AllowedMentions.none())
        self.last_posted_date = today

    @scheduler.before_loop
    async def before_scheduler(self):
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=30)
    async def open_scheduler(self):
        await self.bot.wait_until_ready()
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        if now.weekday() >= 5 or now.strftime("%H:%M") != self.open_time:
            return
        item = self.journal.latest_open()
        if not item or item["session_date"] != now.strftime("%Y-%m-%d") or item.get("open_snapshot"):
            return
        dashboard = await asyncio.to_thread(self.market.get_dashboard)
        self.journal.capture_open(item["session_date"], dashboard.get("raw", {}))

    @open_scheduler.before_loop
    async def before_open_scheduler(self):
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=30)
    async def review_scheduler(self):
        await self.bot.wait_until_ready()
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        if now.weekday() >= 5 or now.strftime("%H:%M") != self.review_time:
            return
        item = self.journal.latest_open()
        if not item or item["session_date"] != now.strftime("%Y-%m-%d"):
            return
        dashboard = await asyncio.to_thread(self.market.get_dashboard)
        raw = dashboard.get("raw", {})
        actual_change = raw.get("market", {}).get("change_percent")
        if actual_change is None:
            return
        reviewed = self.journal.review(item["session_date"], raw, actual_change)
        for guild in self.bot.guilds:
            channel = discord.utils.find(lambda c: c.name.lower().endswith(self.channel_name.lower()), guild.text_channels)
            if channel:
                await channel.send(embed=self._review_embed(reviewed), allowed_mentions=discord.AllowedMentions.none())

    @review_scheduler.before_loop
    async def before_review_scheduler(self):
        await self.bot.wait_until_ready()

    def _setup_embed(self, setup):
        color = discord.Color.green() if setup["bias"] == "Bullish" else discord.Color.red() if setup["bias"] == "Bearish" else discord.Color.gold()
        embed = discord.Embed(
            title=f"Tomorrow Setup • {setup['session_date']}",
            description=f"Bias: **{setup['bias']}** • Probability: **{setup['probability']}%** • Risk score: **{setup['risk_score']}/100**",
            color=color,
        )
        embed.add_field(name="Signals", value=self._signals(setup.get("signals", {})), inline=False)
        embed.add_field(name="Why", value=self._list(setup.get("reasons")), inline=False)
        embed.add_field(name="Catalysts", value=self._list(setup.get("catalysts")), inline=False)
        embed.add_field(name="Confirmation", value=self._list(setup.get("confirmation")), inline=False)
        embed.add_field(name="Invalidation", value=self._list(setup.get("invalidation")), inline=False)
        embed.add_field(name="Expected vs. actual", value="The journal will grade the market reaction—not whether a headline sounded good or bad.", inline=False)
        embed.set_footer(text="Probability, not certainty • Saved to prediction journal")
        return embed

    def _review_embed(self, item):
        result = "Correct" if item["direction_correct"] else "Incorrect"
        embed = discord.Embed(title=f"Setup Review • {item['session_date']}", color=discord.Color.blurple())
        embed.add_field(name="Prediction", value=f"{item['bias']} at {item['probability']}%", inline=True)
        embed.add_field(name="Actual", value=f"{item['actual_outcome']} ({item['actual_change']:+.2f}%)", inline=True)
        embed.add_field(name="Result", value=result, inline=True)
        embed.add_field(name="Invalidated", value="Yes" if item["invalidated"] else "No", inline=True)
        if item.get("lesson"):
            embed.add_field(name="Lesson", value=item["lesson"][:1000], inline=False)
        return embed

    def _stats_embed(self):
        stats = self.journal.statistics()
        embed = discord.Embed(title="Prediction Journal", color=discord.Color.blue())
        if not stats["count"]:
            embed.description = "No graded setups yet. Build a setup with `!tomorrow`."
            return embed
        embed.description = f"Last **{stats['count']}** graded setups"
        embed.add_field(name="Directional accuracy", value=f"{stats['accuracy']}%", inline=True)
        embed.add_field(name="Average probability", value=f"{stats['avg_confidence']}%", inline=True)
        embed.add_field(name="Invalidation rate", value=f"{stats['invalidation_rate']}%", inline=True)
        embed.add_field(name="Calibration gap", value=f"{stats['calibration_gap']:+.1f} points", inline=True)
        return embed

    @staticmethod
    def _list(values):
        values = [str(value) for value in (values or []) if value]
        return "\n".join(f"• {value}" for value in values[:6]) or "No clear signal"

    @staticmethod
    def _signals(signals):
        labels = {"market": "ES", "tech": "NQ", "fear": "VIX", "rates": "US10Y", "dollar": "DXY", "oil": "Oil", "gold": "Gold", "bitcoin": "BTC", "nikkei": "Nikkei", "hang_seng": "Hang Seng", "dax": "DAX", "ftse": "FTSE"}
        rows = []
        for key in ("market", "tech", "fear", "rates", "dollar", "oil", "gold", "bitcoin", "nikkei", "hang_seng", "dax", "ftse"):
            item = signals.get(key, {})
            change = item.get("change_percent")
            rows.append(f"**{labels[key]}:** {change:+.2f}%" if isinstance(change, (int, float)) else f"**{labels[key]}:** unavailable")
        return " • ".join(rows)


async def setup(bot):
    await bot.add_cog(TomorrowSetup(bot))
