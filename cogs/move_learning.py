import asyncio
import json
import os
from pathlib import Path
from time import monotonic

import discord
from discord.ext import commands, tasks

from market.watchlist_engine import WatchlistEngine


VERSION = "MarketOps Move Learning v1.0.0"


class MoveLearning(commands.Cog):
    """Automated stock-move lessons for #stock-move-lessons.

    Watches the normal MarketOps watchlist. When a symbol drops or spikes enough,
    it posts a learning card: Identify -> Translate -> Confirm.
    """

    def __init__(self, bot):
        self.bot = bot
        self.engine = WatchlistEngine()
        self.enabled = self._env_bool("MOVE_LEARNING_ENABLED", default=True)
        self.channel_name = os.getenv("MOVE_LEARNING_CHANNEL", "stock-move-lessons").strip()
        self.poll_minutes = float(os.getenv("MOVE_LEARNING_POLL_MINUTES", "15"))
        self.threshold = float(os.getenv("MOVE_LEARNING_THRESHOLD_PERCENT", "2"))
        self.max_headlines = int(os.getenv("MOVE_LEARNING_MAX_HEADLINES", "3"))
        self.post_no_headline = self._env_bool("MOVE_LEARNING_POST_NO_HEADLINE", default=True)
        self.memory_path = Path("data/stock_move_lessons.json")
        self.memory = self._load_memory()
        self._last_poll = 0.0
        self._last_check = "Not checked yet"
        self._last_post = "Not posted yet"
        self._last_error = "None"

        if self.enabled and not self.move_learning_loop.is_running():
            self.move_learning_loop.start()

    def cog_unload(self):
        if self.move_learning_loop.is_running():
            self.move_learning_loop.cancel()

    @commands.command(name="movelesson", aliases=["stockmove", "movelearn", "droplesson", "stockdrop", "dropwatch", "spikelesson", "stockspike"])
    async def movelesson_prefix(self, ctx, symbol: str = None):
        try:
            lessons = await asyncio.to_thread(self._build_lessons, symbol, True)
            if not lessons:
                await ctx.send(embed=self._no_move_embed(symbol))
                return
            for lesson in lessons[:5]:
                await ctx.send(embed=self._lesson_embed(lesson))
        except Exception as error:
            print(f"❌ !movelesson error: {error!r}")
            await ctx.send("⚠️ MarketOps had trouble building the stock-move lesson. Check the terminal for the error.")

    @commands.command(name="movepost", aliases=["droppost", "spikepost"])
    async def movepost_prefix(self, ctx):
        try:
            if ctx.guild is None:
                await ctx.send("⚠️ Run this inside the Discord server.")
                return
            channel = self._find_text_channel(ctx.guild, self.channel_name)
            if channel is None:
                await ctx.send(f"⚠️ I cannot find `#{self.channel_name}`. Create it or change `MOVE_LEARNING_CHANNEL` in `.env`.")
                return
            lessons = await asyncio.to_thread(self._build_lessons, None, True)
            if not lessons:
                await ctx.send(embed=self._no_move_embed())
                return
            for lesson in lessons[:5]:
                await channel.send(embed=self._lesson_embed(lesson), allowed_mentions=discord.AllowedMentions.none())
            await ctx.send(f"✅ Posted {min(len(lessons), 5)} stock-move lesson(s) to #{channel.name}.")
        except Exception as error:
            print(f"❌ !movepost error: {error!r}")
            await ctx.send("⚠️ MarketOps had trouble posting stock-move lessons. Check the terminal for the error.")

    @commands.command(name="movestatus", aliases=["dropstatus", "spikestatus"])
    async def movestatus_prefix(self, ctx):
        await ctx.send(embed=self._status_embed())

    @commands.command(name="movehelp", aliases=["drophelp", "spikehelp"])
    async def movehelp_prefix(self, ctx):
        await ctx.send(embed=self._help_embed())

    @tasks.loop(seconds=30)
    async def move_learning_loop(self):
        await self.bot.wait_until_ready()
        if not self.enabled:
            return

        if monotonic() - self._last_poll < self.poll_minutes * 60:
            return
        self._last_poll = monotonic()

        try:
            lessons = await asyncio.to_thread(self._build_lessons, None, False)
            self._last_check = self._timestamp()
            if not lessons:
                return
            for guild in self.bot.guilds:
                channel = self._find_text_channel(guild, self.channel_name)
                if channel is None:
                    self._last_error = f"Missing channel #{self.channel_name} in {guild.name}"
                    print(f"⚠️ {self._last_error}")
                    continue
                for lesson in lessons[:5]:
                    await channel.send(embed=self._lesson_embed(lesson), allowed_mentions=discord.AllowedMentions.none())
                self._last_post = self._timestamp()
                self._last_error = "None"
        except Exception as error:
            self._last_error = repr(error)
            print(f"❌ Stock move learning loop error: {error!r}")

    def _build_lessons(self, symbol=None, force=False):
        symbols = [self.engine._normalize_symbol(symbol)] if symbol else list(self.engine.symbols)
        news_items = self.engine._get_news_items()
        lessons = []
        today_key = self._today_key()

        for raw_symbol in symbols:
            if not raw_symbol:
                continue

            quote = self.engine._quote(raw_symbol)
            if quote.get("status") == "Unavailable":
                continue

            change_percent = self.engine._safe_float(quote.get("change_percent"))
            direction = self._direction(change_percent)

            if symbol and force:
                pass
            elif abs(change_percent) < abs(self.threshold):
                continue
            elif quote.get("stale") and not force:
                continue

            matched_headlines = self._matched_headlines(raw_symbol, news_items)
            if not matched_headlines and not self.post_no_headline and not force:
                continue

            memory_key = f"{today_key}:{raw_symbol}:{direction}"
            if not force and memory_key in self.memory:
                continue

            lesson = self._build_lesson(raw_symbol, quote, change_percent, direction, matched_headlines)
            lessons.append(lesson)

            if not force:
                self.memory[memory_key] = {
                    "symbol": raw_symbol,
                    "direction": direction,
                    "change_percent": change_percent,
                    "headline_count": len(matched_headlines),
                    "created": self._timestamp(),
                }

        if lessons and not force:
            self._save_memory()

        lessons.sort(key=lambda item: abs(item.get("change_percent", 0)), reverse=True)
        return lessons

    def _matched_headlines(self, symbol, news_items):
        matches = []
        for item in news_items:
            try:
                matched_symbols = self.engine._match_symbols_to_headline(item)
            except Exception:
                matched_symbols = []
            if symbol in matched_symbols:
                matches.append(item)
            if len(matches) >= self.max_headlines:
                break
        return matches

    def _build_lesson(self, symbol, quote, change_percent, direction, headlines):
        first_headline = headlines[0].get("title", "") if headlines else ""
        return {
            "symbol": symbol,
            "label": quote.get("label", symbol),
            "price": self.engine._price_text(quote.get("price", 0), quote.get("kind")),
            "status": quote.get("status", "Unknown"),
            "change_percent": change_percent,
            "direction": direction,
            "data_confidence": self.engine._data_confidence(quote),
            "headlines": headlines,
            "identify": self._identify(symbol, change_percent, direction, first_headline),
            "translate": self._translate(direction, first_headline),
            "confirm": self._confirm(symbol, direction, bool(headlines)),
        }

    def _direction(self, change_percent):
        if change_percent <= -abs(self.threshold):
            return "down"
        if change_percent >= abs(self.threshold):
            return "up"
        return "flat"

    def _identify(self, symbol, change_percent, direction, headline):
        move_word = "down" if direction == "down" else "up" if direction == "up" else "moving"
        if not headline:
            return f"{symbol} is {move_word} {change_percent:+.2f}%, but no matching fresh headline was found. First decide if this is company-specific, sector-wide, or market-wide."

        text = headline.lower()
        if any(term in text for term in ("earnings", "guidance", "outlook", "forecast", "profit", "revenue")):
            event = "earnings/guidance event"
        elif any(term in text for term in ("upgrade", "downgrade", "price target", "analyst")):
            event = "analyst/expectations event"
        elif any(term in text for term in ("contract", "deal", "approval", "order", "partnership", "acquisition", "merger")):
            event = "deal/contract/growth event"
        elif any(term in text for term in ("lawsuit", "probe", "investigation", "sec", "doj", "ftc", "antitrust", "ban")):
            event = "legal/regulatory risk event"
        elif any(term in text for term in ("layoff", "job cuts", "strike", "shutdown", "plant", "factory")):
            event = "labor/operations/cost event"
        elif any(term in text for term in ("fed", "rate", "rates", "inflation", "yield", "treasury", "dollar")):
            event = "macro/rates event"
        elif any(term in text for term in ("oil", "opec", "iran", "russia", "ukraine", "israel", "sanctions", "tariff", "war")):
            event = "macro/geopolitical event"
        elif any(term in text for term in ("ai", "chip", "gpu", "semiconductor", "data center", "openai", "nvidia", "amd")):
            event = "AI/chip demand event"
        else:
            event = "possible company or sector news event"

        return f"{symbol} is {move_word} {change_percent:+.2f}%. The closest headline looks like a **{event}**."

    def _translate(self, direction, headline):
        if not headline:
            if direction == "down":
                return "Possible economics: broad risk-off selling, sector weakness, profit-taking, or company-specific news not found yet."
            if direction == "up":
                return "Possible economics: broad risk-on buying, sector strength, short covering, momentum, or company-specific good news not found yet."
            return "Move is below the normal lesson threshold. Use this as practice only."

        text = headline.lower()
        impacts = []
        if any(term in text for term in ("revenue", "sales", "demand", "orders", "deliveries")):
            impacts.append("revenue/demand")
        if any(term in text for term in ("cost", "inflation", "wages", "labor", "strike", "plant", "factory", "supply")):
            impacts.append("costs/supply/margins")
        if any(term in text for term in ("guidance", "outlook", "forecast", "profit", "earnings")):
            impacts.append("future expectations")
        if any(term in text for term in ("upgrade", "downgrade", "target", "analyst")):
            impacts.append("investor expectations")
        if any(term in text for term in ("contract", "deal", "approval", "partnership", "order")):
            impacts.append("future revenue/growth")
        if any(term in text for term in ("lawsuit", "probe", "investigation", "ban", "antitrust", "fine")):
            impacts.append("legal/regulatory risk")
        if any(term in text for term in ("fed", "rate", "rates", "inflation", "yield", "treasury", "dollar")):
            impacts.append("macro/rates pressure")
        if any(term in text for term in ("oil", "opec", "war", "attack", "sanctions", "tariff")):
            impacts.append("macro/geopolitical pressure")
        if not impacts:
            impacts.append("sentiment or sector risk")

        direction_note = "bullish" if direction == "up" else "bearish" if direction == "down" else "neutral/practice"
        return f"Possible economic impact: **{', '.join(impacts[:4])}**. Initial read: **{direction_note}**, but confirm with price, volume, and sector reaction."

    def _confirm(self, symbol, direction, has_headline):
        base = [
            f"Run `!chart {symbol} 1d` and check whether the move is holding or fading.",
            "Compare against `!chart SPY 1d` and `!chart QQQ 1d`.",
            "Check volume and whether similar stocks in the same sector are moving too.",
        ]
        if direction == "down":
            base.append("If the stock is down alone, look for company-specific damage. If the sector is down too, it may be sector/broad-market pressure.")
        elif direction == "up":
            base.append("If the stock is up alone, look for company-specific upside. If the sector is up too, it may be sector/broad-market strength.")
        if not has_headline:
            base.append("No matching fresh headline was found, so treat this as a price-action lesson first, not confirmed news.")
        return "\n".join(f"• {item}" for item in base[:5])

    def _lesson_embed(self, lesson):
        direction = lesson.get("direction")
        emoji = "🔴" if direction == "down" else "🟢" if direction == "up" else "🟡"
        title_word = "Stock Drop Lesson" if direction == "down" else "Stock Spike Lesson" if direction == "up" else "Stock Move Lesson"
        color = discord.Color.red() if direction == "down" else discord.Color.green() if direction == "up" else discord.Color.gold()

        embed = discord.Embed(
            title=f"{emoji} {title_word}: {lesson.get('symbol')} {lesson.get('change_percent'):+.2f}%",
            description="Do not read the move emotionally. Read it economically: Identify → Translate → Confirm.",
            color=color,
        )
        embed.add_field(
            name="Price Move",
            value=(
                f"Symbol: **{lesson.get('symbol')}** ({lesson.get('label')})\n"
                f"Price: **{lesson.get('price')}**\n"
                f"Status: **{lesson.get('status')}**\n"
                f"Data: **{lesson.get('data_confidence')}**"
            ),
            inline=False,
        )
        embed.add_field(name="1️⃣ Identify", value=lesson.get("identify", "Unknown"), inline=False)
        embed.add_field(name="2️⃣ Translate the Economics", value=lesson.get("translate", "Unknown"), inline=False)
        embed.add_field(name="3️⃣ Confirm", value=lesson.get("confirm", "Use charts and sources to confirm."), inline=False)

        headlines = lesson.get("headlines", [])
        if headlines:
            lines = []
            for item in headlines[: self.max_headlines]:
                title = discord.utils.escape_markdown(item.get("title", "Untitled"))
                source = item.get("source", "Unknown")
                age = self.engine._age_label(item.get("published_dt"))
                link = (item.get("link") or "").replace(" ", "%20")
                if link:
                    lines.append(f"• **{title}** — {source}, {age}\n  [Open](<{link}>)")
                else:
                    lines.append(f"• **{title}** — {source}, {age}")
            embed.add_field(name="Possible Related Headlines", value="\n".join(lines)[:1024], inline=False)
        else:
            embed.add_field(name="Possible Related Headlines", value="No matching fresh headline found yet. This may be price action, sector movement, or delayed news.", inline=False)

        embed.set_footer(text=f"Checked {self._timestamp()} • {VERSION}")
        return embed

    def _no_move_embed(self, symbol=None):
        target = f" for `{symbol}`" if symbol else ""
        embed = discord.Embed(
            title="🟡 No Stock-Move Lesson Triggered",
            description=f"No watchlist move{target} passed the lesson filter right now.",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Threshold", value=f"±{self.threshold:g}%", inline=True)
        embed.add_field(name="Channel", value=f"#{self.channel_name}", inline=True)
        embed.add_field(name="Try", value="Use `!movelesson TSLA`, `!movelesson NVDA`, or lower the threshold in `.env` if you want more lessons.", inline=False)
        embed.set_footer(text=f"Checked {self._timestamp()} • {VERSION}")
        return embed

    def _status_embed(self):
        embed = discord.Embed(
            title="⚙️ Stock-Move Lesson Status",
            description="Automatic lessons for big watchlist drops and spikes.",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Enabled", value="ON" if self.enabled else "OFF", inline=True)
        embed.add_field(name="Channel", value=f"#{self.channel_name}", inline=True)
        embed.add_field(name="Poll Time", value=f"{self.poll_minutes:g} minutes", inline=True)
        embed.add_field(name="Move Threshold", value=f"±{self.threshold:g}%", inline=True)
        embed.add_field(name="Post Without Headline", value="YES" if self.post_no_headline else "NO", inline=True)
        embed.add_field(name="Last Check", value=self._last_check, inline=True)
        embed.add_field(name="Last Post", value=self._last_post, inline=True)
        embed.add_field(name="Last Error", value=self._last_error, inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _help_embed(self):
        embed = discord.Embed(
            title="📚 Stock-Move Lessons Help",
            description="This channel teaches why stocks drop or spike.",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Manual", value="`!movelesson`\n`!movelesson TSLA`\n`!stockmove NVDA`", inline=False)
        embed.add_field(name="Auto Post", value="`!movepost` posts current lessons to the configured channel.", inline=False)
        embed.add_field(name="Status", value="`!movestatus` shows settings and last error.", inline=False)
        embed.add_field(name="Framework", value="Identify the event → Translate the economics → Confirm with chart/market reaction.", inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _find_text_channel(self, guild, target_name):
        target = self._clean_channel_name(target_name)
        for channel in guild.text_channels:
            if self._clean_channel_name(channel.name).endswith(target):
                return channel
        return None

    def _clean_channel_name(self, channel_name):
        cleaned = (channel_name or "").strip().lower()
        for separator in ("|", "┃", "│"):
            if separator in cleaned:
                cleaned = cleaned.split(separator)[-1].strip()
        while cleaned and not cleaned[0].isalnum():
            cleaned = cleaned[1:].strip()
        return cleaned.replace(" ", "-")

    def _load_memory(self):
        if not self.memory_path.exists():
            return {}
        try:
            with self.memory_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_memory(self):
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        with self.memory_path.open("w", encoding="utf-8") as file:
            json.dump(self.memory, file, indent=2)

    def _today_key(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")

    def _timestamp(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%I:%M %p PT").lstrip("0")

    def _env_bool(self, name, default=False):
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in ("1", "true", "yes", "y", "on")


async def setup(bot):
    await bot.add_cog(MoveLearning(bot))