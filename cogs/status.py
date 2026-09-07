import os
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

from market.watchlist_engine import WatchlistEngine


VERSION = "MarketOps v2.4.1"
PT_ZONE = ZoneInfo("America/Los_Angeles")


class Status(commands.Cog):
    """Bot health/status command.

    Plain English: this cog answers "what is running right now?" so the user
    does not have to remember every setting or guess whether the bot is alive.
    """

    def __init__(self, bot):
        self.bot = bot
        self.started_at = datetime.now(PT_ZONE)
        self.watchlist = WatchlistEngine()
        self.status_channel_name = os.getenv("BOT_STATUS_CHANNEL", "bot-status").strip()
        self._startup_posted = False

    @commands.Cog.listener()
    async def on_ready(self):
        """Post one startup message to #bot-status when the bot comes online."""
        if self._startup_posted:
            return

        self._startup_posted = True

        for guild in self.bot.guilds:
            channel = discord.utils.get(guild.text_channels, name=self.status_channel_name)
            if channel is None:
                print(f"⚠️ Missing bot status channel in {guild.name}: #{self.status_channel_name}")
                continue

            try:
                await channel.send(embed=self._build_startup_embed())
            except Exception as error:
                print(f"❌ Startup status message error: {error}")

    @commands.command(name="status")
    async def status_prefix(self, ctx):
        """Show bot version, uptime, and active settings. Type !status."""
        await ctx.send(embed=self._build_status_embed())

    def _build_startup_embed(self):
        embed = discord.Embed(
            title="✅ MarketOps Started",
            description="Bot is online and ready.",
            color=discord.Color.green(),
        )
        embed.add_field(name="Version", value=VERSION, inline=True)
        embed.add_field(name="Started", value=self._started_text(), inline=True)
        embed.add_field(name="Process ID", value=str(os.getpid()), inline=True)
        embed.add_field(name="Quick Check", value="Type `!status` in `#bot-status` or `!commands` anywhere.", inline=False)
        embed.add_field(
            name="Duplicate Warning",
            value="If replies double again, another `bot.py` process is running. Use the safe restart command.",
            inline=False,
        )
        embed.set_footer(text=VERSION)
        return embed

    def _build_status_embed(self):
        watch_status = self.watchlist.get_status(
            auto_enabled=self._env_bool("WATCHLIST_AUTO_POST", default=True),
            channel_name=os.getenv("WATCHLIST_CHANNEL", "watchlist"),
            poll_minutes=float(os.getenv("WATCHLIST_POLL_MINUTES", "15")),
        )

        brief_status = "ON" if self._env_bool("BRIEF_AUTO_POST", default=False) else "OFF"
        brief_channel = os.getenv("BRIEF_CHANNEL", "morning-brief")
        brief_times = os.getenv("BRIEF_TIMES_PT", os.getenv("BRIEF_TIME_PT", "05:30,09:30,13:15"))

        embed = discord.Embed(
            title="🟢 MarketOps Status",
            description="Quick health check for the bot and your active settings.",
            color=discord.Color.green(),
        )
        embed.add_field(name="Version", value=VERSION, inline=True)
        embed.add_field(name="Uptime", value=self._uptime_text(), inline=True)
        embed.add_field(name="Current PT Time", value=self._now_text(), inline=True)
        embed.add_field(name="Brief Auto-Post", value=brief_status, inline=True)
        embed.add_field(name="Brief Channel", value=f"#{brief_channel}", inline=True)
        embed.add_field(name="Brief Times PT", value=brief_times, inline=True)
        embed.add_field(name="Watchlist Alerts", value="ON" if watch_status.get("enabled") else "OFF", inline=True)
        embed.add_field(name="News Alerts", value="ON" if watch_status.get("news_enabled") else "OFF", inline=True)
        embed.add_field(name="Threshold", value=f'±{watch_status.get("move_threshold", 3):g}%', inline=True)
        embed.add_field(name="Watchlist Channel", value=f'#{watch_status.get("channel_name", "watchlist")}', inline=True)
        embed.add_field(name="Poll Time", value=f'{watch_status.get("poll_minutes", 15):g} minutes', inline=True)
        embed.add_field(name="Process ID", value=str(os.getpid()), inline=True)
        embed.add_field(name="Loaded Cogs", value=self._loaded_cogs_text(), inline=False)
        embed.add_field(
            name="Command Reminder",
            value="Type `!commands` anywhere for the full command guide.",
            inline=False,
        )
        embed.set_footer(text=f'Checked {self._now_text()} • {VERSION}')
        return embed

    def _loaded_cogs_text(self):
        names = sorted(self.bot.cogs.keys())
        return ", ".join(names) if names else "No cogs loaded"

    def _started_text(self):
        return self.started_at.strftime("%I:%M %p PT").lstrip("0")

    def _now_text(self):
        return datetime.now(PT_ZONE).strftime("%I:%M %p PT").lstrip("0")

    def _uptime_text(self):
        delta = datetime.now(PT_ZONE) - self.started_at
        total_seconds = int(delta.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"

    def _env_bool(self, name, default=False):
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in ("1", "true", "yes", "y", "on")


async def setup(bot):
    await bot.add_cog(Status(bot))
