import asyncio
import os
from time import monotonic

import discord
from discord import app_commands
from discord.ext import commands, tasks

from market.watchlist_engine import WatchlistEngine


VERSION = "MarketOps v1.1"


class Watchlist(commands.Cog):
    """Discord commands and auto-posting for watchlist alerts."""

    def __init__(self, bot):
        self.bot = bot
        self.watchlist = WatchlistEngine()
        self.auto_enabled = self._env_bool("WATCHLIST_AUTO_POST", default=True)
        self.channel_name = os.getenv("WATCHLIST_CHANNEL", "watchlist")
        self.poll_minutes = float(os.getenv("WATCHLIST_POLL_MINUTES", "15"))
        self._last_poll = 0.0
        self._last_check = "Not checked yet"
        self._last_alert_count = 0

        if self.auto_enabled and not self.watchlist_loop.is_running():
            self.watchlist_loop.start()

    def cog_unload(self):
        if self.watchlist_loop.is_running():
            self.watchlist_loop.cancel()

    @app_commands.command(
        name="watchlist",
        description="View your MarketOps watchlist.",
    )
    async def watchlist_slash(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        try:
            report = await asyncio.to_thread(self.watchlist.get_watchlist_report)
            await interaction.followup.send(embed=self._build_watchlist_embed(report))
        except Exception as error:
            print(f"❌ /watchlist error: {error}")
            await interaction.followup.send(
                "⚠️ MarketOps had trouble loading the watchlist. Check the terminal for the error.",
                ephemeral=True,
            )

    @app_commands.command(
        name="alerts",
        description="Scan your watchlist for active alerts.",
    )
    async def alerts_slash(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        try:
            report = await asyncio.to_thread(self.watchlist.scan_alerts, True)
            await interaction.followup.send(embed=self._build_alerts_embed(report))
        except Exception as error:
            print(f"❌ /alerts error: {error}")
            await interaction.followup.send(
                "⚠️ MarketOps had trouble scanning alerts. Check the terminal for the error.",
                ephemeral=True,
            )

    @commands.command(name="watchlist")
    async def watchlist_prefix(self, ctx):
        """Desktop/web fallback command. Type !watchlist."""
        try:
            report = await asyncio.to_thread(self.watchlist.get_watchlist_report)
            await ctx.send(embed=self._build_watchlist_embed(report))
        except Exception as error:
            print(f"❌ !watchlist error: {error}")
            await ctx.send("⚠️ MarketOps had trouble loading the watchlist. Check the terminal for the error.")

    @commands.command(name="alerts")
    async def alerts_prefix(self, ctx):
        """Desktop/web fallback command. Type !alerts."""
        try:
            report = await asyncio.to_thread(self.watchlist.scan_alerts, True)
            await ctx.send(embed=self._build_alerts_embed(report))
        except Exception as error:
            print(f"❌ !alerts error: {error}")
            await ctx.send("⚠️ MarketOps had trouble scanning alerts. Check the terminal for the error.")

    @tasks.loop(seconds=30)
    async def watchlist_loop(self):
        await self.bot.wait_until_ready()

        elapsed_seconds = monotonic() - self._last_poll
        poll_seconds = self.poll_minutes * 60

        if elapsed_seconds < poll_seconds:
            return

        self._last_poll = monotonic()

        try:
            report = await asyncio.to_thread(self.watchlist.scan_alerts, False)
            self._last_check = report.get("updated", "Unknown")
            alerts = report.get("alerts", [])
            self._last_alert_count = len(alerts)

            if not alerts:
                return

            for guild in self.bot.guilds:
                channel = discord.utils.get(guild.text_channels, name=self.channel_name)
                if channel is None:
                    print(f"⚠️ Missing watchlist channel in {guild.name}: #{self.channel_name}")
                    continue

                await channel.send(embed=self._build_alerts_embed(report))

        except Exception as error:
            print(f"❌ Watchlist loop error: {error}")

    def _build_watchlist_embed(self, report):
        embed = discord.Embed(
            title="📌 MarketOps Watchlist",
            description="Symbols MarketOps is watching for bigger moves and fresh headlines.",
            color=discord.Color.blue(),
        )

        quotes = report.get("quotes", [])

        if not quotes:
            embed.add_field(
                name="No symbols found",
                value="Add WATCHLIST_SYMBOLS to your .env file.",
                inline=False,
            )
        else:
            value = "\n".join(item["line"] for item in quotes[:15])
            embed.add_field(name="Current Watchlist", value=value, inline=False)

        embed.add_field(
            name="Price Alert Rule",
            value=f'Alert when a symbol moves **±{report.get("move_threshold", 3):g}%** or more.',
            inline=False,
        )
        embed.add_field(
            name="News Alert Rule",
            value="Ticker/company headlines are scanned when WATCHLIST_NEWS_ALERTS=true.",
            inline=False,
        )

        embed.set_footer(text=f'Updated {report.get("updated", "Unknown")} • {VERSION}')
        return embed

    def _build_alerts_embed(self, report):
        embed = discord.Embed(
            title="🚨 MarketOps Watchlist Alerts",
            description="Price moves and fresh ticker headlines from your watchlist.",
            color=discord.Color.red(),
        )

        alerts = report.get("alerts", [])

        if not report.get("enabled", True):
            embed.add_field(
                name="Watchlist disabled",
                value="Set WATCHLIST_ENABLED=true in .env to turn it on.",
                inline=False,
            )
        elif not alerts:
            embed.add_field(
                name="No active alerts",
                value=(
                    f'No symbol moved ±{report.get("move_threshold", 3):g}% or more, '
                    "and no fresh ticker headline was found right now."
                ),
                inline=False,
            )
        else:
            for alert in alerts[:10]:
                if alert.get("type") == "news":
                    embed.add_field(
                        name=f'📰 {alert["symbol"]} News Alert',
                        value=self._format_news_alert(alert),
                        inline=False,
                    )
                else:
                    embed.add_field(
                        name=f'{alert["emoji"]} {alert["symbol"]} Price Alert',
                        value=f'{alert["message"]}\nWatch: {alert["watch"]}',
                        inline=False,
                    )

        embed.add_field(
            name="News Provider",
            value=report.get("news_provider", "Not checked yet"),
            inline=False,
        )
        embed.set_footer(text=f'Checked {report.get("updated", "Unknown")} • {VERSION}')
        return embed

    def _format_news_alert(self, alert):
        link = alert.get("link", "")
        open_line = f"\n[Read headline]({link})" if link else ""
        return (
            f'{alert["message"]}\n'
            f'Source: {alert.get("source", "Unknown")} • '
            f'Provider: {alert.get("provider", "Unknown")} • '
            f'Age: {alert.get("age", "Unknown")}\n'
            f'Watch: {alert["watch"]}'
            f'{open_line}'
        )

    def _env_bool(self, name, default=False):
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in ("1", "true", "yes", "y", "on")


async def setup(bot):
    await bot.add_cog(Watchlist(bot))
