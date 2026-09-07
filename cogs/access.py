import asyncio

import discord
from discord.ext import commands

from market.access_key_engine import AccessKeyEngine


VERSION = "MarketOps v2.6"


class Access(commands.Cog):
    """Access-key commands for MarketOps.

    Plain English: admins can generate keys to sell/give out. Users redeem one
    key inside Eduardo's server to unlock personal commands.
    """

    def __init__(self, bot):
        self.bot = bot
        self.keys = AccessKeyEngine()

    @commands.command(name="redeem")
    async def redeem_prefix(self, ctx, key: str = ""):
        result = await asyncio.to_thread(
            self.keys.redeem_key,
            key,
            ctx.author.id,
            ctx.author.display_name,
        )
        await ctx.send(embed=self._redeem_embed(result))

    @commands.command(name="access")
    async def access_prefix(self, ctx):
        status = await asyncio.to_thread(self.keys.access_status, ctx.author.id)
        await ctx.send(embed=self._access_embed(ctx.author.display_name, status))

    @commands.command(name="genkey", aliases=["adminkey"])
    async def genkey_prefix(self, ctx, plan: str = "beta", days: str = "30"):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a server admin can generate MarketOps keys.")
            return

        record = await asyncio.to_thread(self.keys.create_key, plan, days, ctx.author.id)
        await ctx.send(embed=self._created_keys_embed([record]))

    @commands.command(name="genkeys")
    async def genkeys_prefix(self, ctx, plan: str = "beta", days: str = "30", count: str = "5"):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a server admin can generate MarketOps keys.")
            return

        try:
            count_value = max(1, min(int(count), 25))
        except ValueError:
            count_value = 5

        created = []
        for _ in range(count_value):
            record = await asyncio.to_thread(self.keys.create_key, plan, days, ctx.author.id)
            created.append(record)

        await ctx.send(embed=self._created_keys_embed(created))

    @commands.command(name="revokekey")
    async def revokekey_prefix(self, ctx, key: str = ""):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a server admin can revoke MarketOps keys.")
            return

        result = await asyncio.to_thread(self.keys.revoke_key, key)
        await ctx.send(embed=self._simple_result_embed("🛑 Revoke Key", result))

    @commands.command(name="adminusers")
    async def adminusers_prefix(self, ctx):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a server admin can view MarketOps users.")
            return

        users = await asyncio.to_thread(self.keys.list_users)
        await ctx.send(embed=self._users_embed(users))

    def _redeem_embed(self, result):
        color = discord.Color.green() if result.get("ok") else discord.Color.orange()
        embed = discord.Embed(
            title="🔑 MarketOps Key Redemption",
            description=result.get("message", "Done."),
            color=color,
        )
        record = result.get("record")
        if record:
            embed.add_field(name="Plan", value=record.get("plan", "unknown"), inline=True)
            embed.add_field(name="Expires", value=self.keys.format_expiration(record), inline=True)
        embed.add_field(
            name="Next Step",
            value="Go to `#watchlist` and use `!profile`, `!add TSLA`, `!list`, and `!scan`.",
            inline=False,
        )
        embed.set_footer(text=VERSION)
        return embed

    def _access_embed(self, name, status):
        color = discord.Color.green() if status.get("has_access") else discord.Color.orange()
        embed = discord.Embed(
            title="🔐 MarketOps Access",
            description=f"Access status for **{name}**.",
            color=color,
        )
        embed.add_field(name="Status", value="ACTIVE" if status.get("has_access") else "NO ACTIVE KEY", inline=True)
        record = status.get("record")
        if record:
            embed.add_field(name="Plan", value=record.get("plan", "unknown"), inline=True)
            embed.add_field(name="Expires", value=self.keys.format_expiration(record), inline=True)
        embed.add_field(name="Message", value=status.get("message", "Unknown"), inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _created_keys_embed(self, created):
        embed = discord.Embed(
            title="✅ MarketOps Key Generated",
            description="Copy one key and give it to one person. Do not post paid keys publicly.",
            color=discord.Color.green(),
        )
        lines = []
        for record in created:
            lines.append(f'`{record.get("key")}` — {record.get("plan")} — {self.keys.format_expiration(record)}')
        embed.add_field(name="New Key(s)", value="\n".join(lines[:25]), inline=False)
        embed.add_field(
            name="How They Use It",
            value="They go to `#redeem-access` and type `!redeem KEY-HERE`. After that, they use personal commands in `#watchlist`.",
            inline=False,
        )
        embed.set_footer(text=VERSION)
        return embed

    def _users_embed(self, users):
        embed = discord.Embed(
            title="👥 MarketOps Redeemed Users",
            description="Users who redeemed a MarketOps key.",
            color=discord.Color.blue(),
        )
        if not users:
            embed.add_field(name="No users yet", value="No keys have been redeemed yet.", inline=False)
        else:
            lines = []
            for record in users[:20]:
                name = record.get("redeemed_by_name") or record.get("redeemed_by") or "Unknown"
                plan = record.get("plan", "unknown")
                expires = self.keys.format_expiration(record)
                status = "revoked" if record.get("revoked") else "active"
                lines.append(f"• **{name}** — {plan} — {expires} — {status}")
            embed.add_field(name="Redeemed", value="\n".join(lines), inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _simple_result_embed(self, title, result):
        color = discord.Color.green() if result.get("ok") else discord.Color.orange()
        embed = discord.Embed(title=title, description=result.get("message", "Done."), color=color)
        embed.set_footer(text=VERSION)
        return embed

    def _is_admin(self, ctx):
        if ctx.guild is None:
            return False
        permissions = getattr(ctx.author, "guild_permissions", None)
        return bool(permissions and permissions.administrator)


async def setup(bot):
    await bot.add_cog(Access(bot))
