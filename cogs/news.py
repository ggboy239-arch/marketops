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
    @app_commands.describe(
        category="Choose a news category."
    )
    @app_commands.choices(
        category=[
            app_commands.Choice(name="all", value="all"),
            app_commands.Choice(name="AI / tech", value="ai"),
            app_commands.Choice(name="Fed / rates", value="fed"),
            app_commands.Choice(name="oil / geopolitics", value="geo"),
            app_commands.Choice(name="crypto", value="crypto"),
            app_commands.Choice(name="broad market", value="market"),
        ]
    )
    async def news_slash(
        self,
        interaction: discord.Interaction,
        category: app_commands.Choice[str] = None,
    ):
        await interaction.response.defer(thinking=True)

        try:
            selected_category = category.value if category else "all"
            report = self.news.get_top_news(limit=5, category=selected_category)
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
    async def news_prefix(self, ctx, category="all"):
        """Desktop/web fallback command.

        Examples:
        !news
        !news ai
        !news geo
        !news fed
        !news crypto
        !news channels
        !news post
        """
        try:
            category = category.lower().strip()

            if category in ("help", "categories"):
                await ctx.send(embed=self._build_help_embed())
                return

            if category in ("channels", "channel"):
                await ctx.send(embed=self._build_channel_map_embed())
                return

            if category in ("post", "route", "send"):
                await self._post_news_to_channels(ctx)
                return

            report = self.news.get_top_news(limit=5, category=category)
            embed = self._build_news_embed(report)
            await ctx.send(embed=embed)

        except Exception as error:
            print(f"❌ !news error: {error}")
            await ctx.send(
                "⚠️ MarketOps had trouble building the news report. "
                "Check the terminal for the error."
            )

    async def _post_news_to_channels(self, ctx):
        if ctx.guild is None:
            await ctx.send("⚠️ Channel posting only works inside a Discord server.")
            return

        report = self.news.get_channel_reports(limit_per_channel=3)
        channels = report.get("channels", {})
        posted_count = 0
        missing_channels = []

        for channel_name, items in channels.items():
            if not items:
                continue

            channel = discord.utils.get(
                ctx.guild.text_channels,
                name=channel_name,
            )

            if channel is None:
                missing_channels.append(channel_name)
                continue

            embed = self._build_news_embed(
                {
                    "items": items,
                    "category": channel_name,
                    "updated": report.get("updated", "Unknown"),
                }
            )
            await channel.send(embed=embed)
            posted_count += 1

        message = f"✅ Posted news into **{posted_count}** channel(s)."

        if missing_channels:
            missing = ", ".join(f"#{name}" for name in missing_channels)
            message += f"\n⚠️ Missing channels: {missing}"

        await ctx.send(message)

    def _build_news_embed(self, report):
        category = report.get("category", "all")
        title = self._title_for_category(category)

        embed = discord.Embed(
            title=title,
            description="Reuters-focused headlines with market impact notes.",
            color=discord.Color.blue(),
        )

        items = report.get("items", [])

        if not items:
            embed.add_field(
                name="No headlines found",
                value="Try another category or check again in a few minutes.",
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
            text=f'Updated {report.get("updated", "Unknown")} • MarketOps v0.5.1'
        )

        return embed

    def _format_item(self, item):
        title = item.get("title", "Untitled")
        link = item.get("link", "")
        tags = ", ".join(item.get("tags", []))
        channel = item.get("channel", "breaking-news")
        why = item.get("why_it_matters", "Watch market reaction.")
        watch = item.get("watch", "Market reaction")

        if link:
            headline = f"[{title}]({link})"
        else:
            headline = title

        value = (
            f"**{headline}**\n"
            f"Tags: {tags}\n"
            f"Route: `#{channel}`\n"
            f"Why it matters: {why}\n"
            f"Watch: **{watch}**"
        )

        if len(value) > 1000:
            value = value[:997] + "..."

        return value

    def _build_help_embed(self):
        embed = discord.Embed(
            title="📰 MarketOps News Help",
            description=self.news.category_help(),
            color=discord.Color.gold(),
        )
        embed.set_footer(text="MarketOps v0.5.1")
        return embed

    def _build_channel_map_embed(self):
        embed = discord.Embed(
            title="🧭 MarketOps News Channel Routing",
            description=self.news.channel_map_text(),
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="Manual channel post",
            value="Type `!news post` to send headlines into the matching channels.",
            inline=False,
        )
        embed.set_footer(text="MarketOps v0.5.1")
        return embed

    def _title_for_category(self, category):
        titles = {
            "all": "📰 MarketOps News",
            "ai": "🤖 AI / Tech News",
            "tech": "🤖 AI / Tech News",
            "fed": "🏦 Fed / Rates News",
            "rates": "🏦 Fed / Rates News",
            "geo": "🛢 Oil / Geopolitics News",
            "geopolitics": "🛢 Oil / Geopolitics News",
            "oil": "🛢 Oil / Geopolitics News",
            "crypto": "₿ Crypto News",
            "bitcoin": "₿ Crypto News",
            "market": "📊 Broad Market News",
            "breaking-news": "🚨 Breaking News",
            "ai-news": "🤖 AI / Tech News",
        }

        return titles.get(category, f"📰 MarketOps News — {category}")


async def setup(bot):
    await bot.add_cog(News(bot))
