import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord.ext import commands, tasks

from market.storefront_engine import StorefrontEngine


class Storefronts(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.engine = StorefrontEngine()
        self.minutes = max(5, int(os.getenv("STOREFRONT_CHECK_MINUTES", "10")))
        self.product_delay = max(10, int(os.getenv("STOREFRONT_PRODUCT_DELAY_SECONDS", "20")))
        self.state_file = Path("data/storefront_state.json")
        self.state = self._load_state()
        self.state.setdefault("stores", {})
        self.last_error = "None"
        self.lock = asyncio.Lock()
        self.monitor.change_interval(minutes=self.minutes)
        self.monitor.start()

    def cog_unload(self):
        self.monitor.cancel()

    @tasks.loop(minutes=10)
    async def monitor(self):
        await self.bot.wait_until_ready()
        await self._scan_all()

    @monitor.before_loop
    async def before_monitor(self):
        await self.bot.wait_until_ready()
        # Let the bot finish connecting, then begin loading saved storefronts
        # automatically without requiring a manual scan command.
        await asyncio.sleep(60)

    @commands.group(name="storefront", invoke_without_command=True)
    async def storefront(self, ctx):
        stores = self.state.get("stores", {})
        await ctx.send(
            "**Amazon storefront monitor**\n"
            f"Watching: {len(stores)} storefront(s) • automatic scan: every {self.minutes} minutes\n"
            f"Pacing: one product about every {self.product_delay} seconds\n"
            f"Last scan: {self.state.get('last_scan', 'Not yet')} • Last error: {self.last_error}\n\n"
            "`!storefront add <URL or seller ID>`\n"
            "`!storefront list` • `!storefront scan` • `!storefront remove <seller ID>`"
        )

    @storefront.command(name="add")
    async def add_storefront(self, ctx, *, value: str):
        await ctx.send("🔎 Reading that Amazon storefront…")
        try:
            seller_id = await asyncio.to_thread(self.engine.resolve_seller_id, value)
            name, asins = await asyncio.to_thread(self.engine.storefront, seller_id)
            stores = self.state.setdefault("stores", {})
            existing = stores.get(seller_id, {})
            stores[seller_id] = {
                "name": name, "channel_id": str(ctx.channel.id), "seen": existing.get("seen", []),
                "added_at": existing.get("added_at") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "last_found": len(asins),
            }
            self._save_state()
            await ctx.send(
                f"✅ Added **{name}** (`{seller_id}`) with {len(asins)} public product(s).\n"
                f"Products will begin loading automatically in {ctx.channel.mention}."
            )
        except Exception as error:
            await ctx.send(f"❌ Could not add storefront: {str(error)[:500]}")

    @storefront.command(name="list")
    async def list_storefronts(self, ctx):
        stores = self.state.get("stores", {})
        if not stores:
            await ctx.send("No storefronts are saved yet. Use `!storefront add <URL or seller ID>`.")
            return
        lines = []
        for seller_id, store in stores.items():
            channel_id = store.get("channel_id")
            channel = self.bot.get_channel(int(channel_id)) if str(channel_id).isdigit() else None
            lines.append(f"• **{store.get('name', seller_id)}** — `{seller_id}` — {len(store.get('seen', []))} posted — {channel.mention if channel else 'channel unavailable'}")
        await ctx.send("**Watched storefronts**\n" + "\n".join(lines))

    @storefront.command(name="scan", aliases=["now"])
    async def scan_storefronts(self, ctx):
        await ctx.send("🔎 Loading new storefront products for manual review…")
        posted = await self._scan_all()
        if self.last_error != "None":
            await ctx.send(f"❌ Storefront scan stopped: {self.last_error}")
        else:
            await ctx.send(f"✅ Storefront scan finished; {posted} new product(s) posted.")

    @storefront.command(name="remove", aliases=["delete"])
    async def remove_storefront(self, ctx, *, value: str):
        try:
            seller_id = await asyncio.to_thread(self.engine.resolve_seller_id, value)
        except Exception:
            seller_id = value.strip().upper()
        store = self.state.setdefault("stores", {}).pop(seller_id, None)
        if not store:
            await ctx.send("That seller ID is not in the storefront monitor.")
            return
        self._save_state()
        await ctx.send(f"✅ Removed **{store.get('name', seller_id)}** from monitoring.")

    @storefront.command(name="reset")
    async def reset_storefront(self, ctx, *, value: str):
        try:
            seller_id = await asyncio.to_thread(self.engine.resolve_seller_id, value)
        except Exception:
            seller_id = value.strip().upper()
        store = self.state.setdefault("stores", {}).get(seller_id)
        if not store:
            await ctx.send("That seller ID is not in the storefront monitor.")
            return
        store["seen"] = []
        self._save_state()
        await ctx.send("✅ Cleared posted-product history. The next scan will start loading that storefront again.")

    async def _scan_all(self):
        if self.lock.locked():
            self.last_error = "A storefront scan is already running."
            return 0
        async with self.lock:
            total = 0
            self.last_error = "None"
            try:
                for seller_id, store in self.state.get("stores", {}).items():
                    name, asins = await self._keepa_call(self.engine.storefront, seller_id)
                    store["name"] = name; store["last_found"] = len(asins)
                    seen = set(store.get("seen", []))
                    pending = [asin for asin in asins if asin not in seen]
                    attempted = pending[: self.engine.batch_size]
                    channel_id = str(store.get("channel_id", ""))
                    channel = self.bot.get_channel(int(channel_id)) if channel_id.isdigit() else None
                    if channel is None:
                        raise RuntimeError(f"Saved Discord channel is unavailable for {name}.")
                    permissions = channel.permissions_for(channel.guild.me)
                    if not permissions.send_messages or not permissions.embed_links:
                        raise RuntimeError(f"Discord permissions missing in #{channel.name}: Send Messages and Embed Links are required.")
                    for index, asin in enumerate(attempted):
                        products = await self._keepa_call(self.engine.products, [asin])
                        for product in products:
                            await channel.send(embed=self._embed(product, name, seller_id), allowed_mentions=discord.AllowedMentions.none())
                            total += 1
                        # Save after every ASIN so a restart continues where it
                        # stopped. Omitted/deleted ASINs cannot block the queue.
                        seen.add(asin)
                        store["seen"] = sorted(seen)
                        self._save_state()
                        if index < len(attempted) - 1:
                            await asyncio.sleep(self.product_delay)
                self.state["last_scan"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                self._save_state()
            except Exception as error:
                self.last_error = str(error)[:500]
                print(f"❌ Storefront scan error: {error!r}")
            return total

    async def _keepa_call(self, function, *args):
        """Wait for Keepa's stated refill time and resume the same operation."""
        for attempt in range(3):
            try:
                return await asyncio.to_thread(function, *args)
            except RuntimeError as error:
                match = re.search(r"Retry in about (\d+) minute", str(error), re.I)
                if not match or attempt == 2:
                    raise
                wait_seconds = max(self.product_delay, min(600, int(match.group(1)) * 60 + 5))
                print(f"⏳ Keepa refill pause: {wait_seconds} seconds")
                await asyncio.sleep(wait_seconds)

    @staticmethod
    def _embed(product, store_name, seller_id):
        embed = discord.Embed(
            title=product.title, url=product.amazon_url,
            description=f"New product detected from **{store_name}**\nThis is a raw storefront product for manual review—not a profit claim.",
            color=discord.Color.teal(),
        )
        money = f"${product.price:,.2f}" if product.price is not None else "N/A"
        rank = f"{product.rank:,}" if product.rank is not None else "N/A"
        sellers = f"{product.sellers:,}" if product.sellers is not None else "N/A"
        stock = "In stock" if product.amazon_in_stock is True else "Out of stock" if product.amazon_in_stock is False else "Unknown"
        embed.add_field(name="Brand", value=product.brand, inline=True)
        embed.add_field(name="Current price", value=money, inline=True)
        embed.add_field(name="Sales rank", value=rank, inline=True)
        embed.add_field(name="Amazon", value=stock, inline=True)
        embed.add_field(name="New offers", value=sellers, inline=True)
        embed.add_field(name="ASIN", value=f"`{product.asin}`", inline=True)
        embed.add_field(name="Review manually", value=f"[Amazon]({product.amazon_url}) • [Keepa]({product.keepa_url})", inline=False)
        if product.image_url:
            embed.set_thumbnail(url=product.image_url)
        embed.set_footer(text=f"Seller {seller_id} • First detected {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
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
    await bot.add_cog(Storefronts(bot))
