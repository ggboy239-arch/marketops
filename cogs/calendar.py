import asyncio
import json
import os
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

import discord
from discord.ext import commands, tasks


VERSION = "MarketOps v2.8.2"


class MarketCalendar(commands.Cog):
    """Official event-only calendar alerts.

    This does not post daily reminder spam. It pulls official sources, stores
    upcoming events, posts event lists to #market-calendar, and posts countdown
    alerts to #calendar-event-reminder only when an event is coming up.
    """

    EVENTS_FILE = Path("data/calendar_events.json")

    BLS_ICS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
    FED_CALENDAR_URL = "https://www.federalreserve.gov/newsevents/calendar.htm"
    FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
    WHITE_HOUSE_FEED = "https://www.whitehouse.gov/briefings-statements/feed/"

    IMPORTANT_TERMS = (
        "cpi", "consumer price", "employment situation", "jobs", "unemployment",
        "ppi", "producer price", "pce", "inflation", "fomc", "federal open market",
        "powell", "chair", "monetary policy", "interest rate", "rate decision",
        "federal reserve", "fed", "treasury", "white house", "president",
        "press briefing", "remarks", "tariff", "sanction", "oil", "energy",
        "china", "russia", "ukraine", "iran", "israel", "opec",
    )

    REMINDER_WINDOWS = [
        ("24h", 24 * 60, 35),
        ("1h", 60, 10),
        ("30m", 30, 6),
        ("5m", 5, 3),
        ("start", 0, 3),
    ]

    def __init__(self, bot):
        self.bot = bot
        self.calendar_channel_name = os.getenv("MARKETOPS_CALENDAR_CHANNEL", "market-calendar")
        self.reminder_channel_name = os.getenv("MARKETOPS_CALENDAR_REMINDER_CHANNEL", "calendar-event-reminder")
        self.auto_post = os.getenv("MARKETOPS_CALENDAR_AUTO_POST", "true").strip().lower() in {"1", "true", "yes", "on"}
        self.fetch_minutes = max(15, int(os.getenv("MARKETOPS_CALENDAR_FETCH_MINUTES", "60")))
        self.window_days = int(os.getenv("MARKETOPS_CALENDAR_WINDOW_DAYS", "14"))
        self.calendar_loop.change_interval(minutes=self.fetch_minutes)
        self.calendar_loop.start()

    def cog_unload(self):
        self.calendar_loop.cancel()

    @commands.command(name="calendar", aliases=["marketcalendar", "cal", "calendarhelp"])
    async def calendar_prefix(self, ctx):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a MarketOps admin can view the calendar helper.")
            return
        await ctx.send(embed=self._help_embed())

    @commands.command(name="calendarfetch", aliases=["calfetch", "refreshcalendar"])
    async def calendarfetch_prefix(self, ctx):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a MarketOps admin can pull official calendar events.")
            return
        await ctx.send("🔎 Pulling official market-calendar sources now...")
        result = await asyncio.to_thread(self._fetch_and_store_events)
        await ctx.send(embed=self._fetch_result_embed(result))

    @commands.command(name="events", aliases=["calendarlist", "eventlist", "upcoming"])
    async def events_prefix(self, ctx):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a MarketOps admin can view upcoming calendar events.")
            return
        await ctx.send(embed=self._events_embed("upcoming"))

    @commands.command(name="calendartoday", aliases=["todaycal", "todaycalendar"])
    async def calendartoday_prefix(self, ctx):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a MarketOps admin can view today’s events.")
            return
        await ctx.send(embed=self._events_embed("today"))

    @commands.command(name="calendarweek", aliases=["weekcal", "weeklycalendar"])
    async def calendarweek_prefix(self, ctx):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a MarketOps admin can view this week’s events.")
            return
        await ctx.send(embed=self._events_embed("week"))

    @commands.command(name="calendarstatus", aliases=["calstatus"])
    async def calendarstatus_prefix(self, ctx):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a MarketOps admin can view calendar status.")
            return
        events = self._future_events(self._read_events().get("events", {}).values())
        embed = discord.Embed(
            title="🗓️ MarketOps Calendar Status",
            description="Official-source, event-only alerts. No empty daily reminder spam.",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Auto Pull/Post", value="ON" if self.auto_post else "OFF", inline=True)
        embed.add_field(name="Calendar Channel", value=f"#{self.calendar_channel_name}", inline=True)
        embed.add_field(name="Reminder Channel", value=f"#{self.reminder_channel_name}", inline=True)
        embed.add_field(name="Fetch Every", value=f"{self.fetch_minutes} min", inline=True)
        embed.add_field(name="Upcoming Stored", value=str(len(events)), inline=True)
        embed.add_field(name="Reminder Posts", value="24h • 1h • 30m • 5m • starting now", inline=False)
        embed.set_footer(text=VERSION)
        await ctx.send(embed=embed)

    @commands.command(name="calendaron", aliases=["calon"])
    async def calendaron_prefix(self, ctx):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a MarketOps admin can turn calendar alerts on.")
            return
        self.auto_post = True
        await ctx.send("✅ Official calendar alerts are ON. No-event days stay quiet.")

    @commands.command(name="calendaroff", aliases=["caloff"])
    async def calendaroff_prefix(self, ctx):
        if not self._is_admin(ctx):
            await ctx.send("⚠️ Only a MarketOps admin can turn calendar alerts off.")
            return
        self.auto_post = False
        await ctx.send("🛑 Official calendar alerts are OFF for this bot session.")

    @tasks.loop(minutes=60)
    async def calendar_loop(self):
        if not self.auto_post or not self.bot.guilds:
            return

        result = await asyncio.to_thread(self._fetch_and_store_events)
        events = self._future_events(self._read_events().get("events", {}).values())
        if not events:
            return

        due_alerts = self._due_alerts(events)
        if not due_alerts:
            return

        for guild in self.bot.guilds:
            reminder_channel = self._find_text_channel(guild, self.reminder_channel_name)
            if reminder_channel is None:
                reminder_channel = self._find_text_channel(guild, self.calendar_channel_name)
            if reminder_channel is None:
                continue
            for event, reminder_type in due_alerts:
                await reminder_channel.send(embed=self._event_alert_embed(event, reminder_type))

        self._mark_alerts_posted(due_alerts)

    @calendar_loop.before_loop
    async def before_calendar_loop(self):
        await self.bot.wait_until_ready()

    def _fetch_and_store_events(self):
        fetched = []
        errors = []
        for source_name, fetcher in (
            ("BLS", self._fetch_bls_ics),
            ("Federal Reserve", self._fetch_fed_calendar),
            ("FOMC", self._fetch_fomc),
            ("White House", self._fetch_white_house_feed),
        ):
            try:
                fetched.extend(fetcher())
            except Exception as error:
                errors.append(f"{source_name}: {error}")

        now_utc = datetime.now(timezone.utc)
        window_end = now_utc + timedelta(days=self.window_days)
        filtered = []
        seen = set()

        for event in fetched:
            event_time = self._parse_iso(event.get("event_time_utc"))
            if not event_time or event_time < now_utc - timedelta(hours=2) or event_time > window_end:
                continue
            if not self._is_market_relevant(event):
                continue
            event_id = event.get("id") or self._event_key(event)
            if event_id in seen:
                continue
            seen.add(event_id)
            event["id"] = event_id
            filtered.append(event)

        data = self._read_events()
        data.setdefault("events", {})
        for event in filtered:
            old = data["events"].get(event["id"], {})
            event["posted_reminders"] = old.get("posted_reminders", [])
            event["first_seen_at"] = old.get("first_seen_at") or now_utc.isoformat()
            event["last_seen_at"] = now_utc.isoformat()
            data["events"][event["id"]] = event

        self._write_events(data)
        filtered.sort(key=lambda item: item.get("event_time_utc") or "")
        return {"events": filtered, "errors": errors}

    def _fetch_bls_ics(self):
        text = self._get_url(self.BLS_ICS_URL)
        events = []
        for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, flags=re.S):
            summary = self._ics_field(block, "SUMMARY")
            dtstart = self._ics_field(block, "DTSTART")
            url = self._ics_field(block, "URL") or self.BLS_ICS_URL
            if not summary or not dtstart:
                continue
            event_time = self._parse_ics_datetime(dtstart)
            if not event_time:
                continue
            events.append(self._make_event(
                source="BLS official calendar",
                title=summary,
                event_time_utc=event_time,
                why="Scheduled BLS economic data can move inflation expectations, yields, SPY, QQQ, VIX, DXY, gold, and BTC.",
                watch="SPY, QQQ, VIX, DXY, 10Y, Gold, BTC",
                url=url,
            ))
        return events

    def _fetch_fed_calendar(self):
        html = self._get_url(self.FED_CALENDAR_URL)
        return self._extract_dated_page_events(
            html,
            source="Federal Reserve official calendar",
            url=self.FED_CALENDAR_URL,
            why="Scheduled Federal Reserve event can move rate expectations, yields, VIX, SPY, QQQ, DXY, gold, and BTC.",
        )

    def _fetch_fomc(self):
        html = self._get_url(self.FOMC_URL)
        return self._extract_dated_page_events(
            html,
            source="Federal Reserve FOMC calendar",
            url=self.FOMC_URL,
            why="FOMC dates/minutes/decisions are high-impact events for rates, yields, stocks, gold, and crypto.",
        )

    def _fetch_white_house_feed(self):
        text = self._get_url(self.WHITE_HOUSE_FEED)
        root = ET.fromstring(text)
        events = []
        for item in root.findall("./channel/item")[:25]:
            title = self._xml_text(item, "title")
            link = self._xml_text(item, "link") or self.WHITE_HOUSE_FEED
            pub_date = self._xml_text(item, "pubDate")
            if not title or not pub_date:
                continue
            dt = parsedate_to_datetime(pub_date).astimezone(timezone.utc)
            # White House RSS is mostly posts, not future schedule. Store only recent market-relevant schedule/remarks items.
            if dt < datetime.now(timezone.utc) - timedelta(hours=18):
                continue
            events.append(self._make_event(
                source="White House official feed",
                title=title,
                event_time_utc=dt,
                why="White House policy remarks can affect sectors, defense, energy, rates, trade, and geopolitical risk.",
                watch="SPY, QQQ, VIX, DXY, Oil, Defense, Energy, BTC",
                url=link,
            ))
        return events

    def _extract_dated_page_events(self, html, source, url, why):
        text = self._strip_html(html)
        events = []
        # Basic official-page parser: catches dates written like September 17, 2026 or Sep 17, 2026.
        pattern = r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+20\d{2})(.{0,220})"
        for date_text, nearby in re.findall(pattern, text, flags=re.I):
            title = self._clean_space(nearby)[:140]
            if not title:
                title = source
            event_time = self._parse_page_date(date_text)
            if event_time:
                events.append(self._make_event(
                    source=source,
                    title=title,
                    event_time_utc=event_time,
                    why=why,
                    watch="SPY, QQQ, VIX, DXY, 10Y, Gold, BTC",
                    url=url,
                ))
        return events

    def _due_alerts(self, events):
        now_utc = datetime.now(timezone.utc)
        due = []
        for event in events:
            event_time = self._parse_iso(event.get("event_time_utc"))
            if not event_time:
                continue
            posted = set(event.get("posted_reminders", []))
            minutes_until = (event_time - now_utc).total_seconds() / 60
            for label, target_minutes, tolerance in self.REMINDER_WINDOWS:
                if label in posted:
                    continue
                if target_minutes - tolerance <= minutes_until <= target_minutes + tolerance:
                    due.append((event, label))
                    break
        return due

    def _mark_alerts_posted(self, due_alerts):
        data = self._read_events()
        for event, reminder_type in due_alerts:
            record = data.get("events", {}).get(event.get("id"))
            if not record:
                continue
            reminders = record.setdefault("posted_reminders", [])
            if reminder_type not in reminders:
                reminders.append(reminder_type)
        self._write_events(data)

    def _events_embed(self, mode):
        events = self._future_events(self._read_events().get("events", {}).values())
        now_pt = datetime.now(ZoneInfo("America/Los_Angeles"))
        if mode == "today":
            title = "🗓️ Today’s Official Market Events"
            events = [event for event in events if self._event_pt_time(event).date() == now_pt.date()]
        elif mode == "week":
            title = "🗓️ This Week’s Official Market Events"
            week_end = now_pt + timedelta(days=7)
            events = [event for event in events if now_pt <= self._event_pt_time(event) <= week_end]
        else:
            title = "🗓️ Upcoming Official Market Events"

        embed = discord.Embed(title=title, description="Pulled from official sources where available.", color=discord.Color.blue())
        if not events:
            embed.add_field(name="No events stored", value="Run `!calendarfetch` to pull official sources now.", inline=False)
        else:
            lines = []
            for event in events[:15]:
                pt = self._event_pt_time(event)
                lines.append(f"`{event.get('id')}` — {self._risk_icon(event)} {pt.strftime('%a %b %d %I:%M %p PT')} — **{event.get('title', 'Event')[:90]}**")
            embed.add_field(name="Events", value="\n".join(lines)[:1024], inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _fetch_result_embed(self, result):
        events = result.get("events", [])
        errors = result.get("errors", [])
        embed = discord.Embed(
            title="✅ Official Calendar Pull Complete",
            description="No event = no auto post. Reminders only post when saved official events are coming up.",
            color=discord.Color.green(),
        )
        embed.add_field(name="Upcoming Events Found", value=str(len(events)), inline=True)
        embed.add_field(name="Reminder Channel", value=f"#{self.reminder_channel_name}", inline=True)
        if events:
            lines = []
            for event in events[:8]:
                lines.append(f"• {self._event_pt_time(event).strftime('%a %b %d %I:%M %p PT')} — {event.get('title', 'Event')[:90]}")
            embed.add_field(name="Next Events", value="\n".join(lines)[:1024], inline=False)
        if errors:
            embed.add_field(name="Source Warnings", value="\n".join(errors[:4])[:1024], inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _event_alert_embed(self, event, reminder_type):
        labels = {"24h": "24 Hours Away", "1h": "1 Hour Away", "30m": "30 Minutes Away", "5m": "5 Minutes Away", "start": "Starting Now"}
        pt = self._event_pt_time(event)
        et = self._event_et_time(event)
        risk_icon = self._risk_icon(event)
        color = discord.Color.red() if risk_icon == "🔴" else discord.Color.gold()
        embed = discord.Embed(
            title=f"⏰ Calendar Event Reminder — {labels.get(reminder_type, 'Upcoming')}",
            description=f"{risk_icon} **{event.get('title', 'Market event')}**",
            color=color,
        )
        embed.add_field(name="Time", value=f"PT: `{pt.strftime('%a %b %d, %Y %I:%M %p')}`\nET: `{et.strftime('%a %b %d, %Y %I:%M %p')}`", inline=False)
        embed.add_field(name="Why It Matters", value=event.get("why", "Scheduled event may move markets."), inline=False)
        embed.add_field(name="Watch", value=event.get("watch", "SPY, QQQ, VIX, DXY, 10Y"), inline=False)
        embed.add_field(name="Source", value=f"{event.get('source', 'Official source')}\n{event.get('url', '')}", inline=False)
        embed.set_footer(text=f"Official event-only reminder • {VERSION}")
        return embed

    def _help_embed(self):
        embed = discord.Embed(
            title="🗓️ MarketOps Official Event Calendar",
            description="Pulls official sources and only posts when real events are coming up. No daily empty reminders.",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Channels", value=f"Event list: `#{self.calendar_channel_name}`\nReminders: `#{self.reminder_channel_name}`", inline=False)
        embed.add_field(name="Manual Commands", value="`!calendarfetch` • `!events` • `!calendartoday` • `!calendarweek` • `!calendarstatus`", inline=False)
        embed.add_field(name="Auto Reminders", value="24h before • 1h before • 30m before • 5m before • starting now", inline=False)
        embed.add_field(name="Sources", value="BLS official calendar, Federal Reserve calendar, FOMC calendar, White House official feed.", inline=False)
        embed.set_footer(text=VERSION)
        return embed

    def _make_event(self, source, title, event_time_utc, why, watch, url):
        event = {
            "source": source,
            "title": self._clean_space(title),
            "event_time_utc": event_time_utc.astimezone(timezone.utc).isoformat(),
            "why": why,
            "watch": watch,
            "url": url,
            "posted_reminders": [],
        }
        event["id"] = self._event_key(event)
        return event

    def _event_key(self, event):
        text = f"{event.get('source')}|{event.get('title')}|{event.get('event_time_utc')}"
        clean = re.sub(r"[^A-Z0-9]+", "", text.upper())
        return f"CAL-{clean[:18]}"

    def _is_market_relevant(self, event):
        text = f"{event.get('title', '')} {event.get('source', '')} {event.get('why', '')}".lower()
        return any(term in text for term in self.IMPORTANT_TERMS)

    def _future_events(self, events):
        now_utc = datetime.now(timezone.utc)
        rows = []
        for event in events:
            event_time = self._parse_iso(event.get("event_time_utc"))
            if event_time and event_time >= now_utc - timedelta(hours=2):
                rows.append(event)
        rows.sort(key=lambda item: item.get("event_time_utc") or "")
        return rows

    def _risk_icon(self, event):
        text = f"{event.get('title', '')} {event.get('why', '')}".lower()
        if any(term in text for term in ("cpi", "fomc", "employment situation", "jobs", "unemployment", "powell", "rate decision")):
            return "🔴"
        if any(term in text for term in ("fed", "ppi", "pce", "treasury", "white house", "president", "oil", "sanction")):
            return "🟡"
        return "🟢"

    def _event_pt_time(self, event):
        return self._parse_iso(event.get("event_time_utc")).astimezone(ZoneInfo("America/Los_Angeles"))

    def _event_et_time(self, event):
        return self._parse_iso(event.get("event_time_utc")).astimezone(ZoneInfo("America/New_York"))

    def _parse_iso(self, text):
        try:
            return datetime.fromisoformat(text)
        except Exception:
            return None

    def _parse_ics_datetime(self, text):
        clean = text.strip()
        if clean.endswith("Z"):
            return datetime.strptime(clean, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        if "T" in clean:
            return datetime.strptime(clean[:15], "%Y%m%dT%H%M").replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
        return datetime.strptime(clean[:8], "%Y%m%d").replace(hour=8, minute=30, tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)

    def _parse_page_date(self, date_text):
        for fmt in ("%B %d, %Y", "%b %d, %Y", "%Sept %d, %Y"):
            try:
                return datetime.strptime(date_text.replace("Sept", "Sep"), fmt.replace("Sept", "Sep")).replace(hour=8, minute=30, tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
            except ValueError:
                pass
        return None

    def _ics_field(self, block, name):
        match = re.search(rf"^{name}(?:;[^:]*)?:(.*)$", block, flags=re.M)
        return self._clean_space(match.group(1).replace("\\,", ",")) if match else ""

    def _get_url(self, url):
        request = urllib.request.Request(url, headers={"User-Agent": "MarketOpsBot/1.0"})
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.read().decode("utf-8", errors="ignore")

    def _strip_html(self, html):
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        return unescape(self._clean_space(text))

    def _clean_space(self, text):
        return re.sub(r"\s+", " ", unescape(text or "")).strip()

    def _xml_text(self, item, name):
        child = item.find(name)
        return self._clean_space(child.text if child is not None else "")

    def _read_events(self):
        if not self.EVENTS_FILE.exists():
            return {"events": {}}
        try:
            with self.EVENTS_FILE.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except Exception:
            return {"events": {}}
        if not isinstance(data, dict):
            return {"events": {}}
        data.setdefault("events", {})
        return data

    def _write_events(self, data):
        self.EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with self.EVENTS_FILE.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)

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

    def _clean_channel_name(self, channel_name):
        cleaned = (channel_name or "").strip().lower()
        for separator in ("|", "┃", "│"):
            if separator in cleaned:
                cleaned = cleaned.split(separator)[-1].strip()
        while cleaned and not cleaned[0].isalnum():
            cleaned = cleaned[1:].strip()
        return cleaned.replace(" ", "-")


async def setup(bot):
    await bot.add_cog(MarketCalendar(bot))
