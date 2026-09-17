import asyncio
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from market.policy_brief_engine import PolicyBriefEngine


VERSION = "MarketOps Policy Brief v0.2.0"
PT_ZONE = ZoneInfo("America/Los_Angeles")


class PolicyBrief(commands.Cog):
    """Automatic policy-to-market lesson channel.

    Works with OpenAI when OPENAI_API_KEY is configured, but also has a local
    MarketOps fallback so policy posts do not stop when the API key is absent.
    """

    def __init__(self, bot):
        self.bot = bot
        self.engine = PolicyBriefEngine()
        self.channel_name = os.getenv("POLICY_BRIEF_CHANNEL", "openai-news-for-me").strip()
        self.auto_post = self._env_bool("POLICY_BRIEF_AUTO_POST", True)
        self.create_channel = self._env_bool("POLICY_BRIEF_CREATE_CHANNEL", True)
        self.weekdays_only = self._env_bool("POLICY_BRIEF_WEEKDAYS_ONLY", True)
        self.post_no_update = self._env_bool("POLICY_BRIEF_POST_NO_UPDATE", True)
        self.post_time = os.getenv("POLICY_BRIEF_TIME_PT", "05:30").strip()
        # Wide default catch-up window: if the bot starts later in the morning,
        # it can still send that day's policy lesson instead of silently missing it.
        self.catchup_minutes = int(os.getenv("POLICY_BRIEF_CATCHUP_MINUTES", "360"))
        self.state_file = Path("data/policy_brief_state.json")
        self.state = self._load_state()
        self.last_error = "None"

        if self.auto_post and not self.policy_schedule.is_running():
            self.policy_schedule.start()

    def cog_unload(self):
        if self.policy_schedule.is_running():
            self.policy_schedule.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.create_channel:
            return
        for guild in self.bot.guilds:
            await self._ensure_channel(guild)

    @app_commands.command(name="policy", description="Create today's sourced policy-to-market lesson.")
    async def policy_slash(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        try:
            brief = await asyncio.to_thread(self.engine.build_brief)
            await interaction.followup.send(embed=self._embed(brief))
        except Exception as error:
            self.last_error = repr(error)
            print(f"❌ /policy error: {error!r}")
            await interaction.followup.send(self._friendly_error(error), ephemeral=True)

    @commands.command(name="policy", aliases=["policybrief", "openai"])
    async def policy_prefix(self, ctx, action="now"):
        action = (action or "now").lower().strip()
        if action in {"status", "schedule", "time"}:
            await ctx.send(embed=self._status_embed())
            return

        try:
            brief = await asyncio.to_thread(self.engine.build_brief)
            if action in {"post", "send", "test"} and ctx.guild is not None:
                channel = await self._ensure_channel(ctx.guild)
                if channel is None:
                    await ctx.send(f"⚠️ Create `#{self.channel_name}` or give MarketOps Manage Channels permission.")
                    return
                await channel.send(embed=self._embed(brief), allowed_mentions=discord.AllowedMentions.none())
                self.state["last_result"] = f'Manual post {brief.get("updated", "Unknown")}'
                self.state["last_manual_post"] = datetime.now(PT_ZONE).isoformat()
                self._save_state()
                self.last_error = "None"
                await ctx.send(f"✅ Sent a policy brief to #{channel.name}.")
                return
            await ctx.send(embed=self._embed(brief), allowed_mentions=discord.AllowedMentions.none())
        except Exception as error:
            self.last_error = repr(error)
            print(f"❌ !policy error: {error!r}")
            await ctx.send(self._friendly_error(error))

    @tasks.loop(seconds=30)
    async def policy_schedule(self):
        await self.bot.wait_until_ready()
        now = datetime.now(PT_ZONE)

        if not self.auto_post:
            return
        if self.weekdays_only and now.weekday() >= 5:
            return
        if not self._is_due(now):
            return

        post_key = now.strftime("%Y-%m-%d")
        if self.state.get("last_post_date") == post_key:
            return

        self.state["last_post_date"] = post_key
        self._save_state()

        try:
            brief = await asyncio.to_thread(self.engine.build_brief)

            if brief.get("no_update") and not self.post_no_update:
                self.state["last_result"] = "No meaningful update"
                self._save_state()
                return

            sent_count = 0
            for guild in self.bot.guilds:
                channel = await self._ensure_channel(guild)
                if channel is not None:
                    await channel.send(embed=self._embed(brief), allowed_mentions=discord.AllowedMentions.none())
                    sent_count += 1

            if sent_count == 0:
                raise RuntimeError(
                    f"No #{self.channel_name} channel was available. "
                    "Create it or give MarketOps Manage Channels permission."
                )

            result_label = "No major update — daily check posted" if brief.get("no_update") else f'Posted {brief.get("updated", "Unknown")}'
            self.state["last_result"] = result_label
            self.state["last_auto_post"] = datetime.now(PT_ZONE).isoformat()
            self.last_error = "None"
            self._save_state()
            print(f"🧠 Posted policy brief to #{self.channel_name}.")
        except Exception as error:
            # Clear reservation so it can retry while still inside catch-up window.
            self.state.pop("last_post_date", None)
            self.last_error = repr(error)
            self._save_state()
            print(f"❌ Scheduled policy brief error: {error!r}")

    def _embed(self, brief):
        if brief.get("no_update"):
            description = brief.get("text") or "No new high-confidence policy development was found today."
            color = discord.Color.gold()
        else:
            description = brief.get("text", "No brief returned.")
            color = discord.Color.blurple()

        if len(description) > 4000:
            description = description[:3970].rsplit("\n", 1)[0] + "\n\n…Brief shortened for Discord."

        embed = discord.Embed(
            title="🧠 Policy → Market Lesson",
            description=description,
            color=color,
        )
        embed.add_field(name="Mode", value=brief.get("mode", self.engine.mode), inline=True)
        source_errors = brief.get("source_errors", [])
        if source_errors:
            embed.add_field(
                name="Source note",
                value="\n".join(f"• {self._short_error(item)}" for item in source_errors[:2])[:900],
                inline=False,
            )
        embed.set_footer(
            text=f'Updated {brief.get("updated", "Unknown")} • Public information only • {VERSION}'
        )
        return embed

    def _status_embed(self):
        status = "ON" if self.auto_post else "OFF"
        openai_status = "Ready" if self.engine.openai_enabled else "Not added — local fallback active"
        embed = discord.Embed(
            title="🧠 Policy → Market Status",
            description="Automatic policy-to-market lesson. It can run even without an OpenAI API key.",
            color=discord.Color.green() if self.auto_post else discord.Color.orange(),
        )
        embed.add_field(name="Auto-post", value=status, inline=True)
        embed.add_field(name="Channel", value=f"#{self.channel_name}", inline=True)
        embed.add_field(name="Time", value=f"{self.post_time} PT", inline=True)
        embed.add_field(name="Catch-up", value=f"{self.catchup_minutes} min", inline=True)
        embed.add_field(name="OpenAI", value=openai_status, inline=True)
        embed.add_field(name="Mode", value=self.engine.mode, inline=True)
        embed.add_field(name="Post no-update check", value="YES" if self.post_no_update else "NO", inline=True)
        embed.add_field(name="Last result", value=self.state.get("last_result", "Not posted yet"), inline=False)
        embed.add_field(name="Last error", value=self._short_error(self.last_error), inline=False)
        embed.add_field(name="Test", value="Use `!policy post` in `#openai-news-for-me`.", inline=False)
        embed.set_footer(text=VERSION)
        return embed

    async def _ensure_channel(self, guild):
        existing = self._find_channel(guild)
        if existing is not None:
            return existing
        if not self.create_channel:
            return None

        category = None
        morning = self._find_named_channel(guild, "morning-brief")
        if morning is not None:
            category = morning.category
        try:
            return await guild.create_text_channel(
                self.channel_name,
                category=category,
                reason="MarketOps personal policy-to-market briefing",
            )
        except discord.Forbidden:
            print(f"⚠️ Cannot create #{self.channel_name}; MarketOps needs Manage Channels permission.")
        except Exception as error:
            print(f"⚠️ Could not create #{self.channel_name}: {error!r}")
        return None

    def _find_channel(self, guild):
        return self._find_named_channel(guild, self.channel_name)

    def _find_named_channel(self, guild, target_name):
        target = self._clean_name(target_name)
        for channel in guild.text_channels:
            current = self._clean_name(channel.name)
            if current == target or current.endswith(target):
                return channel
        return None

    def _is_due(self, now):
        try:
            hour, minute = (int(value) for value in self.post_time.split(":", 1))
            scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except Exception:
            return False
        return scheduled <= now <= scheduled + timedelta(minutes=self.catchup_minutes)

    def _friendly_error(self, error):
        return (
            "⚠️ The policy brief could not be created. MarketOps should fall back to public-source mode even without an OpenAI key. "
            "Use `!policy status` and paste the terminal line beginning with `❌ !policy error:` if it still fails."
        )

    def _short_error(self, error):
        text = str(error or "None")
        if text == "None":
            return "None"
        if "401" in text:
            return "A source needs authentication/token setup."
        if "403" in text:
            return "A source rejected the current API key or placeholder value."
        if "429" in text:
            return "A source rate-limited the request."
        if "timed out" in text.lower() or "timeout" in text.lower():
            return "A source timed out. MarketOps will retry later."
        return text[:240]

    def _clean_name(self, value):
        cleaned = (value or "").strip().lower()
        for separator in ("|", "┃", "│"):
            if separator in cleaned:
                cleaned = cleaned.split(separator)[-1].strip()
        while cleaned and not cleaned[0].isalnum():
            cleaned = cleaned[1:].strip()
        return cleaned.replace(" ", "-")

    def _load_state(self):
        try:
            if self.state_file.exists():
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
        except Exception:
            pass
        return {}

    def _save_state(self):
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        except Exception as error:
            print(f"⚠️ Could not save policy brief state: {error!r}")

    def _env_bool(self, name, default=False):
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}


async def setup(bot):
    await bot.add_cog(PolicyBrief(bot))