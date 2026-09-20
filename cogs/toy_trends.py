import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord.ext import commands, tasks

from providers.toy_trend_provider import ToyTrendProvider


class ToyTrends(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.provider = ToyTrendProvider()
        self.channel_id = os.getenv("TOY_TRENDS_CHANNEL_ID", "").strip()
        self.minutes = max(15, int(os.getenv("TOY_TRENDS_CHECK_MINUTES", "30")))
        self.state_file = Path("data/toy_trends_state.json")
        self.state = self._load()
        self.last_error = "None"
        self.monitor.change_interval(minutes=self.minutes)
        self.monitor.start()

    def cog_unload(self):
        self.monitor.cancel()

    @tasks.loop(minutes=30)
    async def monitor(self):
        await self.bot.wait_until_ready()
        await self._scan()

    @monitor.before_loop
    async def before_monitor(self):
        await self.bot.wait_until_ready()

    @commands.command(name="toytrends", aliases=["trendwatch", "toyheadlines"])
    async def toy_trends(self, ctx, action="status"):
        if action.lower() in {"now", "scan", "test"}:
            await ctx.send("🔎 Checking toy, licensing, TikTok/viral and new-release headlines…")
            posted = await self._scan(force=True)
            await ctx.send(f"{'✅' if self.last_error == 'None' else '❌'} Toy trend scan: {posted} posted • {self.last_error}")
            return
        channel = self._channel()
        target = f"#{channel.name}" if channel else "not configured"
        await ctx.send(
            f"**Toy trend headlines**: every {self.minutes} min • channel: {target}\n"
            f"Last scan: {self.state.get('last_scan', 'Not yet')} • Last error: {self.last_error}\n"
            "Headlines are early watch signals; Keepa must confirm an exact ASIN."
        )

    async def _scan(self, force=False):
        channel = self._channel()
        if channel is None:
            self.last_error = "TOY_TRENDS_CHANNEL_ID does not resolve to a visible channel"
            return 0
        permissions = channel.permissions_for(channel.guild.me)
        if not (permissions.view_channel and permissions.send_messages and permissions.embed_links):
            self.last_error = f"Missing View Channel, Send Messages, or Embed Links in #{channel.name}"
            return 0
        try:
            items = await asyncio.to_thread(self.provider.latest, 25)
            posted = 0
            seen = self.state.setdefault("seen", {})
            for item in reversed(items):
                signature = item["link"]
                if not force and signature in seen:
                    continue
                embed = discord.Embed(
                    title=item["title"][:256], url=item["link"], color=discord.Color.purple(),
                    description="Early demand catalyst for manual review—not yet a confirmed Amazon profit lead.",
                )
                embed.add_field(name="Next check", value="Find exact ASINs, then verify 7/30/90-day rank, Amazon stock cycling, price movement and seller trend.", inline=False)
                embed.set_footer(text=f"Source: {item['source']} • MarketOps Toy Trend Watch")
                await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                seen[signature] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                posted += 1
                if posted >= 8:
                    break
            # Keep state bounded on a persistent Railway volume.
            if len(seen) > 1500:
                self.state["seen"] = dict(list(seen.items())[-1000:])
            self.state["last_scan"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.last_error = "None"
            self._save()
            return posted
        except Exception as error:
            self.last_error = str(error)[:240]
            return 0

    def _channel(self):
        return self.bot.get_channel(int(self.channel_id)) if self.channel_id.isdigit() else None

    def _load(self):
        try:
            return json.loads(self.state_file.read_text()) if self.state_file.exists() else {}
        except Exception:
            return {}

    def _save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.state, indent=2))


async def setup(bot):
    await bot.add_cog(ToyTrends(bot))
