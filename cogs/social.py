import asyncio
import hashlib
import json
import os
from pathlib import Path
from time import monotonic

import discord
from discord.ext import commands, tasks

from providers.social_provider import SocialProvider


VERSION = "MarketOps Social v1.0.1"


class SocialMonitor(commands.Cog):
    """X/social/video monitor for MarketOps.

    Plain English: this is separate from the normal news monitor. It posts raw
    X account posts and video-news items into the social/video channels only.
    """

    def __init__(self, bot):
        self.bot = bot
        self.provider = SocialProvider()
        self.enabled = self._env_bool("SOCIAL_MONITOR_ENABLED", default=True)
        self.poll_minutes = float(os.getenv("SOCIAL_POLL_MINUTES", "5"))
        self.max_posts_per_channel = int(os.getenv("SOCIAL_MAX_POSTS_PER_CHANNEL", "3"))
        self.x_channel = os.getenv("SOCIAL_X_CHANNEL", "x-news")
        self.video_channel = os.getenv("SOCIAL_VIDEO_CHANNEL", "video-news")
        self.trending_channel = os.getenv("SOCIAL_TRENDING_CHANNEL", "trending-news")
        self.trending_auto_post = self._env_bool("SOCIAL_TRENDING_AUTO_POST", default=False)
        self.seen_file = Path("data/seen_social.json")
        self.seen_items = self._load_seen_items()
        self._last_poll = 0.0
        self._last_check = "Not checked yet"
        self._last_auto_post = "Not posted yet"
        self._last_auto_post_count = 0

        if self.enabled and not self.social_loop.is_running():
            self.social_loop.start()

    def cog_unload(self):
        if self.social_loop.is_running():
            self.social_loop.cancel()

    @commands.command(name="social", aliases=["socialstatus", "xstatus"])
    async def social_prefix(self, ctx):
        await ctx.send(embed=self._status_embed())

    @commands.command(name="xnews", aliases=["xposts", "twitternews"])
    async def xnews_prefix(self, ctx):
        items = await asyncio.to_thread(self.provider.get_latest_items, 10, "x")
        await ctx.send(
            content=self._mobile_preview("x", items),
            embed=self._items_embed("𝕏 X / Public Account Posts", items),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="videonews", aliases=["videos", "newsvideos"])
    async def videonews_prefix(self, ctx):
        items = await asyncio.to_thread(self.provider.get_latest_items, 8, "video")
        await ctx.send(
            content=self._mobile_preview("video", items),
            embed=self._items_embed("🎥 Video News", items),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="trending", aliases=["trendnews", "socialnews"])
    async def trending_prefix(self, ctx):
        items = await asyncio.to_thread(self.provider.get_latest_items, 10, "trending")
        await ctx.send(
            content=self._mobile_preview("trending", items),
            embed=self._items_embed("🔥 X Trending / Fast-Moving Posts", items),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="socialpost", aliases=["xpost", "videopost"])
    async def socialpost_prefix(self, ctx):
        if ctx.guild is None:
            await ctx.send("⚠️ Social posting only works inside a Discord server.")
            return

        items = await asyncio.to_thread(self.provider.get_latest_items, 25, "all")
        trending_items = await asyncio.to_thread(self.provider.get_latest_items, 10, "trending")
        posted, missing = await self._send_routed_items(ctx.guild, items + trending_items, filter_seen=False, include_trending=True)
        message = f"✅ Posted social/video items into **{posted}** social channel(s)."
        if missing:
            message += "\n⚠️ Missing channels: " + ", ".join(f"#{name}" for name in missing)
        await ctx.send(message)

    @tasks.loop(seconds=30)
    async def social_loop(self):
        await self.bot.wait_until_ready()
        if not self.enabled:
            return

        elapsed_seconds = monotonic() - self._last_poll
        if elapsed_seconds < self.poll_minutes * 60:
            return
        self._last_poll = monotonic()

        try:
            items = await asyncio.to_thread(self.provider.get_latest_items, 25, "all")
            if self.trending_auto_post:
                trending_items = await asyncio.to_thread(self.provider.get_latest_items, 10, "trending")
                items.extend(trending_items)
            self._last_check = self.provider.last_status

            if not self.seen_items:
                self._mark_seen(items)
                self._save_seen_items()
                print("📱 Social/video monitor seeded current items. New items will auto-post after this.")
                return

            total_posted = 0
            for guild in self.bot.guilds:
                posted, missing = await self._send_routed_items(
                    guild,
                    items,
                    filter_seen=True,
                    include_trending=self.trending_auto_post,
                )
                total_posted += posted
                if missing:
                    print(f"⚠️ Missing social/video channels in {guild.name}: {', '.join(missing)}")

            self._last_auto_post_count = total_posted
            if total_posted:
                self._last_auto_post = self.provider.last_status
                print(f"📱 Auto-posted social/video items into {total_posted} channel(s).")
            self._save_seen_items()
        except Exception as error:
            print(f"❌ Social/video loop error: {error}")

    @social_loop.before_loop
    async def before_social_loop(self):
        await self.bot.wait_until_ready()

    async def _send_routed_items(self, guild, items, filter_seen, include_trending=False):
        grouped = {
            self.x_channel: [],
            self.video_channel: [],
        }
        if include_trending:
            grouped[self.trending_channel] = []

        for item in items:
            item_id = self._item_id(item)
            if filter_seen and item_id in self.seen_items:
                continue
            self.seen_items.add(item_id)

            if item.get("type") == "x":
                grouped[self.x_channel].append(item)
            elif item.get("type") == "video":
                grouped[self.video_channel].append(item)
            elif include_trending and item.get("type") == "trending":
                grouped[self.trending_channel].append(item)

        posted = 0
        missing = []
        for channel_name, channel_items in grouped.items():
            channel_items = channel_items[: self.max_posts_per_channel]
            if not channel_items:
                continue
            channel = self._find_text_channel(guild, channel_name)
            if channel is None:
                missing.append(channel_name)
                continue
            await channel.send(
                content=self._mobile_preview(channel_name, channel_items),
                embed=self._items_embed(self._title_for_channel(channel_name), channel_items),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            posted += 1
        return posted, missing

    def _status_embed(self):
        embed = discord.Embed(
            title="📱 MarketOps Social / Video Monitor",
            description="Separate feed for raw X account posts and video clips. It does not mix with normal news channels.",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Monitor", value="ON" if self.enabled else "OFF", inline=True)
        embed.add_field(name="Poll Rate", value=f"Every {self.poll_minutes:g} minute(s)", inline=True)
        embed.add_field(
            name="Channels",
            value=f"X: `#{self.x_channel}`\nVideo: `#{self.video_channel}`\nTrending: `#{self.trending_channel}`",
            inline=False,
        )
        embed.add_field(name="Provider Status", value=self.provider.status_text()[:1024], inline=False)
        embed.add_field(name="Commands", value="`!xnews` • `!videonews` • `!trending` • `!socialpost` • `!social`", inline=False)
        embed.add_field(name="Rule", value="Normal `!news` posts do not route into `#x-news`, `#video-news`, or `#trending-news`.", inline=False)
        embed.add_field(name="Last Auto Post", value=f"{self._last_auto_post} ({self._last_auto_post_count} channel update(s))", inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _items_embed(self, title, items):
        embed = discord.Embed(
            title=title,
            description="Raw public-source feed. No extra decoding added.",
            color=discord.Color.gold(),
        )
        if not items:
            embed.add_field(name="No fresh items", value="No fresh matching social/video items found in the current window.", inline=False)
        else:
            for index, item in enumerate(items[:6], start=1):
                embed.add_field(name=f"{index}. {item.get('source', 'Source')}", value=self._item_value(item), inline=False)
        embed.set_footer(text=f"{self.provider.last_status} • {VERSION}")
        return embed

    def _item_value(self, item):
        title = discord.utils.escape_markdown(self._safe_text(item.get("title", "Untitled")))
        link = self._clean_link(item.get("link", ""))
        unix = self._unix_time(item)
        time_line = f"<t:{unix}:f> (<t:{unix}:R>)" if unix else "Unknown time"
        open_line = f"\nOpen: [View item](<{link}>)" if link else ""
        metrics_line = self._metrics_line(item)
        value = (
            f"**{title[:360]}**\n"
            f"Provider: **{item.get('provider', 'Unknown')}**\n"
            f"Published: {time_line}"
            f"{metrics_line}"
            f"{open_line}"
        )
        return value[:997] + "..." if len(value) > 1000 else value

    def _metrics_line(self, item):
        metrics = item.get("metrics") or {}
        if not metrics:
            return ""
        return (
            f"\nMetrics: {metrics.get('like_count', 0)} likes • "
            f"{metrics.get('retweet_count', 0)} reposts • "
            f"{metrics.get('reply_count', 0)} replies"
        )

    def _mobile_preview(self, category, items):
        if not items:
            return None
        first = items[0]
        emoji = "𝕏" if first.get("type") == "x" else "🔥" if first.get("type") == "trending" else "🎥" if first.get("type") == "video" else "📱"
        source = self._safe_text(first.get("source", "Social"))
        title = self._safe_text(first.get("title", "Untitled"))[:130]
        extra = f" +{len(items) - 1} more" if len(items) > 1 else ""
        return f"{emoji} MarketOps: {source} — {title}{extra}"

    def _title_for_channel(self, channel_name):
        cleaned = self._clean_channel_name(channel_name)
        if "x-news" in cleaned:
            return "𝕏 X / Public Account Posts"
        if "video" in cleaned:
            return "🎥 Video News"
        if "trending" in cleaned:
            return "🔥 X Trending / Fast-Moving Posts"
        return "📱 Social / Video Watch"

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

    def _safe_text(self, value):
        return " ".join(str(value or "").replace("@", "@\u200b").replace("\n", " ").split())

    def _clean_link(self, link):
        return str(link or "").replace(" ", "%20").strip()

    def _unix_time(self, item):
        published_dt = item.get("published_dt")
        try:
            return int(published_dt.timestamp()) if published_dt else None
        except Exception:
            return None

    def _item_id(self, item):
        base = item.get("link") or f'{item.get("source", "")}::{item.get("title", "")}'
        return hashlib.sha256(base.encode("utf-8")).hexdigest()

    def _mark_seen(self, items):
        for item in items:
            self.seen_items.add(self._item_id(item))

    def _load_seen_items(self):
        if not self.seen_file.exists():
            return set()
        try:
            with self.seen_file.open("r", encoding="utf-8") as file:
                data = json.load(file)
            return set(data if isinstance(data, list) else [])
        except Exception:
            return set()

    def _save_seen_items(self):
        self.seen_file.parent.mkdir(parents=True, exist_ok=True)
        trimmed = list(self.seen_items)[-750:]
        with self.seen_file.open("w", encoding="utf-8") as file:
            json.dump(trimmed, file, indent=2)

    def _env_bool(self, name, default=False):
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in ("1", "true", "yes", "y", "on")


async def setup(bot):
    await bot.add_cog(SocialMonitor(bot))
