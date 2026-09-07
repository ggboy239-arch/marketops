import os
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks


VERSION = "MarketOps v2.8.1"


class MarketCalendar(commands.Cog):
    """Market calendar helper for scheduled market-moving events.

    Plain English: this posts a calendar checklist for Fed events, inflation data,
    jobs reports, Treasury events, and White House/president schedule items.
    It can post automatically every morning and every Monday, and admins can
    still run the calendar commands manually whenever they want.
    """

    def __init__(self, bot):
        self.bot = bot
        self.channel_name = os.getenv("MARKETOPS_CALENDAR_CHANNEL", "market-calendar")
        self.auto_post = os.getenv("MARKETOPS_CALENDAR_AUTO_POST", "true").strip().lower() in {"1", "true", "yes", "on"}
        self.daily_time = os.getenv("MARKETOPS_CALENDAR_DAILY_PT", "05:15")
        self.weekly_time = os.getenv("MARKETOPS_CALENDAR_WEEKLY_PT", "05:20")
        self._last_daily_key = None
        self._last_weekly_key = None
        self.calendar_loop.start()

    def cog_unload(self):
        self.calendar_loop.cancel()

    @commands.command(name="calendar", aliases=["marketcalendar", "cal", "calendarhelp"])
    async def calendar_prefix(self, ctx):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a MarketOps admin can post the market calendar helper.")
            return
        await ctx.send(embed=self._calendar_embed("manual"))

    @commands.command(name="calendartoday", aliases=["todaycal", "todaycalendar"])
    async def calendartoday_prefix(self, ctx):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a MarketOps admin can post the daily calendar check.")
            return
        await ctx.send(embed=self._calendar_embed("daily"))

    @commands.command(name="calendarweek", aliases=["weekcal", "weeklycalendar"])
    async def calendarweek_prefix(self, ctx):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a MarketOps admin can post the weekly calendar check.")
            return
        await ctx.send(embed=self._calendar_embed("weekly"))

    @commands.command(name="calendarstatus", aliases=["calstatus"])
    async def calendarstatus_prefix(self, ctx):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a MarketOps admin can view calendar status.")
            return

        status = "ON" if self.auto_post else "OFF"
        embed = discord.Embed(
            title="🗓️ MarketOps Calendar Status",
            description="Automatic market-calendar posting settings.",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Auto Post", value=status, inline=True)
        embed.add_field(name="Channel", value=f"#{self.channel_name}", inline=True)
        embed.add_field(name="Daily PT", value=self.daily_time, inline=True)
        embed.add_field(name="Weekly PT", value=f"Monday {self.weekly_time}", inline=True)
        embed.add_field(name="Manual Commands", value="`!calendar`, `!calendartoday`, `!calendarweek`", inline=False)
        embed.set_footer(text=VERSION)
        await ctx.send(embed=embed)

    @commands.command(name="calendaron", aliases=["calon"])
    async def calendaron_prefix(self, ctx):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a MarketOps admin can turn calendar auto-post on.")
            return
        self.auto_post = True
        await ctx.send("✅ Market calendar auto-post is ON for this bot session.")

    @commands.command(name="calendaroff", aliases=["caloff"])
    async def calendaroff_prefix(self, ctx):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a MarketOps admin can turn calendar auto-post off.")
            return
        self.auto_post = False
        await ctx.send("🛑 Market calendar auto-post is OFF for this bot session.")

    @tasks.loop(seconds=30)
    async def calendar_loop(self):
        if not self.auto_post:
            return
        if not self.bot.guilds:
            return

        now_pt = datetime.now(ZoneInfo("America/Los_Angeles"))
        current_time = now_pt.strftime("%H:%M")
        today_key = now_pt.strftime("%Y-%m-%d")
        week_key = now_pt.strftime("%G-W%V")

        for guild in self.bot.guilds:
            channel = self._find_text_channel(guild, self.channel_name)
            if channel is None:
                continue

            if current_time == self.daily_time and self._last_daily_key != today_key:
                self._last_daily_key = today_key
                await channel.send(embed=self._calendar_embed("daily"))

            if now_pt.weekday() == 0 and current_time == self.weekly_time and self._last_weekly_key != week_key:
                self._last_weekly_key = week_key
                await channel.send(embed=self._calendar_embed("weekly"))

    @calendar_loop.before_loop
    async def before_calendar_loop(self):
        await self.bot.wait_until_ready()

    def _calendar_embed(self, mode="manual"):
        now_pt = datetime.now(ZoneInfo("America/Los_Angeles"))
        now_et = datetime.now(ZoneInfo("America/New_York"))

        if mode == "daily":
            title = "🗓️ MarketOps Daily Calendar Check"
            description = "Auto-posted daily checklist for scheduled events that can move the market."
        elif mode == "weekly":
            title = "🗓️ MarketOps Weekly Calendar Check"
            description = "Auto-posted weekly checklist for scheduled market-moving events."
        else:
            title = "🗓️ MarketOps Calendar Watch"
            description = "Manual calendar helper for scheduled events that can move stocks, yields, oil, gold, and crypto."

        embed = discord.Embed(title=title, description=description, color=discord.Color.blue())

        embed.add_field(
            name="Current Time",
            value=f"PT: `{now_pt.strftime('%a %b %d, %Y %I:%M %p')}`\nET: `{now_et.strftime('%a %b %d, %Y %I:%M %p')}`",
            inline=False,
        )

        if mode == "weekly":
            embed.add_field(
                name="This Week — High Impact Checks",
                value=(
                    "🔴 FOMC decision, minutes, Fed Chair speech, CPI, PPI, jobs report, unemployment, major Treasury events\n"
                    "🟡 Fed speakers, retail sales, GDP, PCE inflation, oil/OPEC events, major earnings\n"
                    "🟢 Normal speeches or low-impact releases unless headlines change"
                ),
                inline=False,
            )
        else:
            embed.add_field(
                name="Today — What To Check",
                value=(
                    "• Fed speakers / Fed calendar\n"
                    "• FOMC dates, minutes, and Fed Chair remarks\n"
                    "• CPI, PPI, PCE, jobs, unemployment, retail sales\n"
                    "• Treasury auctions, yields, DXY, and bond-market events\n"
                    "• White House / president public schedule and policy remarks\n"
                    "• Oil/OPEC, sanctions, China/Taiwan, Russia/Ukraine, Middle East\n"
                    "• Major earnings: NVDA, AMD, TSLA, AAPL, MSFT, AMZN, META, GOOGL"
                ),
                inline=False,
            )

        embed.add_field(
            name="Official Sources To Check",
            value=(
                "Federal Reserve Calendar:\n"
                "https://www.federalreserve.gov/newsevents/calendar.htm\n\n"
                "FOMC Calendar:\n"
                "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm\n\n"
                "BLS CPI / Jobs Release Schedule:\n"
                "https://www.bls.gov/schedule/news_release/\n\n"
                "White House Briefing Room:\n"
                "https://www.whitehouse.gov/briefing-room/"
            ),
            inline=False,
        )

        embed.add_field(
            name="Market Watch List",
            value="Watch: `SPY`, `QQQ`, `VIX`, `DXY`, `10Y`, `Oil`, `Gold`, `BTC`, `NVDA`, `AMD`, `TSLA`",
            inline=False,
        )

        embed.add_field(
            name="How To Post A Found Event",
            value=(
                "Use this format if you manually add something:\n"
                "`DATE / TIME ET — EVENT — WHY IT MATTERS — WATCH: SPY, QQQ, VIX, DXY, 10Y, Oil, BTC`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Manual Commands",
            value="`!calendar` • `!calendartoday` • `!calendarweek` • `!calendarstatus` • `!calendaron` • `!calendaroff`",
            inline=False,
        )

        embed.set_footer(text=f"Auto calendar helper • {VERSION}")
        return embed

    def _is_admin(self, ctx):
        if ctx.guild is None:
            return False
        permissions = getattr(ctx.author, "guild_permissions", None)
        return bool(permissions and permissions.administrator)

    def _find_text_channel(self, guild, target_name):
        target = self._clean_channel_name(target_name)
        for channel in guild.text_channels:
            if self._clean_channel_name(channel.name).endswith(target):
                return channel
        return None

    def _clean_channel_name(self, channel_name):
        cleaned = (channel_name or "").strip().lower()
        for separator in ("|", "┃", "│"):
            if separator in cleaned:
                cleaned = cleaned.split(separator)[-1].strip()
        while cleaned and not cleaned[0].isalnum():
            cleaned = cleaned[1:].strip()
        return cleaned.replace(" ", "-")


async def setup(bot):
    await bot.add_cog(MarketCalendar(bot))
