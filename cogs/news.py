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


VERSION = "MarketOps v0.7.7"


class News(commands.Cog):
    """MarketOps news routing.

    Plain English: this posts clean mobile-friendly headlines, then a compact
    embed. Normal news stays in normal news channels only.
    """

    def __init__(self, bot):
        self.bot = bot
        self.news = NewsEngine()
        self.auto_post_enabled = self._env_bool("NEWS_AUTO_POST", default=True)
        self.poll_minutes = float(os.getenv("NEWS_POLL_MINUTES", "15"))
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

    @app_commands.command(name="news", description="View top trusted market-moving headlines.")
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
            app_commands.Choice(name="reddit hot", value="reddit"),
        ]
    )
    async def news_slash(self, interaction: discord.Interaction, category: app_commands.Choice[str] = None):
        await interaction.response.defer(thinking=True)
        try:
            selected_category = category.value if category else "all"
            report = await asyncio.to_thread(self.news.get_top_news, limit=5, category=selected_category)
            await interaction.followup.send(
                content=self._mobile_preview(selected_category, report.get("items", [])),
                embed=self._build_news_embed(report),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception as error:
            print(f"❌ /news error: {error!r}")
            await interaction.followup.send(
                "⚠️ MarketOps had trouble building the news report. Check the terminal for the error.",
                ephemeral=True,
            )

    @commands.command(name="news")
    async def news_prefix(self, ctx, category="all"):
        try:
            category = (category or "all").lower().strip()

            if category in ("help", "helps", "categories"):
                await ctx.send(embed=self._build_help_embed())
                return
            if category in ("channels", "channel"):
                await ctx.send(embed=self._build_channel_map_embed())
                return
            if category in ("sources", "source", "reuters", "marketaux", "finlight", "reddit", "reddits", "major"):
                await ctx.send(embed=self._build_sources_embed())
                return
            if category in ("debug", "debugs", "counts", "count"):
                await ctx.send(embed=await self._build_debug_embed())
                return
            if category in ("live", "status"):
                await ctx.send(embed=self._build_live_status_embed())
                return
            if category in ("post", "posts", "route", "send"):
                await self._post_news_to_channels(ctx)
                return

            report = await asyncio.to_thread(self.news.get_top_news, limit=5, category=category)
            await ctx.send(
                content=self._mobile_preview(category, report.get("items", [])),
                embed=self._build_news_embed(report),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception as error:
            print(f"❌ !news error: {error!r}")
            await ctx.send("⚠️ MarketOps had trouble building the news report. Check the terminal for the error.")

    @tasks.loop(seconds=15)
    async def auto_news_loop(self):
        await self.bot.wait_until_ready()
        elapsed_seconds = monotonic() - self._last_poll
        poll_seconds = self.poll_minutes * 60
        if elapsed_seconds < poll_seconds:
            return

        self._last_poll = monotonic()
        try:
            report = await asyncio.to_thread(self.news.get_channel_reports, limit_per_channel=2)
            self._last_check = report.get("updated", "Unknown")
            self._last_counts = report.get("counts", {})
            self._last_provider_used = report.get("provider_used", "Unknown")

            all_items = self._all_report_items(report)
            if not self.seen_news:
                self._mark_items_seen(all_items)
                self._save_seen_news()
                print("📰 News monitor seeded current fresh items. New items will auto-post after this.")
                return

            total_posted = 0
            for guild in self.bot.guilds:
                posted_count, missing_channels = await self._send_channel_report(guild, report, filter_seen=True)
                total_posted += posted_count
                if missing_channels:
                    print(f"⚠️ Missing news channels in {guild.name}: {', '.join(missing_channels)}")

            self._last_auto_post_count = total_posted
            if total_posted:
                self._last_auto_post = report.get("updated", "Unknown")
                print(f"📰 Auto-posted fresh items into {total_posted} channel(s).")
            self._save_seen_news()
        except Exception as error:
            print(f"❌ Auto news loop error: {error!r}")

    async def _post_news_to_channels(self, ctx):
        if ctx.guild is None:
            await ctx.send("⚠️ Channel posting only works inside a Discord server.")
            return

        report = await asyncio.to_thread(self.news.get_channel_reports, limit_per_channel=3)
        self._last_check = report.get("updated", "Unknown")
        self._last_counts = report.get("counts", {})
        self._last_provider_used = report.get("provider_used", "Unknown")

        posted_count, missing_channels = await self._send_channel_report(ctx.guild, report, filter_seen=False)
        message = f"✅ Posted fresh routed items into **{posted_count}** regular news channel(s)."
        count_text = self._format_counts(report.get("counts", {}))
        if count_text:
            message += f"\n\nFound by regular news channel:\n{count_text}"
        if missing_channels:
            message += "\n⚠️ Missing channels: " + ", ".join(f"#{name}" for name in missing_channels)
        await ctx.send(message)

    async def _send_channel_report(self, guild, report, filter_seen):
        posted_count = 0
        missing_channels = []

        for channel_name, items in report.get("channels", {}).items():
            if not items:
                continue

            channel = self._find_text_channel(guild, channel_name)
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
            await channel.send(
                content=self._mobile_preview(channel_name, items_to_post),
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            posted_count += 1

        return posted_count, missing_channels

    def _build_news_embed(self, report):
        category = report.get("category", "all")
        items = report.get("items", [])
        embed = discord.Embed(
            title=self._title_for_category(category),
            description="Fresh routed headlines for the regular news channels.",
            color=discord.Color.blue(),
        )

        if not items:
            embed.add_field(
                name="No fresh items found",
                value="MarketOps did not find a matching item in the current freshness window.",
                inline=False,
            )
        else:
            for index, item in enumerate(items, start=1):
                embed.add_field(
                    name=f'{index}. {item.get("source", "News")} • {item.get("importance", "")}',
                    value=self._format_item(item),
                    inline=False,
                )

        embed.set_footer(text=f'Checked {report.get("updated", "Unknown")} • Provider: {report.get("provider_used", "Unknown")} • {VERSION}')
        return embed

    def _format_item(self, item):
        title = discord.utils.escape_markdown(item.get("title", "Untitled"))
        link = self._clean_link(item.get("link", ""))
        provider = item.get("provider", "Unknown")
        trusted_badge = "✅ Trusted" if item.get("trusted") else "⚠️ Chatter / verify first"
        read_line = f"Open: [Read full item](<{link}>)\n" if link else ""

        value = (
            f"**{title}**\n"
            f"{read_line}"
            f"Source: {trusted_badge} • Provider: **{provider}**\n"
            f"Published: **{item.get('published_label', 'Unknown')}** ({item.get('age_label', 'Unknown')})"
        )
        return value[:997] + "..." if len(value) > 1000 else value

    def _mobile_preview(self, category, items):
        if not items:
            return None

        first = items[0]
        title = self._safe_mobile_text(first.get("title", "Untitled"))
        source = self._safe_mobile_text(first.get("source", "News"))
        channel = first.get("channel") or str(category or "")
        emoji = self._channel_emoji(channel)
        extra = f" +{len(items) - 1} more" if len(items) > 1 else ""

        # Keep this line plain text. No URL here, so mobile does not show ugly link popups.
        return f"{emoji} MarketOps: {source} — {title[:140]}{extra}"

    def _safe_mobile_text(self, value):
        text = str(value or "").replace("\n", " ").replace("\r", " ").strip()
        text = text.replace("@", "@\u200b")
        return " ".join(text.split())

    def _channel_emoji(self, channel):
        channel = str(channel or "").lower()
        if "breaking" in channel or "market" in channel:
            return "🚨"
        if "general" in channel:
            return "🗞️"
        if "ai" in channel or "tech" in channel:
            return "🤖"
        if "fed" in channel or "rate" in channel:
            return "🏦"
        if "geo" in channel or "oil" in channel:
            return "🛢️"
        if "crypto" in channel or "bitcoin" in channel:
            return "₿"
        if "reddit" in channel:
            return "🧵"
        return "📰"

    def _build_help_embed(self):
        embed = discord.Embed(title="📰 MarketOps News Help", description=self.news.category_help(), color=discord.Color.gold())
        embed.add_field(name="Live Auto-Posting", value="MarketOps checks for fresh items and routes them into regular news channels. Use `!news live` for status.", inline=False)
        embed.add_field(name="Mobile Notifications", value="Auto-posts include a clean plain-text headline before the embed so Discord mobile shows the headline.", inline=False)
        embed.add_field(name="Clean Cards", value="News cards show headline, source, provider, and time only. Routing/tags stay internal.", inline=False)
        embed.add_field(name="Separate Feeds", value="X/video/trending posts use `!social`, `!xnews`, `!videonews`, and `!trending` in their own channels.", inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _build_channel_map_embed(self):
        embed = discord.Embed(title="🧭 MarketOps News Channel Routing", description=self.news.channel_map_text(), color=discord.Color.gold())
        embed.add_field(name="Manual channel post", value="Type `!news post` to send current fresh items into regular news channels only.", inline=False)
        embed.add_field(name="Rule", value="Sports/entertainment noise is blocked. AI goes to `#ai-news` only when the headline has actual AI/chip/GPU/data-center context.", inline=False)
        embed.add_field(name="Clean Display", value="Tags and route lines are hidden from public posts because the bot handles that internally.", inline=False)
        embed.add_field(name="Separate Channels", value="Regular news does not post to `#x-news`, `#video-news`, or `#trending-news`.", inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _build_sources_embed(self):
        embed = discord.Embed(title="✅ MarketOps News Source Policy", description=self.news.source_policy(), color=discord.Color.green())
        embed.add_field(name="Freshness Rule", value=self.news.freshness_policy(), inline=False)
        embed.add_field(name="Provider Setup", value="Marketaux runs first when available. Trusted RSS fallback includes Reuters plus major-source data points like AP/NPR/CNBC/BBC/Yahoo Finance. Reddit routes to `#reddit-hot` only.", inline=False)
        embed.add_field(
            name="Recommended .env Settings",
            value="`NEWS_MAX_AGE_HOURS=1`\n`NEWS_LOOKBACK=2h`\n`NEWS_POLL_MINUTES=15`\n`NEWS_FALLBACK_RSS=true`\n`NEWS_INCLUDE_MAJOR_SOURCES=true`\n`NEWS_REUTERS_ONLY=false`\n`REDDIT_SUBREDDITS=stocks`\n`REDDIT_CACHE_MINUTES=30`",
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

        embed = discord.Embed(title="🧪 MarketOps News Debug", description="Shows how many fresh items MarketOps found for each regular news route.", color=discord.Color.gold())
        embed.add_field(name="Counts by Channel", value=self._format_counts(counts) or "No fresh items found.", inline=False)
        embed.add_field(name="Last Feed Check", value=self._last_check, inline=True)
        embed.add_field(name="Provider Used", value=self._last_provider_used, inline=True)
        embed.add_field(name="Freshness Policy", value=report.get("freshness_policy", self.news.freshness_policy()), inline=False)
        embed.set_footer(text=f'Checked {report.get("updated", "Unknown")} • {VERSION}')
        return embed

    def _build_live_status_embed(self):
        status = "ON" if self.auto_post_enabled else "OFF"
        embed = discord.Embed(
            title="🟢 MarketOps Live News Monitor",
            description="Automatic fresh routing status for regular news channels only.",
            color=discord.Color.green() if self.auto_post_enabled else discord.Color.red(),
        )
        embed.add_field(name="Auto-posting", value=f"**{status}**", inline=True)
        embed.add_field(name="Poll Rate", value=f"Every **{self.poll_minutes:g} minute(s)**", inline=True)
        embed.add_field(name="Seen Items", value=f"**{len(self.seen_news)}** tracked", inline=True)
        embed.add_field(name="Last Feed Check", value=self._last_check, inline=True)
        embed.add_field(name="Provider Used", value=self._last_provider_used, inline=True)
        embed.add_field(name="Last Auto Post", value=f"{self._last_auto_post} ({self._last_auto_post_count} channel updates)", inline=True)
        embed.add_field(name="Current Counts", value=self._format_counts(self._last_counts) or "No check completed yet.", inline=False)
        embed.add_field(name="Freshness Policy", value=self.news.freshness_policy(), inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _format_counts(self, counts):
        if not counts:
            return ""
        ordered = ["breaking-news", "general-news", "ai-news", "fed", "geopolitics", "crypto", "reddit-hot"]
        lines = []
        for channel in ordered:
            if channel in counts:
                lines.append(f"• `#{channel}` — **{counts[channel]}** item(s)")
        for channel, count in counts.items():
            if channel not in ordered:
                lines.append(f"• `#{channel}` — **{count}** item(s)")
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
            "usa": "🗞 General News",
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
            "reddit": "🧵 Reddit Hot",
            "reddits": "🧵 Reddit Hot",
            "reddit-hot": "🧵 Reddit Hot",
            "social": "🧵 Reddit Hot",
        }
        return titles.get(category, f"📰 MarketOps News — {category}")

    def _find_text_channel(self, guild, target_name):
        target = self._clean_channel_name(target_name)
        for channel in guild.text_channels:
            if self._clean_channel_name(channel.name).endswith(target):
                return channel
        return None

    def _clean_channel_name(self, channel_name):
        cleaned = (channel_name or "").strip().lower()
        for separator in ("|", "┃", "│"):
            if separator in cleaned:
                cleaned = cleaned.split(separator)[-1].strip()
        while cleaned and not cleaned[0].isalnum():
            cleaned = cleaned[1:].strip()
        return cleaned.replace(" ", "-")

    def _clean_link(self, link):
        return (link or "").replace(" ", "%20").strip()

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
