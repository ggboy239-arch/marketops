import asyncio
import hashlib
import json
import os
from pathlib import Path
from time import monotonic

import discord
from discord import app_commands
from discord.ext import commands, tasks

from market.news_engine import NewsEngine


VERSION = "MarketOps v0.6.3"


class News(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.news = NewsEngine()
        self.auto_post_enabled = self._env_bool("NEWS_AUTO_POST", default=True)
        self.poll_minutes = float(os.getenv("NEWS_POLL_MINUTES", "1"))
        self.seen_file = Path("data/seen_news.json")
        self.seen_news = self._load_seen_news()
        self._last_poll = 0.0
        self._last_check = "Not checked yet"
        self._last_auto_post = "Not posted yet"
        self._last_auto_post_count = 0
        self._last_counts = {}
        self._last_provider_used = "Not checked yet"

        if self.auto_post_enabled and not self.auto_news_loop.is_running():
            self.auto_news_loop.start()

    def cog_unload(self):
        if self.auto_news_loop.is_running():
            self.auto_news_loop.cancel()

    @app_commands.command(
        name="news",
        description="View top trusted market-moving headlines.",
    )
    @app_commands.describe(category="Choose a news category.")
    @app_commands.choices(
        category=[
            app_commands.Choice(name="all", value="all"),
            app_commands.Choice(name="broad market", value="market"),
            app_commands.Choice(name="general / national", value="general"),
            app_commands.Choice(name="AI / tech", value="ai"),
            app_commands.Choice(name="Fed / rates", value="fed"),
            app_commands.Choice(name="oil / geopolitics", value="geo"),
            app_commands.Choice(name="crypto", value="crypto"),
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
            report = await asyncio.to_thread(
                self.news.get_top_news,
                limit=5,
                category=selected_category,
            )
            embed = self._build_news_embed(report)
            await interaction.followup.send(embed=embed)

        except Exception as error:
            print(f"❌ /news error: {error}")
            await interaction.followup.send(
                "⚠️ MarketOps had trouble building the news report. Check the terminal for the error.",
                ephemeral=True,
            )

    @commands.command(name="news")
    async def news_prefix(self, ctx, category="all"):
        """Desktop/web fallback command.

        Examples:
        !news
        !news market
        !news general
        !news ai
        !news geo
        !news fed
        !news crypto
        !news channels
        !news sources
        !news debug
        !news post
        !news live
        """
        try:
            category = category.lower().strip()

            if category in ("help", "categories"):
                await ctx.send(embed=self._build_help_embed())
                return

            if category in ("channels", "channel"):
                await ctx.send(embed=self._build_channel_map_embed())
                return

            if category in ("sources", "source", "reuters", "finlight"):
                await ctx.send(embed=self._build_sources_embed())
                return

            if category in ("debug", "counts", "count"):
                await ctx.send(embed=await self._build_debug_embed())
                return

            if category in ("live", "status"):
                await ctx.send(embed=self._build_live_status_embed())
                return

            if category in ("post", "route", "send"):
                await self._post_news_to_channels(ctx)
                return

            report = await asyncio.to_thread(
                self.news.get_top_news,
                limit=5,
                category=category,
            )
            embed = self._build_news_embed(report)
            await ctx.send(embed=embed)

        except Exception as error:
            print(f"❌ !news error: {error}")
            await ctx.send(
                "⚠️ MarketOps had trouble building the news report. Check the terminal for the error."
            )

    @tasks.loop(seconds=15)
    async def auto_news_loop(self):
        await self.bot.wait_until_ready()

        elapsed_seconds = monotonic() - self._last_poll
        poll_seconds = self.poll_minutes * 60

        if elapsed_seconds < poll_seconds:
            return

        self._last_poll = monotonic()

        try:
            report = await asyncio.to_thread(
                self.news.get_channel_reports,
                limit_per_channel=2,
            )
            self._last_check = report.get("updated", "Unknown")
            self._last_counts = report.get("counts", {})
            self._last_provider_used = report.get("provider_used", "Unknown")

            all_items = self._all_report_items(report)

            if not self.seen_news:
                self._mark_items_seen(all_items)
                self._save_seen_news()
                print(
                    "📰 News monitor seeded current fresh trusted headlines. "
                    "New headlines will auto-post after this."
                )
                return

            total_posted = 0

            for guild in self.bot.guilds:
                posted_count, missing_channels = await self._send_channel_report(
                    guild=guild,
                    report=report,
                    filter_seen=True,
                )
                total_posted += posted_count

                if missing_channels:
                    missing = ", ".join(missing_channels)
                    print(f"⚠️ Missing news channels in {guild.name}: {missing}")

            self._last_auto_post_count = total_posted

            if total_posted:
                self._last_auto_post = report.get("updated", "Unknown")
                print(f"📰 Auto-posted fresh news into {total_posted} channel(s).")

            self._save_seen_news()

        except Exception as error:
            print(f"❌ Auto news loop error: {error}")

    async def _post_news_to_channels(self, ctx):
        if ctx.guild is None:
            await ctx.send("⚠️ Channel posting only works inside a Discord server.")
            return

        report = await asyncio.to_thread(
            self.news.get_channel_reports,
            limit_per_channel=3,
        )
        self._last_check = report.get("updated", "Unknown")
        self._last_counts = report.get("counts", {})
        self._last_provider_used = report.get("provider_used", "Unknown")

        posted_count, missing_channels = await self._send_channel_report(
            guild=ctx.guild,
            report=report,
            filter_seen=False,
        )

        message = f"✅ Posted fresh trusted news into **{posted_count}** channel(s)."
        count_text = self._format_counts(report.get("counts", {}))

        if count_text:
            message += f"\n\nFound by channel:\n{count_text}"

        if missing_channels:
            missing = ", ".join(f"#{name}" for name in missing_channels)
            message += f"\n⚠️ Missing channels: {missing}"

        await ctx.send(message)

    async def _send_channel_report(self, guild, report, filter_seen):
        channels = report.get("channels", {})
        posted_count = 0
        missing_channels = []

        for channel_name, items in channels.items():
            if not items:
                continue

            channel = discord.utils.get(guild.text_channels, name=channel_name)

            if channel is None:
                missing_channels.append(channel_name)
                continue

            items_to_post = []

            for item in items:
                item_id = self._article_id(item)

                if filter_seen and item_id in self.seen_news:
                    continue

                items_to_post.append(item)
                self.seen_news.add(item_id)

            if not items_to_post:
                continue

            embed = self._build_news_embed(
                {
                    "items": items_to_post,
                    "category": channel_name,
                    "updated": report.get("updated", "Unknown"),
                    "source_policy": report.get("source_policy", "Trusted source mode."),
                    "freshness_policy": report.get("freshness_policy", "Fresh headlines only."),
                    "provider_used": report.get("provider_used", "Unknown"),
                }
            )
            await channel.send(embed=embed)
            posted_count += 1

        return posted_count, missing_channels

    def _build_news_embed(self, report):
        category = report.get("category", "all")

        embed = discord.Embed(
            title=self._title_for_category(category),
            description="Fresh trusted headlines routed by topic.",
            color=discord.Color.blue(),
        )

        items = report.get("items", [])

        if not items:
            embed.add_field(
                name="No fresh trusted headlines found",
                value=(
                    "MarketOps did not find a matching trusted headline in the current freshness window. "
                    "It will not invent news just to fill the channel."
                ),
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
            text=(
                f'Checked {report.get("updated", "Unknown")} • '
                f'Provider: {report.get("provider_used", "Unknown")} • {VERSION}'
            )
        )
        return embed

    def _format_item(self, item):
        title = discord.utils.escape_markdown(item.get("title", "Untitled"))
        link = item.get("link", "")
        tags = ", ".join(item.get("tags", []))
        channel = item.get("channel", "breaking-news")
        why = item.get("why_it_matters", "Watch market reaction.")
        watch = item.get("watch", "Market reaction")
        published_label = item.get("published_label", "Unknown")
        age_label = item.get("age_label", "Unknown")
        provider = item.get("provider", "Unknown")
        trusted_badge = "✅ Trusted" if item.get("trusted") else "⚠️ Unverified"

        read_line = f"Open: [Read full article]({link})\n" if link else ""

        value = (
            f"Headline: **{title}**\n"
            f"{read_line}"
            f"Source: {trusted_badge} • Provider: **{provider}**\n"
            f"Published: **{published_label}** ({age_label})\n"
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
        embed.add_field(
            name="Live Auto-Posting",
            value=(
                "MarketOps checks frequently for fresh trusted headlines and routes them into the matching channels. "
                "Use `!news live` to check status."
            ),
            inline=False,
        )
        embed.set_footer(text=VERSION)
        return embed

    def _build_channel_map_embed(self):
        embed = discord.Embed(
            title="🧭 MarketOps News Channel Routing",
            description=self.news.channel_map_text(),
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="Manual channel post",
            value="Type `!news post` to send current fresh trusted headlines into the matching channels.",
            inline=False,
        )
        embed.add_field(
            name="Rule",
            value=(
                "`#breaking-news` is for market-moving headlines. "
                "`#general-news` is for important national/world headlines that are not directly market-specific."
            ),
            inline=False,
        )
        embed.set_footer(text=VERSION)
        return embed

    def _build_sources_embed(self):
        embed = discord.Embed(
            title="✅ MarketOps News Source Policy",
            description=self.news.source_policy(),
            color=discord.Color.green(),
        )
        embed.add_field(name="Freshness Rule", value=self.news.freshness_policy(), inline=False)
        embed.add_field(
            name="Important Reality",
            value=(
                "Free RSS/search monitoring is near-live, but true instant breaking news requires "
                "a paid push feed such as WebSocket or webhook access."
            ),
            inline=False,
        )
        embed.add_field(
            name="Recommended .env Settings",
            value=(
                "`NEWS_MAX_AGE_HOURS=0.25`\n"
                "`NEWS_POLL_MINUTES=1`\n"
                "`NEWS_FALLBACK_RSS=true`"
            ),
            inline=False,
        )
        embed.set_footer(text=VERSION)
        return embed

    async def _build_debug_embed(self):
        report = await asyncio.to_thread(self.news.get_channel_reports, limit_per_channel=5)
        counts = report.get("counts", {})
        self._last_check = report.get("updated", "Unknown")
        self._last_counts = counts
        self._last_provider_used = report.get("provider_used", "Unknown")

        embed = discord.Embed(
            title="🧪 MarketOps News Debug",
            description="Shows how many fresh trusted headlines MarketOps found for each route.",
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="Counts by Channel",
            value=self._format_counts(counts) or "No fresh trusted headlines found.",
            inline=False,
        )
        embed.add_field(name="Last Feed Check", value=self._last_check, inline=True)
        embed.add_field(name="Provider Used", value=self._last_provider_used, inline=True)
        embed.add_field(
            name="Source Policy",
            value=report.get("source_policy", self.news.source_policy()),
            inline=False,
        )
        embed.add_field(
            name="Freshness Policy",
            value=report.get("freshness_policy", self.news.freshness_policy()),
            inline=False,
        )
        embed.set_footer(text=f'Checked {report.get("updated", "Unknown")} • {VERSION}')
        return embed

    def _build_live_status_embed(self):
        status = "ON" if self.auto_post_enabled else "OFF"

        embed = discord.Embed(
            title="🟢 MarketOps Live News Monitor",
            description="Automatic fresh trusted news routing status.",
            color=discord.Color.green() if self.auto_post_enabled else discord.Color.red(),
        )
        embed.add_field(name="Auto-posting", value=f"**{status}**", inline=True)
        embed.add_field(name="Poll Rate", value=f"Every **{self.poll_minutes:g} minute(s)**", inline=True)
        embed.add_field(name="Seen Headlines", value=f"**{len(self.seen_news)}** tracked", inline=True)
        embed.add_field(name="Last Feed Check", value=self._last_check, inline=True)
        embed.add_field(name="Provider Used", value=self._last_provider_used, inline=True)
        embed.add_field(
            name="Last Auto Post",
            value=f"{self._last_auto_post} ({self._last_auto_post_count} channel updates)",
            inline=True,
        )
        embed.add_field(
            name="Current Counts",
            value=self._format_counts(self._last_counts) or "No check completed yet.",
            inline=False,
        )
        embed.add_field(name="Freshness Policy", value=self.news.freshness_policy(), inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _format_counts(self, counts):
        if not counts:
            return ""

        ordered = [
            "breaking-news",
            "general-news",
            "ai-news",
            "fed",
            "geopolitics",
            "crypto",
        ]
        lines = []

        for channel in ordered:
            if channel in counts:
                lines.append(f"• `#{channel}` — **{counts[channel]}** headline(s)")

        for channel, count in counts.items():
            if channel not in ordered:
                lines.append(f"• `#{channel}` — **{count}** headline(s)")

        return "\n".join(lines)

    def _title_for_category(self, category):
        titles = {
            "all": "📰 MarketOps News",
            "market": "📊 Broad Market News",
            "markets": "📊 Broad Market News",
            "breaking-news": "🚨 Market-Moving Breaking News",
            "general": "🗞 General News",
            "national": "🗞 General News",
            "world": "🗞 General News",
            "general-news": "🗞 General News",
            "ai": "🤖 AI / Tech News",
            "tech": "🤖 AI / Tech News",
            "ai-news": "🤖 AI / Tech News",
            "fed": "🏦 Fed / Rates News",
            "rates": "🏦 Fed / Rates News",
            "geo": "🛢 Oil / Geopolitics News",
            "geopolitics": "🛢 Oil / Geopolitics News",
            "oil": "🛢 Oil / Geopolitics News",
            "crypto": "₿ Crypto News",
            "bitcoin": "₿ Crypto News",
        }

        return titles.get(category, f"📰 MarketOps News — {category}")

    def _env_bool(self, name, default=False):
        value = os.getenv(name)

        if value is None:
            return default

        return value.strip().lower() in ("1", "true", "yes", "y", "on")

    def _all_report_items(self, report):
        items = []
        for channel_items in report.get("channels", {}).values():
            items.extend(channel_items)
        return items

    def _mark_items_seen(self, items):
        for item in items:
            self.seen_news.add(self._article_id(item))

    def _article_id(self, item):
        base = item.get("link") or f'{item.get("source", "")}::{item.get("title", "")}'
        return hashlib.sha256(base.encode("utf-8")).hexdigest()

    def _load_seen_news(self):
        if not self.seen_file.exists():
            return set()

        try:
            with self.seen_file.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except Exception:
            return set()

        return set(data if isinstance(data, list) else [])

    def _save_seen_news(self):
        self.seen_file.parent.mkdir(parents=True, exist_ok=True)
        trimmed = list(self.seen_news)[-500:]

        with self.seen_file.open("w", encoding="utf-8") as file:
            json.dump(trimmed, file, indent=2)


async def setup(bot):
    await bot.add_cog(News(bot))
