import discord
from discord import app_commands
from discord.ext import commands

from market.news_engine import NewsEngine


class News(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.news = NewsEngine()

    @app_commands.command(
        name="news",
        description="View top market-moving headlines.",
    )
    async def news_slash(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        try:
            report = self.news.get_top_news(limit=5)
            embed = self._build_news_embed(report)
            await interaction.followup.send(embed=embed)

        except Exception as error:
            print(f"❌ /news error: {error}")
            await interaction.followup.send(
                "⚠️ MarketOps had trouble building the news report. "
                "Check the terminal for the error.",
                ephemeral=True,
            )

    @commands.command(name="news")
    async def news_prefix(self, ctx):
        """Desktop/web fallback command.

        If Discord desktop/web refuses to show bot slash commands, type !news.
        """
        try:
            report = self.news.get_top_news(limit=5)
            embed = self._build_news_embed(report)
            await ctx.send(embed=embed)

        except Exception as error:
            print(f"❌ !news error: {error}")
            await ctx.send(
                "⚠️ MarketOps had trouble building the news report. "
                "Check the terminal for the error."
            )

    def _build_news_embed(self, report):
        embed = discord.Embed(
            title="📰 MarketOps News",
            description="Top headlines with market impact notes.",
            color=discord.Color.blue(),
        )

        items = report.get("items", [])

        if not items:
            embed.add_field(
                name="No headlines found",
                value="Try again in a few minutes or check your internet connection.",
                inline=False,
            )
        else:
            for index, item in enumerate(items, start=1):
                embed.add_field(
                    name=f'{index}. {item["source"]} • {item["importance"]}',
                    value=self._format_item(item),
                    inline=False,
                )

        embed.set_footer(
            text=f'Updated {report.get("updated", "Unknown")} • MarketOps v0.5'
        )

        return embed

    def _format_item(self, item):
        title = item.get("title", "Untitled")
        link = item.get("link", "")
        tags = ", ".join(item.get("tags", []))
        why = item.get("why_it_matters", "Watch market reaction.")
        watch = item.get("watch", "Market reaction")

        if link:
            headline = f"[{title}]({link})"
        else:
            headline = title

        value = (
            f"**{headline}**\n"
            f"Tags: {tags}\n"
            f"Why it matters: {why}\n"
            f"Watch: **{watch}**"
        )

        if len(value) > 1000:
            value = value[:997] + "..."

        return value


async def setup(bot):
    await bot.add_cog(News(bot))
