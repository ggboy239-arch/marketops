from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands


VERSION = "MarketOps v2.8"


class MarketCalendar(commands.Cog):
    """Market calendar helper for scheduled market-moving events.

    Plain English: this posts a calendar checklist for Fed events, inflation data,
    jobs reports, Treasury events, and White House/president schedule items.
    """

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="calendar", aliases=["marketcalendar", "cal", "calendarhelp"])
    async def calendar_prefix(self, ctx):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a MarketOps admin can post the market calendar helper.")
            return

        now_pt = datetime.now(ZoneInfo("America/Los_Angeles"))
        now_et = datetime.now(ZoneInfo("America/New_York"))

        embed = discord.Embed(
            title="🗓️ MarketOps Calendar Watch",
            description=(
                "Use this channel to track scheduled events that can move stocks, yields, oil, gold, and crypto.\n\n"
                "Pin this message so admins know what to check before market open and during the day."
            ),
            color=discord.Color.blue(),
        )

        embed.add_field(
            name="Current Time",
            value=f"PT: `{now_pt.strftime('%a %b %d, %Y %I:%M %p')}`\nET: `{now_et.strftime('%a %b %d, %Y %I:%M %p')}`",
            inline=False,
        )

        embed.add_field(
            name="Daily Checks",
            value=(
                "• Fed speakers / Fed calendar\n"
                "• FOMC dates and meeting minutes\n"
                "• CPI, PPI, jobs, unemployment, retail sales\n"
                "• Treasury auctions and bond/yield events\n"
                "• White House / president public schedule\n"
                "• Oil/OPEC, war, sanctions, China/Taiwan, Russia/Ukraine, Middle East\n"
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
                "Economic Calendar / BLS CPI Jobs Data:\n"
                "https://www.bls.gov/schedule/news_release/\n\n"
                "White House Briefing Room:\n"
                "https://www.whitehouse.gov/briefing-room/"
            ),
            inline=False,
        )

        embed.add_field(
            name="How To Post Events Here",
            value=(
                "Use this format:\n\n"
                "`DATE / TIME ET — EVENT — WHY IT MATTERS — WATCH: SPY, QQQ, VIX, DXY, 10Y, Oil, BTC`\n\n"
                "Example:\n"
                "`Tue 10:00 AM ET — Fed Chair speaks — Rates/yields risk — Watch QQQ, VIX, 10Y`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Risk Labels",
            value=(
                "🟢 Low = not likely to move market much\n"
                "🟡 Medium = could move certain sectors\n"
                "🔴 High = CPI/FOMC/jobs/Fed Chair/major geopolitical event"
            ),
            inline=False,
        )

        embed.set_footer(text=f"Admin calendar helper • {VERSION}")
        await ctx.send(embed=embed)

    def _is_admin(self, ctx):
        if ctx.guild is None:
            return False
        permissions = getattr(ctx.author, "guild_permissions", None)
        return bool(permissions and permissions.administrator)


async def setup(bot):
    await bot.add_cog(MarketCalendar(bot))
