import discord
from discord import app_commands
from discord.ext import commands


class Ping(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="ping",
        description="Check if MarketOps is online."
    )
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)

        await interaction.response.send_message(
            f"🏓 Pong!\n\nLatency: **{latency} ms**"
        )


async def setup(bot):
    await bot.add_cog(Ping(bot))