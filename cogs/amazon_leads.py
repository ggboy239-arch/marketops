import asyncio
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord.ext import commands, tasks

from market.amazon_leads_engine import AmazonLeadsEngine


class AmazonLeads(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.engine = AmazonLeadsEngine()
        self.minutes = max(10, int(os.getenv("AMAZON_LEADS_CHECK_MINUTES", "30")))
        self.channel_ids = {
            "hold": os.getenv("AMAZON_HOLD_LEADS_CHANNEL_ID", ""),
            "pressure": os.getenv("AMAZON_STOCK_PRESSURE_CHANNEL_ID", ""),
            "review": os.getenv("AMAZON_LEAD_REVIEW_CHANNEL_ID", ""),
        }
        self.state_file = Path("data/amazon_leads_state.json")
        self.state = self._load_state()
        self.last_error = "None"
        self.scanner.change_interval(minutes=self.minutes)
        self.scanner.start()

    def cog_unload(self):
        self.scanner.cancel()

    @tasks.loop(minutes=30)
    async def scanner(self):
        await self.bot.wait_until_ready()
        await self._run_scan()

    @scanner.before_loop
    async def before_scanner(self):
        await self.bot.wait_until_ready()

    @commands.command(name="amazonleads", aliases=["keepaleads"])
    async def amazon_leads(self, ctx, action="status"):
        if action.lower() in {"now", "scan", "test"}:
            await ctx.send("🔎 Running the Keepa Amazon lead scan now…")
            posted = await self._run_scan(force=True)
            if self.last_error != "None":
                await ctx.send(f"❌ Scan failed: {self.last_error}")
            else:
                await ctx.send(f"✅ Scan finished; {posted} lead(s) posted.")
            return
        configured = sum(bool(v.strip()) for v in self.channel_ids.values())
        stats = self.state.get("last_scan_stats", {})
        funnel = (
            f"Discovered: {stats.get('discovered', 'N/A')} • "
            f"Analyzed: {stats.get('products', 'N/A')} • "
            f"Posted candidates: {stats.get('qualified', 'N/A')} "
            f"(ROI: {stats.get('roi_leads', 'N/A')} • Velocity review: {stats.get('velocity_review', 'N/A')}) • "
            f"Next batch starts at: {stats.get('next_cursor', 'N/A')}"
        )
        await ctx.send(
            f"**Amazon lead scanner**: every {self.minutes} min • {configured}/3 channels configured\n"
            f"Last scan: {self.state.get('last_scan', 'Not yet')} • Last error: {self.last_error}\n"
            f"{funnel}"
        )

    async def _run_scan(self, force=False):
        try:
            permission_issues = self._permission_issues()
            if permission_issues:
                self.last_error = "Discord permissions missing: " + "; ".join(permission_issues)
                return 0
            leads = await asyncio.to_thread(self.engine.scan)
            posted = 0
            for lead in leads:
                signature = f"{lead.lead_type}:{lead.lane}:{lead.amazon_price}:{lead.exit_price}:{lead.roi}:{lead.sellers}"
                if not force and self.state.get("seen", {}).get(lead.asin) == signature:
                    continue
                channel = self._channel(lead.lane)
                if channel is None:
                    continue
                embed = self._embed(lead)
                can_attach = channel.permissions_for(channel.guild.me).attach_files
                chart = await asyncio.to_thread(self.engine.chart_png, lead) if can_attach else None
                file = None
                if chart:
                    file = discord.File(io.BytesIO(chart), filename=f"keepa_{lead.asin}.png")
                    embed.set_image(url=f"attachment://keepa_{lead.asin}.png")
                elif not can_attach:
                    embed.add_field(
                        name="Chart",
                        value="Discord Attach Files is disabled here. Use the Keepa link above for the full chart.",
                        inline=False,
                    )
                if file:
                    await channel.send(embed=embed, file=file, allowed_mentions=discord.AllowedMentions.none())
                else:
                    await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                self.state.setdefault("seen", {})[lead.asin] = signature
                posted += 1
            self.state["last_scan"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.state["last_count"] = len(leads)
            self.state["last_scan_stats"] = self.engine.last_scan_stats
            self.last_error = "None"
            self._save_state()
            return posted
        except Exception as error:
            self.last_error = str(error)[:240]
            print(f"❌ Amazon lead scan error: {error!r}")
            return 0

    def _permission_issues(self):
        issues = []
        labels = {
            "hold": "AMAZON_HOLD_LEADS_CHANNEL_ID",
            "pressure": "AMAZON_STOCK_PRESSURE_CHANNEL_ID",
            "review": "AMAZON_LEAD_REVIEW_CHANNEL_ID",
        }
        required = ("view_channel", "send_messages", "embed_links")
        for lane, env_name in labels.items():
            channel = self._channel(lane)
            if channel is None:
                issues.append(f"{env_name} does not resolve to a visible channel")
                continue
            member = channel.guild.me
            permissions = channel.permissions_for(member)
            missing = [name.replace("_", " ").title() for name in required if not getattr(permissions, name, False)]
            if missing:
                issues.append(f"#{channel.name}: {', '.join(missing)}")
        return issues

    def _channel(self, lane):
        raw = self.channel_ids.get(lane, "").strip()
        if not raw.isdigit():
            return None
        return self.bot.get_channel(int(raw))

    def _embed(self, lead):
        label = {"hold": "BUY / HOLD", "pressure": "STOCK PRESSURE", "review": "REVIEW"}[lead.lane]
        color = {"hold": discord.Color.green(), "pressure": discord.Color.orange(), "review": discord.Color.blurple()}[lead.lane]
        embed = discord.Embed(title=f"{label} • {lead.brand}", description=lead.title, color=color, url=lead.amazon_url)
        money = lambda value: f"${value:,.2f}" if value is not None else "N/A"
        number = lambda value: f"{value:,}" if value is not None else "N/A"
        max_buy = self.engine.max_buy_price(lead)
        embed.add_field(name="Amazon buy", value=money(lead.amazon_price), inline=True)
        embed.add_field(name="Historical exit", value=money(lead.exit_price), inline=True)
        embed.add_field(name="Est. profit / ROI", value=f"{money(lead.profit)} / {lead.roi:.1f}%" if lead.roi is not None else "N/A", inline=True)
        embed.add_field(name="Lead type", value="ROI qualified" if lead.lead_type == "roi-qualified" else "High-velocity manual review", inline=True)
        embed.add_field(name="Max buy @ target ROI", value=money(max_buy), inline=True)
        embed.add_field(name="Velocity", value=f"{number(lead.monthly_sold)} monthly • {number(lead.drops30)} drops/30d", inline=True)
        embed.add_field(name="Rank / sellers", value=f"{number(lead.rank)} / {number(lead.sellers)}", inline=True)
        stock_recency = f"{lead.amazon_last_in_stock_days} day(s) ago" if lead.amazon_last_in_stock_days is not None else "N/A"
        embed.add_field(name="Amazon stock cycle", value=f"Last stocked: {stock_recency} • {lead.amazon_stock_changes90} change(s)/90d", inline=False)
        embed.add_field(name="Lead methods", value=lead.methods[:1000], inline=False)
        embed.add_field(name="Why it surfaced", value=lead.reason, inline=False)
        embed.add_field(name="Review", value=f"[Amazon]({lead.amazon_url}) • [Keepa]({lead.keepa_url})", inline=False)
        embed.set_footer(text=f"Score {lead.score}/100 • Fee estimate only • Check eligibility, tax and exact FBA fees before buying")
        return embed

    def _load_state(self):
        try:
            return json.loads(self.state_file.read_text()) if self.state_file.exists() else {}
        except Exception:
            return {}

    def _save_state(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.state, indent=2))


async def setup(bot):
    await bot.add_cog(AmazonLeads(bot))
