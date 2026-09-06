import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from market.brief_engine import BriefEngine


VERSION = "MarketOps v0.8.1"


class Brief(commands.Cog):
    """Discord commands for the MarketOps morning brief."""

    def __init__(self, bot):
        self.bot = bot
        self.brief_engine = BriefEngine()

    @app_commands.command(
        name="brief",
        description="View the MarketOps morning brief.",
    )
    async def brief_slash(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        try:
            brief = await asyncio.to_thread(self.brief_engine.build_brief)
            embed = self._build_brief_embed(brief)
            await interaction.followup.send(embed=embed)
        except Exception as error:
            print(f"❌ /brief error: {error}")
            await interaction.followup.send(
                "⚠️ MarketOps had trouble building the morning brief. Check the terminal for the error.",
                ephemeral=True,
            )

    @commands.command(name="brief")
    async def brief_prefix(self, ctx):
        """Desktop/web fallback command. Type !brief."""
        try:
            brief = await asyncio.to_thread(self.brief_engine.build_brief)
            embed = self._build_brief_embed(brief)
            await ctx.send(embed=embed)
        except Exception as error:
            print(f"❌ !brief error: {error}")
            await ctx.send(
                "⚠️ MarketOps had trouble building the morning brief. Check the terminal for the error."
            )

    def _build_brief_embed(self, brief):
        dashboard = brief["dashboard"]
        top_items = brief["top_items"]

        embed = discord.Embed(
            title="🌅 MarketOps Morning Brief",
            description="One quick read before you look at charts or headlines.",
            color=self._risk_color(dashboard["score"]),
        )

        embed.add_field(
            name="🧠 Market Mood",
            value=(
                f'**{dashboard["risk"]}**\n'
                f'Score: **{dashboard["score"]}/100**\n'
                f'Confidence: {dashboard["confidence"]}'
            ),
            inline=False,
        )

        embed.add_field(
            name="Why?",
            value=self._format_reasons(dashboard.get("reasons", [])),
            inline=False,
        )

        embed.add_field(
            name="⚡ Fast Market Check",
            value=(
                f'**Leader:** {dashboard["leader"]}\n'
                f'**Weakest:** {dashboard["loser"]}\n'
                f'**Warning:** {dashboard["warning_signal"]}\n'
                f'**Oil/Geo:** {dashboard["energy_signal"]}\n'
                f'**Crypto:** {dashboard["crypto_signal"]}'
            ),
            inline=False,
        )

        embed.add_field(
            name="📰 Top Market News",
            value=self._format_item(top_items.get("market")),
            inline=False,
        )

        embed.add_field(
            name="🏦 Fed / Rates",
            value=self._format_item(top_items.get("fed")),
            inline=False,
        )

        embed.add_field(
            name="🛢 Geopolitics / Oil Risk",
            value=self._format_item(top_items.get("geo")),
            inline=False,
        )

        embed.add_field(
            name="🤖 AI / Tech",
            value=self._format_item(top_items.get("ai")),
            inline=False,
        )

        embed.add_field(
            name="₿ Crypto",
            value=self._format_item(top_items.get("crypto")),
            inline=False,
        )

        embed.add_field(
            name="🗞 General News",
            value=self._format_item(top_items.get("general")),
            inline=False,
        )

        embed.add_field(
            name="🧵 Reddit Chatter",
            value=self._format_item(top_items.get("reddit"), reddit=True),
            inline=False,
        )

        embed.add_field(
            name="🎯 What To Watch",
            value="\n".join(f"• {item}" for item in brief.get("watch_list", [])),
            inline=False,
        )

        embed.set_footer(
            text=(
                f'Updated {brief.get("updated", "Unknown")} • '
                f'Providers checked: {brief.get("provider_used", "Unknown")} • {VERSION}'
            )
        )
        return embed

    def _format_item(self, item, reddit=False):
        if item is None:
            return "No fresh item found."

        title = discord.utils.escape_markdown(item.get("title", "Untitled"))
        source = item.get("source", "Unknown")
        age = item.get("age_label", "Unknown")
        route = item.get("channel", "unknown")
        link = item.get("link", "")

        warning = "⚠️ Reddit chatter only — verify first.\n" if reddit else ""
        open_line = f"\n[Read item]({link})" if link else ""

        return (
            f"{warning}**{title}**\n"
            f"Source: {source} • Age: {age} • Route: `#{route}`"
            f"{open_line}"
        )

    def _format_reasons(self, reasons):
        if not reasons:
            return "No clear reason yet."
        return "\n".join(f"• {reason}" for reason in reasons[:5])

    def _risk_color(self, score):
        if score >= 60:
            return discord.Color.green()
        if score <= 30:
            return discord.Color.red()
        if score <= 45:
            return discord.Color.orange()
        return discord.Color.gold()


async def setup(bot):
    await bot.add_cog(Brief(bot))
