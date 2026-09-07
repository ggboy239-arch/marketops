import discord
from discord.ext import commands


VERSION = "MarketOps v2.6"


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
            name="👤 Personal User Commands",
            value=(
                "`!redeem KEY-HERE` — unlock personal commands → `#watchlist`\n"
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
            name="🔑 Admin Key Commands",
            value=(
                "`!genkey beta 30` — make one 30-day beta key\n"
                "`!genkey monthly 30` — make one monthly key\n"
                "`!genkey lifetime` — make one lifetime key\n"
                "`!genkeys beta 30 5` — make 5 beta keys\n"
                "`!revokekey KEY-HERE` — disable a key\n"
                "`!adminusers` — see redeemed users"
            ),
            inline=False,
        )

        embed.add_field(
            name="📌 Shared Watchlist / Alerts",
            value=(
                "`!watchlist` — show shared watched symbols → `#watchlist`\n"
                "`!alerts` — scan shared alerts → `#watchlist`\n"
                "`!watch TSLA` / `!unwatch CVX` — edit shared list → `#watchlist`\n"
                "`!threshold 2` — set shared price alert percent → `#watchlist`"
            ),
            inline=False,
        )

        embed.add_field(
            name="📰 News Commands",
            value=(
                "`!news` — latest routed news → news channels\n"
                "`!news sources` — provider status/source policy\n"
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
            value="`!brief` → `!list` → `!scan` → `!learn`",
            inline=False,
        )

        embed.set_footer(text=VERSION)
        return embed


async def setup(bot):
    await bot.add_cog(MarketOpsHelp(bot))
