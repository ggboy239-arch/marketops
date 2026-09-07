import asyncio
import os
from time import monotonic

import discord
from discord import app_commands
from discord.ext import commands, tasks

from market.watchlist_engine import WatchlistEngine


VERSION = "MarketOps v2.0"


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

    @app_commands.command(name="watchlist", description="View your MarketOps watchlist.")
    async def watchlist_slash(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        report = await asyncio.to_thread(self.watchlist.get_watchlist_report)
        await interaction.followup.send(embed=self._build_watchlist_embed(report))

    @app_commands.command(name="alerts", description="Scan your watchlist for active alerts.")
    async def alerts_slash(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        report = await asyncio.to_thread(self.watchlist.scan_alerts, True)
        await interaction.followup.send(embed=self._build_alerts_embed(report))

    @app_commands.command(name="watch", description="Add a ticker to your MarketOps watchlist.")
    async def watch_slash(self, interaction: discord.Interaction, symbol: str):
        await interaction.response.defer(thinking=True)
        result = await asyncio.to_thread(self.watchlist.add_symbol, symbol)
        await interaction.followup.send(embed=self._build_change_embed("➕ Watchlist Updated", result))

    @app_commands.command(name="unwatch", description="Remove a ticker from your MarketOps watchlist.")
    async def unwatch_slash(self, interaction: discord.Interaction, symbol: str):
        await interaction.response.defer(thinking=True)
        result = await asyncio.to_thread(self.watchlist.remove_symbol, symbol)
        await interaction.followup.send(embed=self._build_change_embed("➖ Watchlist Updated", result))

    @commands.command(name="watchlist")
    async def watchlist_prefix(self, ctx):
        try:
            report = await asyncio.to_thread(self.watchlist.get_watchlist_report)
            await ctx.send(embed=self._build_watchlist_embed(report))
        except Exception as error:
            print(f"❌ !watchlist error: {error}")
            await ctx.send("⚠️ MarketOps had trouble loading the watchlist. Check the terminal for the error.")

    @commands.command(name="alerts")
    async def alerts_prefix(self, ctx):
        try:
            report = await asyncio.to_thread(self.watchlist.scan_alerts, True)
            await ctx.send(embed=self._build_alerts_embed(report))
        except Exception as error:
            print(f"❌ !alerts error: {error}")
            await ctx.send("⚠️ MarketOps had trouble scanning alerts. Check the terminal for the error.")

    @commands.command(name="watch")
    async def watch_prefix(self, ctx, symbol: str = ""):
        result = await asyncio.to_thread(self.watchlist.add_symbol, symbol)
        await ctx.send(embed=self._build_change_embed("➕ Watchlist Updated", result))

    @commands.command(name="unwatch")
    async def unwatch_prefix(self, ctx, symbol: str = ""):
        result = await asyncio.to_thread(self.watchlist.remove_symbol, symbol)
        await ctx.send(embed=self._build_change_embed("➖ Watchlist Updated", result))

    @commands.command(name="watchreset")
    async def watchreset_prefix(self, ctx):
        result = await asyncio.to_thread(self.watchlist.reset_symbols)
        await ctx.send(embed=self._build_change_embed("🔄 Watchlist Reset", result))

    @commands.command(name="alertstatus")
    async def alertstatus_prefix(self, ctx):
        status = self.watchlist.get_status(
            auto_enabled=self.auto_enabled,
            channel_name=self.channel_name,
            poll_minutes=self.poll_minutes,
        )
        await ctx.send(embed=self._build_status_embed(status))

    @commands.command(name="alertson")
    async def alertson_prefix(self, ctx):
        self.auto_enabled = True
        self.watchlist.set_enabled(True)
        if not self.watchlist_loop.is_running():
            self.watchlist_loop.start()
        await ctx.send("✅ Watchlist alerts are ON. Use `!alertstatus` to check settings.")

    @commands.command(name="alertsoff")
    async def alertsoff_prefix(self, ctx):
        self.auto_enabled = False
        self.watchlist.set_enabled(False)
        await ctx.send("🛑 Watchlist alerts are OFF. Manual `!alerts` will show disabled until you run `!alertson`.")

    @commands.command(name="newson")
    async def newson_prefix(self, ctx):
        self.watchlist.set_news_enabled(True)
        await ctx.send("✅ Watchlist news alerts are ON.")

    @commands.command(name="newsoff")
    async def newsoff_prefix(self, ctx):
        self.watchlist.set_news_enabled(False)
        await ctx.send("🛑 Watchlist news alerts are OFF. Price alerts can still work.")

    @commands.command(name="threshold")
    async def threshold_prefix(self, ctx, value: str = ""):
        result = self.watchlist.set_threshold(value)
        if not result.get("ok"):
            await ctx.send(f'⚠️ {result.get("message")}')
            return
        await ctx.send(f'✅ {result.get("message")}')

    @tasks.loop(seconds=30)
    async def watchlist_loop(self):
        await self.bot.wait_until_ready()
        if not self.auto_enabled:
            return

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
            embed.add_field(name="No symbols found", value="Use `!watch NVDA` or add WATCHLIST_SYMBOLS to your .env file.", inline=False)
        else:
            value = "\n".join(item["line"] for item in quotes[:15])
            embed.add_field(name="Current Watchlist", value=value, inline=False)

        embed.add_field(
            name="Commands",
            value=(
                "`!watch TSLA` adds a ticker\n"
                "`!unwatch CVX` removes a ticker\n"
                "`!threshold 2` changes price sensitivity\n"
                "`!alertstatus` shows alert settings\n"
                "`!watchreset` resets to .env/default list"
            ),
            inline=False,
        )
        embed.add_field(name="Price Alert Rule", value=f'Alert when a symbol moves **±{report.get("move_threshold", 3):g}%** or more.', inline=False)
        embed.add_field(
            name="News Alert Rule",
            value="Ticker/company headlines are scanned when news alerts are ON. Quality labels help you judge the source.",
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
            embed.add_field(name="Watchlist disabled", value="Run `!alertson` to turn it back on.", inline=False)
        elif not alerts:
            embed.add_field(name="No active alerts", value=f'No symbol moved ±{report.get("move_threshold", 3):g}% or had a fresh matched headline right now.', inline=False)
        else:
            for alert in alerts[:10]:
                embed.add_field(name=self._alert_title(alert), value=self._alert_value(alert), inline=False)

        if report.get("news_enabled"):
            embed.add_field(name="News Provider", value=report.get("news_provider", "Not checked yet"), inline=False)
        embed.set_footer(text=f'Checked {report.get("updated", "Unknown")} • {VERSION}')
        return embed

    def _build_status_embed(self, status):
        embed = discord.Embed(
            title="⚙️ MarketOps Alert Status",
            description="Your current watchlist alert controls.",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Auto Alerts", value="ON" if status.get("auto_enabled") else "OFF", inline=True)
        embed.add_field(name="Watchlist Engine", value="ON" if status.get("enabled") else "OFF", inline=True)
        embed.add_field(name="News Alerts", value="ON" if status.get("news_enabled") else "OFF", inline=True)
        embed.add_field(name="Channel", value=f'#{status.get("channel_name", "watchlist")}', inline=True)
        embed.add_field(name="Poll Time", value=f'{status.get("poll_minutes", 15):g} minutes', inline=True)
        embed.add_field(name="Threshold", value=f'±{status.get("move_threshold", 3):g}%', inline=True)
        embed.add_field(name="Symbols", value=", ".join(status.get("symbols", [])) or "None", inline=False)
        embed.set_footer(text=f'Checked {status.get("updated", "Unknown")} • {VERSION}')
        return embed

    def _build_change_embed(self, title, result):
        color = discord.Color.green() if result.get("ok") else discord.Color.orange()
        embed = discord.Embed(title=title, description=result.get("message", "Watchlist updated."), color=color)
        symbols = result.get("symbols", [])
        embed.add_field(name="Current Symbols", value=", ".join(symbols) if symbols else "No symbols saved.", inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _alert_title(self, alert):
        if alert.get("type", "price") == "news":
            return f'{alert.get("emoji", "📰")} {alert.get("symbol", "Unknown")} News Alert — {alert.get("quality_label", "Needs Confirmation")}'
        return f'{alert.get("emoji", "🚨")} {alert.get("symbol", "Unknown")} Price Alert'

    def _alert_value(self, alert):
        if alert.get("type", "price") == "news":
            link = alert.get("link", "")
            open_line = f"\n[Open headline]({link})" if link else ""
            return (
                f'{alert.get("message", "News alert")}\n'
                f'Trust: **{alert.get("quality_label", "Needs Confirmation")}** — {alert.get("quality_reason", "Verify before acting.")}\n'
                f'Source: {alert.get("source", "Unknown")} • Provider: {alert.get("provider", "Unknown")} • Age: {alert.get("age", "Unknown")}\n'
                f'Watch: {alert.get("watch", "Verify before acting.")}'
                f"{open_line}"
            )
        return f'{alert.get("message", "Price alert")}\nWatch: {alert.get("watch", "Verify before acting.")}'

    def _env_bool(self, name, default=False):
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in ("1", "true", "yes", "y", "on")


async def setup(bot):
    await bot.add_cog(Watchlist(bot))
