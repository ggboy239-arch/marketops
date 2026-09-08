import discord
from discord.ext import commands


VERSION = "MarketOps v2.9.5"


class MarketOpsHelp(commands.Cog):
    """Short command guide for MarketOps."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="commands", aliases=["help", "cmds"])
    async def commands_prefix(self, ctx):
        await ctx.send(embed=self._build_help_embed())

    def _build_help_embed(self):
        embed = discord.Embed(
            title="🧭 MarketOps Command Guide",
            description="Quick cheat sheet for what to type and where to use it.",
            color=discord.Color.blue(),
        )

        embed.add_field(
            name="⚡ Fast Market / Charts",
            value=(
                "`!pulse` — shared fast snapshot → `#market-dashboard`\n"
                "`!market` — full dashboard with gold/oil/VIX/rates/BTC → `#market-dashboard`\n"
                "`!chart TSLA 5d` / `!charts TSLA 5d` — public candlestick chart → `#market-charts`\n"
                "`!mychart TSLA 5d` — private chart sent to your DMs → `#market-charts` or `#watchlist`\n"
                "`!chart QQQ 1d` — 1-day intraday candles\n"
                "`!chart GC=F 5d` — gold futures chart\n"
                "`!candles` — open/high/low/close lesson → `#market-school` or `#market-charts`"
            ),
            inline=False,
        )

        embed.add_field(
            name="🎓 Learning",
            value=(
                "`!learn` — detailed lesson based on current market setup → `#market-school`\n"
                "`!learn candles` — candlestick/OHLC lesson\n"
                "`!learn risk` — risk-on/risk-off lesson\n"
                "`!learn vix` — fear/VIX lesson\n"
                "`!learn rates` — 10Y/DXY/rates lesson\n"
                "`!learn gold` — gold/safety lesson\n"
                "`!learn news` — news vs price action lesson\n"
                "`!playbook` — full MarketOps checklist"
            ),
            inline=False,
        )

        embed.add_field(
            name="🌅 Brief",
            value=(
                "`!brief` — full market brief → `#morning-brief`\n"
                "`!brief schedule` — show auto-post settings and last error\n"
                "`!brief post` — test-send one brief into the configured brief channel"
            ),
            inline=False,
        )

        embed.add_field(
            name="🧠 OpenAI News for Me",
            value=(
                "`!policy` — create today's verified policy-to-market lesson → `#openai-news-for-me`\n"
                "`!policy post` — test-send a lesson into the personal channel\n"
                "`!policy status` — show schedule, OpenAI readiness, and last error\n"
                "Auto-post: weekdays at `05:30 PT`"
            ),
            inline=False,
        )

        embed.add_field(
            name="👤 Personal User Commands",
            value=(
                "`!redeem KEY-HERE` — unlock personal commands and auto-assign user role → `#redeem-access`\n"
                "`!profile` — show your setup → `#watchlist`\n"
                "`!timezone America/New_York` — set your timezone → `#watchlist`\n"
                "`!brief-times 06:00,12:00,16:15` — set your times → `#watchlist`\n"
                "`!alert-percent 3` — set your alert percent → `#watchlist`\n"
                "`!add TSLA` / `!remove TSLA` — edit your list → `#watchlist`\n"
                "`!list` / `!scan` — show or scan your personal list → `#watchlist`"
            ),
            inline=False,
        )

        embed.add_field(
            name="📌 Shared Watchlist / Alerts",
            value=(
                "`!watchlist` — show shared watched symbols and data health → `#watchlist`\n"
                "`!watchtest` — test quote freshness/accuracy health → `#watchlist`\n"
                "`!alerts` — scan shared alerts → `#watchlist`\n"
                "`!watch TSLA` / `!unwatch CVX` — edit shared list → `#watchlist`\n"
                "`!threshold 2` — set shared price alert percent → `#watchlist`"
            ),
            inline=False,
        )

        embed.add_field(
            name="📰 News Commands",
            value=(
                "`!news` — latest routed news → regular news channels only\n"
                "`!news sources` — provider/source policy\n"
                "`!news post` — post fresh routed items\n"
                "`!news ai` — real AI/chips/data-center only → `#ai-news`\n"
                "`!news general` — major U.S./world news → `#general-news`\n"
                "`!news geo` — geopolitics/oil risk → `#geopolitics`\n"
                "`!news fed` — Fed/rates/inflation → `#fed`\n"
                "`!news crypto` — crypto → `#crypto`\n"
                "`!news reddit` — Reddit chatter → `#reddit-hot`"
            ),
            inline=False,
        )

        embed.add_field(
            name="📱 Social / Video Monitor",
            value=(
                "`!social` — social/video monitor status → `#x-news`, `#video-news`, or `#trending-news`\n"
                "`!xnews` — raw configured X public-account posts → `#x-news` only\n"
                "`!videonews` — Bloomberg/CNBC/Reuters video RSS items → `#video-news` only\n"
                "`!trending` — configured X trending/fast-moving accounts → `#trending-news` only\n"
                "`!socialpost` — manually post routed social/video items → social channels only"
            ),
            inline=False,
        )

        embed.add_field(
            name="🗓 Calendar",
            value=(
                "`!calendarfetch` — pull official event calendar → `#market-calendar`\n"
                "`!events` — upcoming official events\n"
                "`!calendartoday` — today only\n"
                "`!calendarweek` — next 7 days\n"
                "Reminders post to `#calendar-event-reminder` only when an event is coming up."
            ),
            inline=False,
        )

        embed.add_field(
            name="🔑 Admin / Owner",
            value=(
                "Admin keys/tickets: `#admin-keys`\n"
                "Owner audit logs: `#owner-audit`\n"
                "Ticket panel: `!ticketpanel` → `#marketops-commands`\n"
                "Role sync: `!syncroles` → `#admin-keys`"
            ),
            inline=False,
        )

        embed.add_field(
            name="✅ Allowed Anywhere",
            value="`!commands`, `!help`, `!cmds`, and `!ping` can be used anywhere.",
            inline=False,
        )

        embed.add_field(
            name="Best Flow",
            value="`!pulse` → `!watchtest` → `!brief` → `!mychart SPY 1d` → `!mychart QQQ 1d` → `!news post` → `!videonews` → optional `!xnews` later if X token is added",
            inline=False,
        )

        embed.set_footer(text=VERSION)
        return embed


async def setup(bot):
    await bot.add_cog(MarketOpsHelp(bot))
