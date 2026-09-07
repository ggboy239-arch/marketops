import json
import os
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord.ext import commands


VERSION = "MarketOps v2.7.2"


class OwnerLogs(commands.Cog):
    """Owner-only logs for tickets and keys.

    Plain English: these commands are only for Eduardo/server owner. Admin helpers
    can work tickets, but only the owner can review key/ticket logs.
    """

    def __init__(self, bot):
        self.bot = bot
        self.access_file = Path("data/access_keys.json")
        self.panel_file = Path("data/ticket_panels.json")
        self.owner_id = os.getenv("MARKETOPS_OWNER_ID", "").strip()

    @commands.command(name="keylog")
    async def keylog_prefix(self, ctx):
        if not self._is_owner(ctx):
            await ctx.send("⚠️ Only the server owner can view the MarketOps key log.")
            return

        data = self._read_json(self.access_file, {"keys": {}, "renewals": {}})
        keys = list(data.get("keys", {}).values())
        renewals = list(data.get("renewals", {}).values())

        embed = discord.Embed(
            title="🔐 MarketOps Owner Key Log",
            description="Owner-only audit view for generated keys, redemptions, renewals, and revocations.",
            color=discord.Color.dark_gold(),
        )

        total = len(keys)
        unused = len([item for item in keys if not item.get("redeemed_by") and not item.get("revoked")])
        used = len([item for item in keys if item.get("redeemed_by")])
        revoked = len([item for item in keys if item.get("revoked")])
        pending = len([item for item in renewals if item.get("status") == "pending"])

        embed.add_field(
            name="Summary",
            value=(
                f"Total keys: **{total}**\n"
                f"Unused active keys: **{unused}**\n"
                f"Used/redeemed keys: **{used}**\n"
                f"Revoked keys: **{revoked}**\n"
                f"Pending renewals: **{pending}**"
            ),
            inline=False,
        )

        recent_keys = sorted(keys, key=lambda item: item.get("created_at") or item.get("redeemed_at") or "", reverse=True)[:12]
        if recent_keys:
            lines = []
            for item in recent_keys:
                key = item.get("key", "UNKNOWN")
                plan = item.get("plan", "unknown")
                created_by = item.get("created_by", "unknown")
                user = item.get("redeemed_by_name") or "unused"
                used_for = item.get("used_for") or "not used"
                status = "revoked" if item.get("revoked") else "active"
                lines.append(f"`{key}` — {plan} — {user} — {used_for} — {status} — created by `{created_by}`")
            embed.add_field(name="Recent Keys", value="\n".join(lines)[:1024], inline=False)
        else:
            embed.add_field(name="Recent Keys", value="No keys found yet.", inline=False)

        recent_renewals = sorted(renewals, key=lambda item: item.get("requested_at") or "", reverse=True)[:8]
        if recent_renewals:
            lines = []
            for item in recent_renewals:
                lines.append(
                    f"`{item.get('request_id', 'UNKNOWN')}` — {item.get('username', 'Unknown')} — "
                    f"{item.get('plan', 'unknown')} — {item.get('status', 'unknown')}"
                )
            embed.add_field(name="Recent Renewal Requests", value="\n".join(lines)[:1024], inline=False)

        embed.set_footer(text=f"Owner-only • {VERSION}")
        await ctx.send(embed=embed)

    @commands.command(name="ticketlog")
    async def ticketlog_prefix(self, ctx):
        if not self._is_owner(ctx):
            await ctx.send("⚠️ Only the server owner can view the MarketOps ticket log.")
            return

        if ctx.guild is None:
            await ctx.send("⚠️ Ticket log only works inside your Discord server.")
            return

        ticket_channels = []
        for channel in ctx.guild.text_channels:
            clean_name = self._clean_channel_name(channel.name)
            if clean_name.startswith(("buy-", "renew-", "bug-", "support-", "ticket-")):
                ticket_channels.append(channel)

        panels = self._read_json(self.panel_file, [])

        embed = discord.Embed(
            title="🎟️ MarketOps Owner Ticket Log",
            description="Owner-only audit view for ticket panels and currently open tickets.",
            color=discord.Color.dark_gold(),
        )
        embed.add_field(name="Ticket Panels Posted", value=str(len(panels) if isinstance(panels, list) else 0), inline=True)
        embed.add_field(name="Open Ticket Channels", value=str(len(ticket_channels)), inline=True)

        if ticket_channels:
            lines = []
            for channel in ticket_channels[:20]:
                lines.append(f"• {channel.mention} — `{channel.name}`")
            embed.add_field(name="Open Tickets", value="\n".join(lines)[:1024], inline=False)
        else:
            embed.add_field(name="Open Tickets", value="No open ticket channels found.", inline=False)

        embed.add_field(
            name="Owner Check",
            value="Use this if you hire someone. Compare open tickets, generated keys, redeemed users, and pending renewals.",
            inline=False,
        )
        embed.set_footer(text=f"Owner-only • {VERSION}")
        await ctx.send(embed=embed)

    def _is_owner(self, ctx):
        if ctx.guild is None:
            return False
        if self.owner_id and str(ctx.author.id) == self.owner_id:
            return True
        return ctx.guild.owner_id == ctx.author.id

    def _read_json(self, path, default):
        if not path.exists():
            return default
        try:
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
                return data
        except Exception:
            return default

    def _clean_channel_name(self, channel_name):
        cleaned = (channel_name or "").strip().lower()
        for separator in ("|", "┃", "│"):
            if separator in cleaned:
                cleaned = cleaned.split(separator)[-1].strip()
        return cleaned.replace(" ", "-")


async def setup(bot):
    await bot.add_cog(OwnerLogs(bot))
