import discord
from discord import app_commands
from discord.ext import commands

from market.explain_engine import ExplainEngine
from market.market_service import MarketService


class Explain(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.market = MarketService()
        self.explain_engine = ExplainEngine()

    @app_commands.command(
        name="explain",
        description="Explain a market signal in plain English.",
    )
    @app_commands.describe(
        topic="Choose what you want MarketOps to explain."
    )
    @app_commands.choices(
        topic=[
            app_commands.Choice(name="market / S&P futures", value="market"),
            app_commands.Choice(name="tech / Nasdaq futures", value="tech"),
            app_commands.Choice(name="vix / fear", value="vix"),
            app_commands.Choice(name="oil", value="oil"),
            app_commands.Choice(name="dollar / DXY", value="dollar"),
            app_commands.Choice(name="rates / US10Y", value="rates"),
            app_commands.Choice(name="bitcoin / crypto", value="bitcoin"),
        ]
    )
    async def explain_slash(
        self,
        interaction: discord.Interaction,
        topic: app_commands.Choice[str],
    ):
        await interaction.response.defer(thinking=True)

        try:
            dashboard = self.market.get_dashboard()
            explanation = self.explain_engine.build(topic.value, dashboard)
            embed = self._build_explain_embed(explanation)
            await interaction.followup.send(embed=embed)

        except Exception as error:
            print(f"❌ /explain error: {error}")
            await interaction.followup.send(
                "⚠️ MarketOps had trouble building the explanation. "
                "Check the terminal for the error.",
                ephemeral=True,
            )

    @commands.command(name="explain")
    async def explain_prefix(self, ctx, *, topic=None):
        """Desktop/web fallback command.

        Examples:
        !explain vix
        !explain oil
        !explain bitcoin
        """
        try:
            dashboard = self.market.get_dashboard()
            explanation = self.explain_engine.build(topic, dashboard)
            embed = self._build_explain_embed(explanation)
            await ctx.send(embed=embed)

        except Exception as error:
            print(f"❌ !explain error: {error}")
            await ctx.send(
                "⚠️ MarketOps had trouble building the explanation. "
                "Check the terminal for the error."
            )

    def _build_explain_embed(self, explanation):
        if not explanation.get("found"):
            embed = discord.Embed(
                title="🧠 MarketOps Explain",
                description=explanation["message"],
                color=discord.Color.gold(),
            )
            embed.set_footer(text="MarketOps v0.4")
            return embed

        embed = discord.Embed(
            title=explanation["title"],
            description="Plain-English explanation of this market signal.",
            color=discord.Color.blue(),
        )

        embed.add_field(
            name="Current Read",
            value=explanation["current"],
            inline=False,
        )

        embed.add_field(
            name="What It Means",
            value=explanation["plain"],
            inline=False,
        )

        embed.add_field(
            name="If It Goes Up",
            value=explanation["up"],
            inline=False,
        )

        embed.add_field(
            name="If It Goes Down",
            value=explanation["down"],
            inline=False,
        )

        embed.add_field(
            name="Who May Benefit",
            value=explanation["benefits"],
            inline=False,
        )

        embed.add_field(
            name="Who May Be Hurt",
            value=explanation["loses"],
            inline=False,
        )

        embed.add_field(
            name="What To Watch",
            value=explanation["watch"],
            inline=False,
        )

        embed.add_field(
            name="Today's Read",
            value=explanation["today"],
            inline=False,
        )

        embed.set_footer(
            text=f'Updated {explanation["updated"]} • MarketOps v0.4'
        )

        return embed


async def setup(bot):
    await bot.add_cog(Explain(bot))
