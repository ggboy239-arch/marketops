import discord
from discord.ext import commands


VERSION = "MarketOps v2.2"


class MarketOpsHelp(commands.Cog):
    """Short command guide for MarketOps.

    Plain English: this cog is the cheat sheet. The user can type !commands,
    !help, or !cmds and get a quick reminder of what every command does and
    which channel to use it in.
    """

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
            name="🌅 Morning / Market Read",
            value=(
                "`!brief` — full market brief → `#morning-brief`\n"
                "`!market` — quick dashboard → `#market-dashboard`\n"
                "`!learn` — explains today's market setup → `#market-school`\n"
                "`!playbook` — quick checklist → `#market-school`"
            ),
            inline=False,
        )

        embed.add_field(
            name="📌 Watchlist / Alerts",
            value=(
                "`!watchlist` — show watched symbols → `#watchlist`\n"
                "`!alerts` — scan price + headline alerts → `#watchlist`\n"
                "`!watch TSLA` — add symbol → `#watchlist`\n"
                "`!unwatch CVX` — remove symbol → `#watchlist`\n"
                "`!watchreset` — reset saved list → `#watchlist`"
            ),
            inline=False,
        )

        embed.add_field(
            name="⚙️ Alert Controls",
            value=(
                "`!alertstatus` — show settings → `#watchlist`\n"
                "`!alertson` / `!alertsoff` — turn alerts on/off → `#watchlist`\n"
                "`!newson` / `!newsoff` — turn headline alerts on/off → `#watchlist`\n"
                "`!threshold 2` — set price alert percent → `#watchlist`"
            ),
            inline=False,
        )

        embed.add_field(
            name="📰 News Commands",
            value=(
                "`!news` — latest routed news → news channels\n"
                "`!news ai` — AI/tech → `#ai-news`\n"
                "`!news geo` — geopolitics/oil risk → `#geopolitics`\n"
                "`!news fed` — Fed/rates/inflation → `#fed`\n"
                "`!news crypto` — crypto → `#crypto`\n"
                "`!news reddit` — Reddit chatter → `#reddit-hot`"
            ),
            inline=False,
        )

        embed.add_field(
            name="✅ Allowed Anywhere",
            value="`!commands`, `!help`, `!cmds`, and `!ping` can be used anywhere.",
            inline=False,
        )

        embed.add_field(
            name="Best Daily Flow",
            value="`!brief` → `!watchlist` → `!alerts` → `!learn`",
            inline=False,
        )

        embed.set_footer(text=VERSION)
        return embed


async def setup(bot):
    await bot.add_cog(MarketOpsHelp(bot))
