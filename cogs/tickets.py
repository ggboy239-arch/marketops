import json
import os
import re
from pathlib import Path

import discord
from discord.ext import commands


VERSION = "MarketOps v2.7.1"


class Tickets(commands.Cog):
    """Emoji ticket panel for MarketOps access and support.

    Plain English: this lets users click an emoji to open a private ticket for
    buying a key, renewing access, or reporting a bug.
    """

    PANEL_FILE = Path("data/ticket_panels.json")

    TICKET_TYPES = {
        "💳": {
            "type": "buy",
            "label": "Buy Initial Access Key",
            "prefix": "buy",
            "color": discord.Color.green(),
        },
        "🔁": {
            "type": "renew",
            "label": "Renew Access",
            "prefix": "renew",
            "color": discord.Color.gold(),
        },
        "🐛": {
            "type": "bug",
            "label": "Bug / Issue",
            "prefix": "bug",
            "color": discord.Color.red(),
        },
    }

    def __init__(self, bot):
        self.bot = bot
        self.admin_channel_name = os.getenv("MARKETOPS_ADMIN_CHANNEL", "admin-keys")
        self.ticket_category_name = os.getenv("MARKETOPS_TICKET_CATEGORY", "MarketOps Access")
        self.admin_mention = os.getenv("MARKETOPS_ADMIN_MENTION", "@ssg")
        self.paypal = os.getenv("MARKETOPS_PAYPAL", "ggboy_239@yahoo.com")
        self.cashapp = os.getenv("MARKETOPS_CASHAPP", "$eddiej12180")
        self.panels = self._load_panels()

    @commands.command(name="ticketpanel")
    async def ticketpanel_prefix(self, ctx):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a server admin can post the MarketOps ticket panel.")
            return

        embed = discord.Embed(
            title="🎟️ MarketOps Access & Support Tickets",
            description=(
                "React below to open a private ticket.\n\n"
                "💳 **Buy Initial Access Key** — request a new paid/beta key\n"
                "🔁 **Renew Access** — request renewal after payment\n"
                "🐛 **Bug / Issue** — report bot problems or broken commands"
            ),
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="Payment Options",
            value=(
                f"PayPal F&F: `{self.paypal}`\n"
                f"Cash App: `{self.cashapp}`\n\n"
                "Payment is manually confirmed by admin before a key or renewal is approved."
            ),
            inline=False,
        )
        embed.set_footer(text=f"React with one emoji below • {VERSION}")

        message = await ctx.send(embed=embed)
        for emoji in self.TICKET_TYPES:
            await message.add_reaction(emoji)

        self.panels.add(str(message.id))
        self._save_panels()

    @commands.command(name="tickethelp", aliases=["ticketadmin"])
    async def tickethelp_prefix(self, ctx):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a server admin can view the ticket admin helper.")
            return

        embed = discord.Embed(
            title="🛠️ MarketOps Ticket/Admin Helper",
            description="Private admin cheat sheet. Use this in `#admin-keys` only.",
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="Post Ticket Panel",
            value="Go to `#marketops-commands` and type `!ticketpanel` once. Users click 💳, 🔁, or 🐛.",
            inline=False,
        )
        embed.add_field(
            name="New Buyer Flow",
            value=(
                "1. User clicks 💳 and pays.\n"
                f"2. Confirm PayPal F&F `{self.paypal}` or Cash App `{self.cashapp}`.\n"
                "3. Run `!genkey monthly 30` or `!genkey trial 7`.\n"
                "4. Give the key to the user.\n"
                "5. User goes to `#redeem-access` and types `!redeem KEY-HERE`."
            ),
            inline=False,
        )
        embed.add_field(
            name="Renewal Flow",
            value=(
                "1. User clicks 🔁 and pays.\n"
                "2. User submits `!renew KEY-HERE` in `#redeem-access`.\n"
                "3. Confirm payment.\n"
                "4. Run `!approverenew REQUEST-ID` or `!denyrenew REQUEST-ID`.\n"
                "5. Use `!renewals` to see pending requests."
            ),
            inline=False,
        )
        embed.add_field(
            name="Key/Admin Commands",
            value=(
                "`!genkey beta 30`\n"
                "`!genkeys monthly 30 5`\n"
                "`!revokekey KEY-HERE`\n"
                "`!adminusers`\n"
                "`!renewals`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Ticket Commands",
            value="`!closeticket` or `!close` inside a ticket when finished.",
            inline=False,
        )
        embed.set_footer(text=VERSION)
        await ctx.send(embed=embed)

    @commands.command(name="closeticket", aliases=["close"])
    async def closeticket_prefix(self, ctx):
        if not ctx.channel.name.startswith(("ticket-", "buy-", "renew-", "bug-", "support-")):
            await ctx.send("⚠️ This command only works inside a MarketOps ticket channel.")
            return
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only an admin can close tickets right now.")
            return
        await ctx.send("✅ Closing this ticket.")
        await ctx.channel.delete(reason=f"Closed by {ctx.author}")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.user_id == self.bot.user.id:
            return
        if str(payload.message_id) not in self.panels:
            return

        emoji = str(payload.emoji)
        ticket_info = self.TICKET_TYPES.get(emoji)
        if not ticket_info:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        member = guild.get_member(payload.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(payload.user_id)
            except Exception:
                return

        channel = guild.get_channel(payload.channel_id)
        if channel:
            try:
                message = await channel.fetch_message(payload.message_id)
                await message.remove_reaction(payload.emoji, member)
            except Exception:
                pass

        existing = self._find_existing_ticket(guild, member, ticket_info["prefix"])
        if existing:
            try:
                await member.send(f"You already have an open MarketOps ticket: {existing.mention}")
            except Exception:
                pass
            return

        ticket_channel = await self._create_ticket_channel(guild, member, ticket_info)
        if ticket_channel is None:
            admin_channel = self._find_text_channel(guild, self.admin_channel_name)
            if admin_channel:
                await admin_channel.send(
                    f"{self._admin_ping(guild)} Ticket requested by {member.mention}, but I could not create a private channel. "
                    "Check bot permissions: Manage Channels, View Channels, Send Messages, Embed Links."
                )
            return

        await ticket_channel.send(
            content=f"{member.mention} {self._admin_ping(guild)}",
            embed=self._ticket_embed(member, ticket_info),
        )

        admin_channel = self._find_text_channel(guild, self.admin_channel_name)
        if admin_channel:
            await admin_channel.send(
                content=self._admin_ping(guild),
                embed=self._admin_ticket_embed(member, ticket_info, ticket_channel),
            )

    async def _create_ticket_channel(self, guild, member, ticket_info):
        category = self._find_category(guild, self.ticket_category_name)
        if category is None:
            try:
                category = await guild.create_category(self.ticket_category_name)
            except Exception:
                category = None

        safe_name = self._safe_name(member.display_name)
        channel_name = f"{ticket_info['prefix']}-{safe_name}-{str(member.id)[-4:]}"

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True),
        }

        try:
            return await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"MarketOps ticket opened by {member}",
            )
        except Exception as error:
            print(f"❌ Ticket channel create error: {error}")
            return None

    def _ticket_embed(self, member, ticket_info):
        embed = discord.Embed(
            title=f"🎟️ {ticket_info['label']}",
            description="An admin will review this ticket.",
            color=ticket_info["color"],
        )
        embed.add_field(name="User", value=f"{member.mention} (`{member.id}`)", inline=False)

        if ticket_info["type"] in ("buy", "renew"):
            embed.add_field(
                name="Payment Required Before Approval",
                value=(
                    f"PayPal F&F: `{self.paypal}`\n"
                    f"Cash App: `{self.cashapp}`\n\n"
                    "After payment, send a screenshot or payment note here. "
                    "Admin will confirm payment before creating a key or approving renewal."
                ),
                inline=False,
            )

        if ticket_info["type"] == "buy":
            embed.add_field(
                name="What To Post Here",
                value="Tell admin which plan you want: `trial`, `monthly`, or `lifetime`.",
                inline=False,
            )
        elif ticket_info["type"] == "renew":
            embed.add_field(
                name="What To Post Here",
                value="Post the renewal key or tell admin you need a new monthly renewal key.",
                inline=False,
            )
        else:
            embed.add_field(
                name="What To Post Here",
                value="Explain what command broke, what channel you used, and paste any error message.",
                inline=False,
            )

        embed.add_field(name="Close Ticket", value="Admin can type `!closeticket` when finished.", inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _admin_ticket_embed(self, member, ticket_info, ticket_channel):
        embed = discord.Embed(
            title="🎟️ New MarketOps Ticket",
            description=f"A user opened a **{ticket_info['label']}** ticket.",
            color=ticket_info["color"],
        )
        embed.add_field(name="User", value=f"{member.mention} (`{member.id}`)", inline=False)
        embed.add_field(name="Ticket", value=ticket_channel.mention, inline=False)
        if ticket_info["type"] == "buy":
            embed.add_field(name="Admin Step", value="Confirm payment, then run `!genkey monthly 30` in `#admin-keys` and give them the key privately.", inline=False)
        elif ticket_info["type"] == "renew":
            embed.add_field(name="Admin Step", value="Confirm payment, then approve their pending renewal or generate a renewal key.", inline=False)
        else:
            embed.add_field(name="Admin Step", value="Review the bug report and ask for screenshot/logs if needed.", inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _find_existing_ticket(self, guild, member, prefix):
        suffix = str(member.id)[-4:]
        for channel in guild.text_channels:
            clean_name = self._clean_channel_name(channel.name)
            if clean_name.startswith(f"{prefix}-") and clean_name.endswith(suffix):
                return channel
        return None

    def _admin_ping(self, guild):
        if self.admin_mention:
            return self.admin_mention
        if guild.owner_id:
            return f"<@{guild.owner_id}>"
        return "@here"

    def _safe_name(self, name):
        clean = re.sub(r"[^a-zA-Z0-9-]+", "-", name.lower()).strip("-")
        return clean[:20] or "user"

    def _is_admin(self, ctx):
        if ctx.guild is None:
            return False
        permissions = getattr(ctx.author, "guild_permissions", None)
        return bool(permissions and permissions.administrator)

    def _find_text_channel(self, guild, target_name):
        target = self._clean_channel_name(target_name)
        for channel in guild.text_channels:
            if self._clean_channel_name(channel.name).endswith(target):
                return channel
        return None

    def _find_category(self, guild, target_name):
        target = self._clean_channel_name(target_name)
        for category in guild.categories:
            clean_name = self._clean_channel_name(category.name)
            if clean_name == target or clean_name.endswith(target):
                return category
        return None

    def _clean_channel_name(self, channel_name):
        cleaned = (channel_name or "").strip().lower()
        for separator in ("|", "┃", "│"):
            if separator in cleaned:
                cleaned = cleaned.split(separator)[-1].strip()
        return cleaned.replace(" ", "-")

    def _load_panels(self):
        if not self.PANEL_FILE.exists():
            return set()
        try:
            with self.PANEL_FILE.open("r", encoding="utf-8") as file:
                data = json.load(file)
                return set(str(item) for item in data if item)
        except Exception:
            return set()

    def _save_panels(self):
        self.PANEL_FILE.parent.mkdir(parents=True, exist_ok=True)
        with self.PANEL_FILE.open("w", encoding="utf-8") as file:
            json.dump(sorted(self.panels), file, indent=2)


async def setup(bot):
    await bot.add_cog(Tickets(bot))
