import discord
from discord import app_commands
from discord.ext import commands

from market.coach_engine import CoachEngine
from market.market_service import MarketService


class Coach(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.market = MarketService()
        self.coach = CoachEngine()

    @app_commands.command(
        name="coach",
        description="Get a plain-English MarketOps coach read.",
    )
    async def coach_slash(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        try:
            dashboard = self.market.get_dashboard()
            coach = self.coach.build(dashboard)
            embed = self._build_coach_embed(coach, dashboard)
            await interaction.followup.send(embed=embed)

        except Exception as error:
            print(f"❌ /coach error: {error}")
            await interaction.followup.send(
                "⚠️ MarketOps had trouble building the coach read. "
                "Check the terminal for the error.",
                ephemeral=True,
            )

    @commands.command(name="coach")
    async def coach_prefix(self, ctx):
        """Desktop/web fallback command.

        If Discord desktop/web refuses to show bot slash commands, type !coach.
        """
        try:
            dashboard = self.market.get_dashboard()
            coach = self.coach.build(dashboard)
            embed = self._build_coach_embed(coach, dashboard)
            await ctx.send(embed=embed)

        except Exception as error:
            print(f"❌ !coach error: {error}")
            await ctx.send(
                "⚠️ MarketOps had trouble building the coach read. "
                "Check the terminal for the error."
            )

    def _build_coach_embed(self, coach, dashboard):
        embed = discord.Embed(
            title="🧠 MarketOps Coach",
            description="Plain-English read of the current market dashboard.",
            color=self._risk_color(dashboard["score"]),
        )

        embed.add_field(
            name="Today's Read",
            value=coach["read"],
            inline=False,
        )

        embed.add_field(
            name="What It Means",
            value=coach["meaning"],
            inline=False,
        )

        embed.add_field(
            name="Why?",
            value=coach["why"],
            inline=False,
        )

        embed.add_field(
            name="What To Watch Next",
            value=coach["watch"],
            inline=False,
        )

        embed.add_field(
            name="Beginner Lesson",
            value=coach["lesson"],
            inline=False,
        )

        embed.add_field(
            name="Reminder",
            value=coach["reminder"],
            inline=False,
        )

        embed.set_footer(
            text=f'Updated {coach["updated"]} • MarketOps v0.3'
        )

        return embed

    def _risk_color(self, score):
        if score >= 60:
            return discord.Color.green()

        if score <= 40:
            return discord.Color.orange()

        return discord.Color.gold()


async def setup(bot):
    await bot.add_cog(Coach(bot))
