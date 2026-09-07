import asyncio

import discord
from discord.ext import commands

from market.access_key_engine import AccessKeyEngine
from market.user_settings_engine import UserSettingsEngine


VERSION = "MarketOps v2.6"


class UserSettings(commands.Cog):
    """Personal MarketOps commands.

    Plain English: each person in Eduardo's server can keep their own timezone,
    brief times, threshold, and watchlist after redeeming a key.
    """

    def __init__(self, bot):
        self.bot = bot
        self.users = UserSettingsEngine()
        self.keys = AccessKeyEngine()

    @commands.command(name="profile", aliases=["mysettings", "settings"])
    async def profile_prefix(self, ctx):
        if not await self._has_personal_access(ctx):
            return
        settings = await asyncio.to_thread(self.users.get_settings, ctx.author.id, ctx.author.display_name)
        await ctx.send(embed=self._settings_embed(ctx.author.display_name, settings))

    @commands.command(name="timezone", aliases=["mytimezone", "tz"])
    async def timezone_prefix(self, ctx, timezone_name: str = ""):
        if not await self._has_personal_access(ctx):
            return
        result = await asyncio.to_thread(self.users.set_timezone, ctx.author.id, ctx.author.display_name, timezone_name)
        await ctx.send(embed=self._result_embed("🌎 Personal Timezone", result))

    @commands.command(name="brief-times", aliases=["brieftimes", "mybrief"])
    async def brief_times_prefix(self, ctx, *, times_text: str = ""):
        if not await self._has_personal_access(ctx):
            return
        result = await asyncio.to_thread(self.users.set_brief_times, ctx.author.id, ctx.author.display_name, times_text)
        await ctx.send(embed=self._result_embed("🌅 Personal Brief Times", result))

    @commands.command(name="alert-percent", aliases=["alertpercent", "mythreshold"])
    async def alert_percent_prefix(self, ctx, value: str = ""):
        if not await self._has_personal_access(ctx):
            return
        result = await asyncio.to_thread(self.users.set_threshold, ctx.author.id, ctx.author.display_name, value)
        await ctx.send(embed=self._result_embed("🎯 Personal Alert Percent", result))

    @commands.command(name="add", aliases=["mywatch"])
    async def add_prefix(self, ctx, symbol: str = ""):
        if not await self._has_personal_access(ctx):
            return
        result = await asyncio.to_thread(self.users.add_symbol, ctx.author.id, ctx.author.display_name, symbol)
        await ctx.send(embed=self._result_embed("➕ Personal Watchlist", result))

    @commands.command(name="remove", aliases=["myunwatch"])
    async def remove_prefix(self, ctx, symbol: str = ""):
        if not await self._has_personal_access(ctx):
            return
        result = await asyncio.to_thread(self.users.remove_symbol, ctx.author.id, ctx.author.display_name, symbol)
        await ctx.send(embed=self._result_embed("➖ Personal Watchlist", result))

    @commands.command(name="reset-profile", aliases=["myreset"])
    async def reset_profile_prefix(self, ctx):
        if not await self._has_personal_access(ctx):
            return
        result = await asyncio.to_thread(self.users.reset_user, ctx.author.id, ctx.author.display_name)
        await ctx.send(embed=self._result_embed("🔄 Personal Settings Reset", result))

    @commands.command(name="list", aliases=["mywatchlist"])
    async def list_prefix(self, ctx):
        if not await self._has_personal_access(ctx):
            return
        report = await asyncio.to_thread(self.users.watchlist_report, ctx.author.id, ctx.author.display_name)
        await ctx.send(embed=self._watchlist_embed(ctx.author.display_name, report))

    @commands.command(name="scan", aliases=["myalerts"])
    async def scan_prefix(self, ctx):
        if not await self._has_personal_access(ctx):
            return
        report = await asyncio.to_thread(self.users.alerts_report, ctx.author.id, ctx.author.display_name)
        await ctx.send(embed=self._alerts_embed(ctx.author.display_name, report))

    async def _has_personal_access(self, ctx):
        if self._is_admin(ctx):
            return True

        allowed = await asyncio.to_thread(self.keys.user_has_access, ctx.author.id)
        if allowed:
            return True

        embed = discord.Embed(
            title="🔐 MarketOps Access Required",
            description="Personal commands require an active MarketOps key.",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Redeem", value="Type `!redeem YOUR-KEY-HERE` in `#watchlist`.", inline=False)
        embed.add_field(name="Ask Eduardo", value="Ask the server owner for a beta, trial, monthly, or lifetime key.", inline=False)
        embed.set_footer(text=VERSION)
        await ctx.send(embed=embed)
        return False

    def _is_admin(self, ctx):
        if ctx.guild is None:
            return False
        permissions = getattr(ctx.author, "guild_permissions", None)
        return bool(permissions and permissions.administrator)

    def _settings_embed(self, name, settings):
        embed = discord.Embed(
            title="👤 MarketOps Personal Profile",
            description=f"Personal setup for **{name}**.",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Timezone", value=settings.get("timezone", "America/Los_Angeles"), inline=True)
        embed.add_field(name="Brief Times", value=", ".join(settings.get("brief_times", [])), inline=True)
        embed.add_field(name="Alert Percent", value=f'±{settings.get("threshold", 3):g}%', inline=True)
        embed.add_field(name="Alerts", value="ON" if settings.get("alerts_enabled", True) else "OFF", inline=True)
        embed.add_field(name="News Alerts", value="ON" if settings.get("news_alerts_enabled", True) else "OFF", inline=True)
        embed.add_field(name="Symbols", value=", ".join(settings.get("symbols", [])) or "None", inline=False)
        embed.add_field(
            name="Personal Commands",
            value=(
                "`!timezone America/Los_Angeles`\n"
                "`!brief-times 05:30,09:30,13:15`\n"
                "`!alert-percent 2`\n"
                "`!add TSLA` / `!remove TSLA`\n"
                "`!list` / `!scan`"
            ),
            inline=False,
        )
        embed.set_footer(text=VERSION)
        return embed

    def _watchlist_embed(self, name, report):
        settings = report.get("settings", {})
        embed = discord.Embed(
            title="📌 Personal Watchlist",
            description=f"Personal watchlist for **{name}**.",
            color=discord.Color.blue(),
        )
        quotes = report.get("quotes", [])
        embed.add_field(name="Symbols", value="\n".join(quotes[:15]) or "No symbols saved.", inline=False)
        embed.add_field(name="Alert Percent", value=f'±{settings.get("threshold", 3):g}%', inline=True)
        embed.add_field(name="Timezone", value=settings.get("timezone", "America/Los_Angeles"), inline=True)
        embed.set_footer(text=f'Updated {report.get("updated", "Unknown")} • {VERSION}')
        return embed

    def _alerts_embed(self, name, report):
        settings = report.get("settings", {})
        embed = discord.Embed(
            title="🚨 Personal Alert Scan",
            description=f"Price alerts for **{name}** using their own alert percent.",
            color=discord.Color.red(),
        )
        alerts = report.get("alerts", [])
        if not alerts:
            embed.add_field(
                name="No personal alerts",
                value=f'No personal symbol moved ±{settings.get("threshold", 3):g}% or more right now.',
                inline=False,
            )
        else:
            embed.add_field(name="Triggered", value="\n".join(alerts[:10]), inline=False)
        embed.add_field(name="Timezone", value=settings.get("timezone", "America/Los_Angeles"), inline=True)
        embed.set_footer(text=f'Checked {report.get("updated", "Unknown")} • {VERSION}')
        return embed

    def _result_embed(self, title, result):
        color = discord.Color.green() if result.get("ok") else discord.Color.orange()
        embed = discord.Embed(title=title, description=result.get("message", "Done."), color=color)
        settings = result.get("settings")
        if settings:
            embed.add_field(name="Timezone", value=settings.get("timezone", "America/Los_Angeles"), inline=True)
            embed.add_field(name="Alert Percent", value=f'±{settings.get("threshold", 3):g}%', inline=True)
            embed.add_field(name="Symbols", value=", ".join(settings.get("symbols", [])) or "None", inline=False)
        embed.set_footer(text=VERSION)
        return embed


async def setup(bot):
    await bot.add_cog(UserSettings(bot))
