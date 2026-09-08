import asyncio
import os

import discord
from discord.ext import commands

from market.access_key_engine import AccessKeyEngine


VERSION = "MarketOps v2.7.0"
PAYMENT_TEXT = "PayPal F&F: `ggboy_239@yahoo.com`\nCash App: `$eddiej12180`"


class Access(commands.Cog):
    """Access-key commands for MarketOps.

    Plain English: admins can generate keys to sell/give out. Users redeem a key
    for first access, then MarketOps can automatically assign the MarketOps User
    Discord role if the bot has Manage Roles permission.
    """

    def __init__(self, bot):
        self.bot = bot
        self.keys = AccessKeyEngine()
        self.admin_channel_name = os.getenv("MARKETOPS_ADMIN_CHANNEL", "admin-keys")
        self.user_role_name = os.getenv("MARKETOPS_USER_ROLE", "MarketOps User").strip()
        self.owner_id = os.getenv("MARKETOPS_OWNER_ID", "").strip()
        self.owner_mention_text = os.getenv("MARKETOPS_OWNER_MENTION", "@ssg").strip()

    @commands.command(name="redeem")
    async def redeem_prefix(self, ctx, key: str = ""):
        result = await asyncio.to_thread(self.keys.redeem_key, key, ctx.author.id, ctx.author.display_name)
        role_note = None
        if result.get("ok"):
            role_note = await self._add_user_role(ctx.guild, ctx.author)
        await ctx.send(embed=self._redeem_embed(result, role_note))

    @commands.command(name="renew")
    async def renew_prefix(self, ctx, key: str = ""):
        result = await asyncio.to_thread(self.keys.request_renewal, key, ctx.author.id, ctx.author.display_name)
        await ctx.send(embed=self._renew_request_embed(result))
        if result.get("ok"):
            await self._notify_admins(ctx, result)

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

    @commands.command(name="renewals")
    async def renewals_prefix(self, ctx):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a server admin can view renewal requests.")
            return
        renewals = await asyncio.to_thread(self.keys.pending_renewals)
        await ctx.send(embed=self._pending_renewals_embed(renewals))

    @commands.command(name="approverenew")
    async def approverenew_prefix(self, ctx, request_id: str = ""):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a server admin can approve renewals.")
            return
        result = await asyncio.to_thread(self.keys.approve_renewal, request_id, ctx.author.id)
        role_note = None
        if result.get("ok"):
            request = result.get("request", {})
            role_note = await self._add_role_to_user_id(ctx.guild, request.get("user_id"))
        await ctx.send(embed=self._approval_embed(result, role_note))

    @commands.command(name="denyrenew")
    async def denyrenew_prefix(self, ctx, request_id: str = ""):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a server admin can deny renewals.")
            return
        result = await asyncio.to_thread(self.keys.deny_renewal, request_id, ctx.author.id)
        await ctx.send(embed=self._simple_result_embed("🛑 Deny Renewal", result))

    @commands.command(name="revokekey")
    async def revokekey_prefix(self, ctx, key: str = ""):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a server admin can revoke MarketOps keys.")
            return
        result = await asyncio.to_thread(self.keys.revoke_key, key)
        role_note = None
        if result.get("ok"):
            record = result.get("record", {})
            role_note = await self._remove_role_if_no_access(ctx.guild, record.get("redeemed_by"))
        await ctx.send(embed=self._simple_result_embed("🛑 Revoke Key", result, role_note))

    @commands.command(name="adminusers")
    async def adminusers_prefix(self, ctx):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a server admin can view MarketOps users.")
            return
        users = await asyncio.to_thread(self.keys.list_users)
        await ctx.send(embed=self._users_embed(users))

    @commands.command(name="syncroles")
    async def syncroles_prefix(self, ctx):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a server admin can sync MarketOps roles.")
            return
        result = await self._sync_access_roles(ctx.guild)
        await ctx.send(embed=self._sync_roles_embed(result))

    async def _notify_admins(self, ctx, result):
        if ctx.guild is None:
            return
        channel = self._find_text_channel(ctx.guild, self.admin_channel_name)
        if channel is None:
            return

        mention = self._owner_mention(ctx)
        request = result.get("request", {})
        record = result.get("record", {})
        embed = discord.Embed(
            title="🔁 Renewal Needs Approval",
            description="Confirm payment first, then approve or deny this renewal.",
            color=discord.Color.gold(),
        )
        embed.add_field(name="User", value=f'{request.get("username", "Unknown")} (`{request.get("user_id", "Unknown")}`)', inline=False)
        embed.add_field(name="Request ID", value=f'`{request.get("request_id", "Unknown")}`', inline=True)
        embed.add_field(name="Plan", value=record.get("plan", "unknown"), inline=True)
        embed.add_field(name="Days", value=str(record.get("days", 0)), inline=True)
        embed.add_field(name="Payment To Check", value=PAYMENT_TEXT, inline=False)
        embed.add_field(name="Approve After Payment", value=f'`!approverenew {request.get("request_id", "")}`', inline=False)
        embed.add_field(name="Deny", value=f'`!denyrenew {request.get("request_id", "")}`', inline=False)
        embed.set_footer(text=VERSION)
        await channel.send(content=mention, embed=embed)

    def _owner_mention(self, ctx):
        if self.owner_id:
            return f"<@{self.owner_id}>"
        if self.owner_mention_text:
            return self.owner_mention_text
        if ctx.guild and ctx.guild.owner_id:
            return f"<@{ctx.guild.owner_id}>"
        return "@here"

    def _redeem_embed(self, result, role_note=None):
        color = discord.Color.green() if result.get("ok") else discord.Color.orange()
        embed = discord.Embed(title="🔑 MarketOps Key Redemption", description=result.get("message", "Done."), color=color)
        record = result.get("record")
        if record:
            embed.add_field(name="Plan", value=record.get("plan", "unknown"), inline=True)
            embed.add_field(name="Expires", value=self.keys.format_expiration(record), inline=True)
        if role_note:
            embed.add_field(name="Discord Role", value=role_note, inline=False)
        embed.add_field(name="Next Step", value="Go to `#watchlist` and use `!profile`, `!add TSLA`, `!list`, and `!scan`.", inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _renew_request_embed(self, result):
        color = discord.Color.green() if result.get("ok") else discord.Color.orange()
        embed = discord.Embed(title="🔁 MarketOps Renewal Request", description=result.get("message", "Done."), color=color)
        request = result.get("request")
        record = result.get("record")
        if request:
            embed.add_field(name="Request ID", value=f'`{request.get("request_id")}`', inline=True)
        if record:
            embed.add_field(name="Plan", value=record.get("plan", "unknown"), inline=True)
            embed.add_field(name="Days", value=str(record.get("days", 0)), inline=True)
        embed.add_field(name="Payment Required Before Approval", value=PAYMENT_TEXT, inline=False)
        embed.add_field(name="Next Step", value="After payment, wait for @ssg/Eduardo to confirm and approve your renewal.", inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _access_embed(self, name, status):
        color = discord.Color.green() if status.get("has_access") else discord.Color.orange()
        embed = discord.Embed(title="🔐 MarketOps Access", description=f"Access status for **{name}**.", color=color)
        embed.add_field(name="Status", value="ACTIVE" if status.get("has_access") else "NO ACTIVE KEY", inline=True)
        record = status.get("record")
        if record:
            embed.add_field(name="Plan", value=record.get("plan", "unknown"), inline=True)
            embed.add_field(name="Expires", value=self.keys.format_expiration(record), inline=True)
        embed.add_field(name="Discord Role", value=f"Active users should have `{self.user_role_name}`.", inline=False)
        embed.add_field(name="Message", value=status.get("message", "Unknown"), inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _created_keys_embed(self, created):
        embed = discord.Embed(title="✅ MarketOps Key Generated", description="Copy one key and give it to one person. Do not post paid keys publicly.", color=discord.Color.green())
        lines = []
        for record in created:
            access_length = "Lifetime" if record.get("plan") == "lifetime" else f'{record.get("days", 0)} day(s)'
            lines.append(f'`{record.get("key")}` — {record.get("plan")} — {access_length}')
        embed.add_field(name="New Key(s)", value="\n".join(lines[:25]), inline=False)
        embed.add_field(name="First-Time Access", value="They go to `#redeem-access` and type `!redeem KEY-HERE`. MarketOps will assign the user role automatically if permissions are correct.", inline=False)
        embed.add_field(name="Renewal Payment", value=PAYMENT_TEXT, inline=False)
        embed.add_field(name="Renewal", value="They go to `#redeem-access` and type `!renew KEY-HERE`. You approve after confirming payment.", inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _pending_renewals_embed(self, renewals):
        embed = discord.Embed(title="🔁 Pending MarketOps Renewals", description="Confirm payment before approving.", color=discord.Color.gold())
        embed.add_field(name="Payment To Check", value=PAYMENT_TEXT, inline=False)
        if not renewals:
            embed.add_field(name="No pending renewals", value="No renewal requests are waiting right now.", inline=False)
        else:
            lines = []
            for item in renewals[:20]:
                lines.append(f'`{item.get("request_id")}` — **{item.get("username", "Unknown")}** — {item.get("plan")} — {item.get("days")} day(s)')
            embed.add_field(name="Requests", value="\n".join(lines), inline=False)
            embed.add_field(name="Approve", value="`!approverenew REQUEST-ID`", inline=True)
            embed.add_field(name="Deny", value="`!denyrenew REQUEST-ID`", inline=True)
        embed.set_footer(text=VERSION)
        return embed

    def _approval_embed(self, result, role_note=None):
        color = discord.Color.green() if result.get("ok") else discord.Color.orange()
        embed = discord.Embed(title="✅ Renewal Approval", description=result.get("message", "Done."), color=color)
        request = result.get("request")
        record = result.get("record")
        if request:
            embed.add_field(name="User", value=request.get("username", "Unknown"), inline=True)
            embed.add_field(name="Request ID", value=f'`{request.get("request_id")}`', inline=True)
        if record:
            embed.add_field(name="New Access", value=self.keys.format_expiration(record), inline=True)
        if role_note:
            embed.add_field(name="Discord Role", value=role_note, inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _users_embed(self, users):
        embed = discord.Embed(title="👥 MarketOps Redeemed Users", description="Users who redeemed or renewed a MarketOps key.", color=discord.Color.blue())
        if not users:
            embed.add_field(name="No users yet", value="No keys have been redeemed yet.", inline=False)
        else:
            lines = []
            for record in users[:20]:
                name = record.get("redeemed_by_name") or record.get("redeemed_by") or "Unknown"
                plan = record.get("plan", "unknown")
                expires = self.keys.format_expiration(record)
                use_type = record.get("used_for") or "access"
                status = "revoked" if record.get("revoked") else "active"
                lines.append(f"• **{name}** — {plan} — {expires} — {use_type} — {status}")
            embed.add_field(name="Users", value="\n".join(lines), inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _simple_result_embed(self, title, result, role_note=None):
        color = discord.Color.green() if result.get("ok") else discord.Color.orange()
        embed = discord.Embed(title=title, description=result.get("message", "Done."), color=color)
        if role_note:
            embed.add_field(name="Discord Role", value=role_note, inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _sync_roles_embed(self, result):
        color = discord.Color.green() if result.get("ok") else discord.Color.orange()
        embed = discord.Embed(title="🔄 MarketOps Role Sync", description=result.get("message", "Done."), color=color)
        embed.add_field(name="Role", value=f'`{self.user_role_name}`', inline=True)
        embed.add_field(name="Added", value=str(result.get("added", 0)), inline=True)
        embed.add_field(name="Removed", value=str(result.get("removed", 0)), inline=True)
        if result.get("skipped"):
            embed.add_field(name="Skipped", value=str(result.get("skipped", 0)), inline=True)
        embed.set_footer(text=VERSION)
        return embed

    async def _add_user_role(self, guild, member):
        if guild is None or member is None:
            return "Role not assigned because this was not inside a server."
        role = self._find_role(guild)
        if role is None:
            return f"Role `{self.user_role_name}` was not found. Create it, then run `!syncroles`."
        if role in getattr(member, "roles", []):
            return f"Already has `{role.name}`."
        try:
            await member.add_roles(role, reason="MarketOps key redeemed/renewed")
            return f"Assigned `{role.name}` automatically."
        except discord.Forbidden:
            return f"Could not assign `{role.name}`. Move the bot role above `{role.name}` and give the bot Manage Roles."
        except Exception as error:
            print(f"❌ MarketOps role assign error: {error!r}")
            return f"Could not assign `{role.name}`. Check terminal for error."

    async def _add_role_to_user_id(self, guild, user_id):
        member = await self._get_member(guild, user_id)
        if member is None:
            return "Role not assigned because the user was not found in this server."
        return await self._add_user_role(guild, member)

    async def _remove_role_if_no_access(self, guild, user_id):
        if guild is None or not user_id:
            return None
        status = await asyncio.to_thread(self.keys.access_status, user_id)
        if status.get("has_access"):
            return "User still has another active key, so role was kept."
        member = await self._get_member(guild, user_id)
        role = self._find_role(guild)
        if member is None or role is None or role not in getattr(member, "roles", []):
            return None
        try:
            await member.remove_roles(role, reason="MarketOps key revoked/expired")
            return f"Removed `{role.name}` because no active access remains."
        except discord.Forbidden:
            return f"Could not remove `{role.name}`. Check bot role order and Manage Roles permission."
        except Exception as error:
            print(f"❌ MarketOps role remove error: {error!r}")
            return f"Could not remove `{role.name}`. Check terminal for error."

    async def _sync_access_roles(self, guild):
        if guild is None:
            return {"ok": False, "message": "Run this inside the Discord server.", "added": 0, "removed": 0, "skipped": 0}
        role = self._find_role(guild)
        if role is None:
            return {"ok": False, "message": f"Role `{self.user_role_name}` was not found. Create it first.", "added": 0, "removed": 0, "skipped": 0}

        users = await asyncio.to_thread(self.keys.list_users)
        user_ids = {str(record.get("redeemed_by")) for record in users if record.get("redeemed_by")}
        added = 0
        removed = 0
        skipped = 0

        for user_id in user_ids:
            member = await self._get_member(guild, user_id)
            if member is None:
                skipped += 1
                continue
            status = await asyncio.to_thread(self.keys.access_status, user_id)
            has_access = status.get("has_access", False)
            has_role = role in getattr(member, "roles", [])
            try:
                if has_access and not has_role:
                    await member.add_roles(role, reason="MarketOps role sync")
                    added += 1
                elif not has_access and has_role:
                    await member.remove_roles(role, reason="MarketOps role sync")
                    removed += 1
            except discord.Forbidden:
                skipped += 1
            except Exception as error:
                print(f"❌ MarketOps role sync error for {user_id}: {error!r}")
                skipped += 1

        return {
            "ok": True,
            "message": "Role sync complete. Active users should have the role; inactive users from key records should not.",
            "added": added,
            "removed": removed,
            "skipped": skipped,
        }

    async def _get_member(self, guild, user_id):
        if guild is None or not user_id:
            return None
        try:
            user_id_int = int(user_id)
        except (TypeError, ValueError):
            return None
        member = guild.get_member(user_id_int)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(user_id_int)
        except Exception:
            return None

    def _find_role(self, guild):
        target = self._clean_name(self.user_role_name)
        for role in guild.roles:
            if self._clean_name(role.name) == target:
                return role
        return None

    def _find_text_channel(self, guild, target_name):
        target = self._clean_name(target_name)
        for channel in guild.text_channels:
            if self._clean_name(channel.name).endswith(target):
                return channel
        return None

    def _clean_name(self, value):
        cleaned = (value or "").strip().lower()
        for separator in ("|", "┃", "│"):
            if separator in cleaned:
                cleaned = cleaned.split(separator)[-1].strip()
        while cleaned and not cleaned[0].isalnum():
            cleaned = cleaned[1:].strip()
        return cleaned.replace(" ", "-")

    def _is_admin(self, ctx):
        if ctx.guild is None:
            return False
        permissions = getattr(ctx.author, "guild_permissions", None)
        return bool(permissions and permissions.administrator)


async def setup(bot):
    await bot.add_cog(Access(bot))