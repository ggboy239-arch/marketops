import asyncio

import discord
from discord.ext import commands

from market.user_settings_engine import UserSettingsEngine


VERSION = "MarketOps v2.5"


class UserSettings(commands.Cog):
    """Personal MarketOps commands.

    Plain English: these commands let each person in Eduardo's server keep their
    own timezone, brief times, threshold, and watchlist.
    """

    def __init__(self, bot):
        self.bot = bot
        self.users = UserSettingsEngine()

    @commands.command(name="mysettings")
    async def mysettings_prefix(self, ctx):
        settings = await asyncio.to_thread(self.users.get_settings, ctx.author.id, ctx.author.display_name)
        await ctx.send(embed=self._settings_embed(ctx.author.display_name, settings))

    @commands.command(name="mytimezone")
    async def mytimezone_prefix(self, ctx, timezone_name: str = ""):
        result = await asyncio.to_thread(self.users.set_timezone, ctx.author.id, ctx.author.display_name, timezone_name)
        await ctx.send(embed=self._result_embed("🌎 Personal Timezone", result))

    @commands.command(name="mybrief")
    async def mybrief_prefix(self, ctx, *, times_text: str = ""):
        result = await asyncio.to_thread(self.users.set_brief_times, ctx.author.id, ctx.author.display_name, times_text)
        await ctx.send(embed=self._result_embed("🌅 Personal Brief Times", result))

    @commands.command(name="mythreshold")
    async def mythreshold_prefix(self, ctx, value: str = ""):
        result = await asyncio.to_thread(self.users.set_threshold, ctx.author.id, ctx.author.display_name, value)
        await ctx.send(embed=self._result_embed("🎯 Personal Threshold", result))

    @commands.command(name="mywatch")
    async def mywatch_prefix(self, ctx, symbol: str = ""):
        result = await asyncio.to_thread(self.users.add_symbol, ctx.author.id, ctx.author.display_name, symbol)
        await ctx.send(embed=self._result_embed("➕ Personal Watchlist", result))

    @commands.command(name="myunwatch")
    async def myunwatch_prefix(self, ctx, symbol: str = ""):
        result = await asyncio.to_thread(self.users.remove_symbol, ctx.author.id, ctx.author.display_name, symbol)
        await ctx.send(embed=self._result_embed("➖ Personal Watchlist", result))

    @commands.command(name="myreset")
    async def myreset_prefix(self, ctx):
        result = await asyncio.to_thread(self.users.reset_user, ctx.author.id, ctx.author.display_name)
        await ctx.send(embed=self._result_embed("🔄 Personal Settings Reset", result))

    @commands.command(name="mywatchlist")
    async def mywatchlist_prefix(self, ctx):
        report = await asyncio.to_thread(self.users.watchlist_report, ctx.author.id, ctx.author.display_name)
        await ctx.send(embed=self._watchlist_embed(ctx.author.display_name, report))

    @commands.command(name="myalerts")
    async def myalerts_prefix(self, ctx):
        report = await asyncio.to_thread(self.users.alerts_report, ctx.author.id, ctx.author.display_name)
        await ctx.send(embed=self._alerts_embed(ctx.author.display_name, report))

    def _settings_embed(self, name, settings):
        embed = discord.Embed(
            title="👤 MarketOps Personal Settings",
            description=f"Personal setup for **{name}**.",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Timezone", value=settings.get("timezone", "America/Los_Angeles"), inline=True)
        embed.add_field(name="Brief Times", value=", ".join(settings.get("brief_times", [])), inline=True)
        embed.add_field(name="Threshold", value=f'±{settings.get("threshold", 3):g}%', inline=True)
        embed.add_field(name="Alerts", value="ON" if settings.get("alerts_enabled", True) else "OFF", inline=True)
        embed.add_field(name="News Alerts", value="ON" if settings.get("news_alerts_enabled", True) else "OFF", inline=True)
        embed.add_field(name="Symbols", value=", ".join(settings.get("symbols", [])) or "None", inline=False)
        embed.add_field(
            name="Personal Commands",
            value=(
                "`!mytimezone America/Los_Angeles`\n"
                "`!mybrief 05:30,09:30,13:15`\n"
                "`!mythreshold 2`\n"
                "`!mywatch TSLA` / `!myunwatch TSLA`\n"
                "`!mywatchlist` / `!myalerts`"
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
        embed.add_field(name="Threshold", value=f'±{settings.get("threshold", 3):g}%', inline=True)
        embed.add_field(name="Timezone", value=settings.get("timezone", "America/Los_Angeles"), inline=True)
        embed.set_footer(text=f'Updated {report.get("updated", "Unknown")} • {VERSION}')
        return embed

    def _alerts_embed(self, name, report):
        settings = report.get("settings", {})
        embed = discord.Embed(
            title="🚨 Personal Alerts",
            description=f"Price alerts for **{name}** using their own threshold.",
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
            embed.add_field(name="Threshold", value=f'±{settings.get("threshold", 3):g}%', inline=True)
            embed.add_field(name="Symbols", value=", ".join(settings.get("symbols", [])) or "None", inline=False)
        embed.set_footer(text=VERSION)
        return embed


async def setup(bot):
    await bot.add_cog(UserSettings(bot))
