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
from market.news_patch import apply_news_routing_patch

apply_news_routing_patch()

VERSION = "MarketOps v0.8.0"


class News(commands.Cog):
    """Clean, strict MarketOps news routing."""

    def __init__(self, bot):
        self.bot = bot
        self.news = NewsEngine()
        self.auto_post_enabled = self._env_bool("NEWS_AUTO_POST", True)
        self.poll_minutes = float(os.getenv("NEWS_POLL_MINUTES", "15"))
        self.seen_file = Path("data/seen_news.json")
        self.seen_news = self._load_seen_news()
        self._last_poll = 0.0
        self._last_check = "Not checked yet"
        self._last_counts = {}
        self._last_provider_used = "Not checked yet"
        if self.auto_post_enabled and not self.auto_news_loop.is_running():
            self.auto_news_loop.start()

    def cog_unload(self):
        if self.auto_news_loop.is_running():
            self.auto_news_loop.cancel()

    @app_commands.command(name="news", description="View fresh MarketOps headlines.")
    @app_commands.describe(category="Choose a news category.")
    @app_commands.choices(category=[
        app_commands.Choice(name="all", value="all"),
        app_commands.Choice(name="breaking", value="market"),
        app_commands.Choice(name="general", value="general"),
        app_commands.Choice(name="AI / tech", value="ai"),
        app_commands.Choice(name="Fed / rates", value="fed"),
        app_commands.Choice(name="oil / geopolitics", value="geo"),
        app_commands.Choice(name="crypto", value="crypto"),
    ])
    async def news_slash(self, interaction: discord.Interaction, category: app_commands.Choice[str] = None):
        await interaction.response.defer(thinking=True)
        selected = category.value if category else "all"
        report = await asyncio.to_thread(self.news.get_top_news, limit=5, category=selected)
        await interaction.followup.send(content=self._mobile_preview(selected, report.get("items", [])), embed=self._build_news_embed(report), allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="news")
    async def news_prefix(self, ctx, category="all"):
        category = (category or "all").lower().strip()
        if category in ("channels", "channel"):
            await ctx.send(embed=self._build_channel_map_embed())
            return
        if category in ("debug", "counts", "count"):
            await ctx.send(embed=await self._build_debug_embed())
            return
        if category in ("live", "status"):
            await ctx.send(embed=self._build_live_status_embed())
            return
        if category in ("post", "posts", "route", "send"):
            await self._post_news_to_channels(ctx)
            return
        if category in ("sources", "source"):
            await ctx.send(embed=self._build_sources_embed())
            return
        report = await asyncio.to_thread(self.news.get_top_news, limit=5, category=category)
        await ctx.send(content=self._mobile_preview(category, report.get("items", [])), embed=self._build_news_embed(report), allowed_mentions=discord.AllowedMentions.none())

    @tasks.loop(seconds=15)
    async def auto_news_loop(self):
        await self.bot.wait_until_ready()
        if monotonic() - self._last_poll < self.poll_minutes * 60:
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
                return
            for guild in self.bot.guilds:
                await self._send_channel_report(guild, report, filter_seen=True)
            self._save_seen_news()
        except Exception as error:
            print(f"❌ Auto news loop error: {error!r}")

    async def _post_news_to_channels(self, ctx):
        if ctx.guild is None:
            await ctx.send("⚠️ This command only works inside the server.")
            return
        report = await asyncio.to_thread(self.news.get_channel_reports, limit_per_channel=3)
        posted, missing = await self._send_channel_report(ctx.guild, report, filter_seen=False)
        message = f"✅ Posted fresh routed news into **{posted}** channel(s)."
        if missing:
            message += "\nMissing: " + ", ".join(f"#{x}" for x in missing)
        await ctx.send(message)

    async def _send_channel_report(self, guild, report, filter_seen):
        posted = 0
        missing = []
        for channel_name, items in report.get("channels", {}).items():
            if not items:
                continue
            channel = self._find_text_channel(guild, channel_name)
            if channel is None:
                missing.append(channel_name)
                continue
            send_items = []
            for item in items:
                item_id = self._article_id(item)
                # Allow a genuinely breaking story in breaking-news AND its
                # topical home, but prevent repeats within normal monitoring.
                seen_key = f"{channel_name}:{item_id}"
                if filter_seen and seen_key in self.seen_news:
                    continue
                send_items.append(item)
                self.seen_news.add(seen_key)
            if not send_items:
                continue
            await channel.send(content=self._mobile_preview(channel_name, send_items), embed=self._build_news_embed({"items": send_items, "category": channel_name, "updated": report.get("updated", "Unknown"), "provider_used": report.get("provider_used", "Unknown")}), allowed_mentions=discord.AllowedMentions.none())
            posted += 1
        return posted, missing

    def _build_news_embed(self, report):
        items = report.get("items", [])
        embed = discord.Embed(title=self._title_for_category(report.get("category", "all")), color=discord.Color.blue())
        if not items:
            embed.description = "No fresh matching headlines."
        else:
            for item in items:
                source = item.get("source", "News")
                title = discord.utils.escape_markdown(item.get("title", "Untitled"))
                link = self._clean_link(item.get("link", ""))
                published = item.get("published_label", "Unknown")
                age = item.get("age_label", "Unknown")
                body = f"**{title}**\n"
                if link:
                    body += f"[Read article](<{link}>)\n"
                body += f"{published} • {age}"
                embed.add_field(name=source, value=body[:1000], inline=False)
        embed.set_footer(text=f'{report.get("updated", "Unknown")} • {VERSION}')
        return embed

    def _mobile_preview(self, category, items):
        if not items:
            return None
        first = items[0]
        title = self._safe_mobile_text(first.get("title", "Untitled"))
        source = self._safe_mobile_text(first.get("source", "News"))
        extra = f" +{len(items)-1} more" if len(items) > 1 else ""
        return f"{self._channel_emoji(category)} {source} — {title[:150]}{extra}"

    def _safe_mobile_text(self, value):
        return " ".join(str(value or "").replace("@", "@\u200b").replace("\n", " ").split())

    def _channel_emoji(self, channel):
        channel = str(channel or "").lower()
        if "breaking" in channel or channel == "market": return "🚨"
        if "general" in channel: return "🗞️"
        if "ai" in channel or "tech" in channel: return "🤖"
        if "fed" in channel or "rate" in channel: return "🏦"
        if "geo" in channel or "oil" in channel: return "🛢️"
        if "crypto" in channel or "bitcoin" in channel: return "₿"
        return "📰"

    def _title_for_category(self, category):
        c = str(category or "").lower()
        if "breaking" in c or c == "market": return "🚨 Breaking News"
        if "general" in c: return "🗞️ General News"
        if "ai" in c or "tech" in c: return "🤖 AI / Tech News"
        if "fed" in c or "rate" in c: return "🏦 Fed / Rates News"
        if "geo" in c or "oil" in c: return "🛢️ Oil / Geopolitics News"
        if "crypto" in c or "bitcoin" in c: return "₿ Crypto News"
        return "📰 MarketOps News"

    def _build_channel_map_embed(self):
        embed = discord.Embed(title="🧭 MarketOps Routing", description="One primary topic per story. Breaking is an urgency layer.", color=discord.Color.gold())
        embed.add_field(name="Routes", value="🤖 AI / Tech → `#ai-news`\n🏦 Fed / Rates → `#fed`\n🛢️ Oil / Geopolitics → `#geopolitics`\n₿ Crypto → `#crypto`\n🗞️ Important General → `#general-news`\n🚨 Urgent / market-wide → `#breaking-news` + its topical channel", inline=False)
        embed.add_field(name="Filtered", value="Sports, entertainment, local filler, generic topic pages, stock-pick filler, and weak keyword matches are dropped.", inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _build_sources_embed(self):
        embed = discord.Embed(title="✅ News Sources", description=self.news.source_policy(), color=discord.Color.green())
        embed.add_field(name="Freshness", value=self.news.freshness_policy(), inline=False)
        embed.set_footer(text=VERSION)
        return embed

    async def _build_debug_embed(self):
        report = await asyncio.to_thread(self.news.get_channel_reports, limit_per_channel=5)
        counts = report.get("counts", {})
        text = "\n".join(f"• #{channel} — {count}" for channel, count in counts.items()) or "No fresh items."
        embed = discord.Embed(title="🧪 News Routing Debug", description=text, color=discord.Color.gold())
        embed.set_footer(text=f'{report.get("updated", "Unknown")} • {VERSION}')
        return embed

    def _build_live_status_embed(self):
        status = "ON" if self.auto_post_enabled else "OFF"
        embed = discord.Embed(title="🟢 MarketOps Live News", description=f"Auto-posting: **{status}**\nPoll rate: **{self.poll_minutes:g} minutes**", color=discord.Color.green())
        embed.set_footer(text=VERSION)
        return embed

    def _find_text_channel(self, guild, target_name):
        target = self._clean_channel_name(target_name)
        for channel in guild.text_channels:
            if self._clean_channel_name(channel.name) == target or self._clean_channel_name(channel.name).endswith(target):
                return channel
        return None

    def _clean_channel_name(self, name):
        cleaned = (name or "").strip().lower()
        for separator in ("|", "┃", "│"):
            if separator in cleaned:
                cleaned = cleaned.split(separator)[-1].strip()
        while cleaned and not cleaned[0].isalnum():
            cleaned = cleaned[1:].strip()
        return cleaned.replace(" ", "-")

    def _article_id(self, item):
        raw = f'{item.get("title", "").lower().strip()}|{item.get("link", "").strip()}'
        return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()

    def _all_report_items(self, report):
        items = []
        for channel_name, channel_items in report.get("channels", {}).items():
            for item in channel_items:
                copy = dict(item)
                copy["_seen_channel"] = channel_name
                items.append(copy)
        return items

    def _mark_items_seen(self, items):
        for item in items:
            channel = item.get("_seen_channel", item.get("channel", "unknown"))
            self.seen_news.add(f"{channel}:{self._article_id(item)}")

    def _load_seen_news(self):
        try:
            if not self.seen_file.exists(): return set()
            data = json.loads(self.seen_file.read_text(encoding="utf-8"))
            return set(data if isinstance(data, list) else [])
        except Exception:
            return set()

    def _save_seen_news(self):
        try:
            self.seen_file.parent.mkdir(parents=True, exist_ok=True)
            self.seen_file.write_text(json.dumps(sorted(self.seen_news)[-3000:], indent=2), encoding="utf-8")
        except Exception as error:
            print(f"⚠️ Could not save news cache: {error!r}")

    def _clean_link(self, link):
        return str(link or "").replace("<", "").replace(">", "").strip()

    def _env_bool(self, name, default=False):
        value = os.getenv(name)
        if value is None: return default
        return value.strip().lower() in {"1", "true", "yes", "on"}


async def setup(bot):
    await bot.add_cog(News(bot))
