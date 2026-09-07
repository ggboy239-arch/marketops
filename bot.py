import asyncio
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    case_insensitive=True,
)

# Replace Discord.py's default help command with our MarketOps command guide.
bot.remove_command("help")


# --------------------
# Command Channel Rules
# --------------------

HELP_COMMANDS = {"commands", "help", "cmds", "ping"}

ACCESS_CHANNEL_COMMANDS = [
    "redeem", "renew", "access", "profile", "settings", "mysettings",
]

PERSONAL_WATCHLIST_COMMANDS = [
    "timezone", "tz", "mytimezone", "brief-times", "brieftimes", "mybrief",
    "alert-percent", "alertpercent", "mythreshold", "add", "mywatch",
    "remove", "myunwatch", "reset-profile", "myreset", "list", "mywatchlist",
    "scan", "myalerts",
]

SHARED_WATCHLIST_COMMANDS = [
    "watchlist", "alerts", "watch", "unwatch", "watchreset", "alertstatus",
    "alertson", "alertsoff", "newson", "newsoff", "threshold",
]

ADMIN_KEY_COMMANDS = [
    "genkey", "adminkey", "genkeys", "revokekey", "adminusers",
    "renewals", "approverenew", "denyrenew",
]

COMMAND_CHANNELS = {
    "status": ["bot-status"],
    "market": ["market-dashboard"],
    "brief": ["morning-brief"],
    "learn": ["market-school"],
    "playbook": ["market-school"],
    **{command: ["watchlist"] for command in SHARED_WATCHLIST_COMMANDS},
    **{command: ["watchlist"] for command in PERSONAL_WATCHLIST_COMMANDS},
    **{command: ["redeem-access", "watchlist"] for command in ACCESS_CHANNEL_COMMANDS},
    **{command: ["admin-keys"] for command in ADMIN_KEY_COMMANDS},
    "news": [
        "breaking-news",
        "general-news",
        "ai-news",
        "fed",
        "geopolitics",
        "crypto",
        "reddit-hot",
    ],
}


@bot.check
async def command_channel_check(ctx):
    """Keep commands in their correct Discord channels."""
    if ctx.guild is None or ctx.command is None:
        return True

    command_name = ctx.command.name.lower()
    invoked_name = (ctx.invoked_with or command_name).lower()

    if command_name in HELP_COMMANDS or invoked_name in HELP_COMMANDS:
        return True

    allowed_channels = COMMAND_CHANNELS.get(invoked_name) or COMMAND_CHANNELS.get(command_name)
    if not allowed_channels:
        return True

    current_channel = getattr(ctx.channel, "name", "")
    if current_channel in allowed_channels:
        return True

    allowed_text = ", ".join(f"#{name}" for name in allowed_channels)
    await ctx.send(
        f"⚠️ `{ctx.prefix}{ctx.invoked_with}` belongs in {allowed_text}. "
        "Type `!commands` for the quick guide."
    )
    return False


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        return

    if isinstance(error, commands.CommandNotFound):
        await ctx.send("⚠️ I do not know that command yet. Type `!commands` for the command guide.")
        return

    raise error


# --------------------
# When Bot Starts
# --------------------

@bot.event
async def on_ready():
    print("=" * 50)
    print(f"🚀 Logged in as {bot.user}")
    print("=" * 50)

    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} commands.")
    except Exception as error:
        print(f"❌ Slash command sync error: {error}")


# --------------------
# Load Cogs
# --------------------

async def load():
    await bot.load_extension("cogs.ping")
    await bot.load_extension("cogs.market")
    await bot.load_extension("cogs.coach")
    await bot.load_extension("cogs.explain")
    await bot.load_extension("cogs.news")
    await bot.load_extension("cogs.brief")
    await bot.load_extension("cogs.watchlist")
    await bot.load_extension("cogs.learn")
    await bot.load_extension("cogs.help")
    await bot.load_extension("cogs.status")
    await bot.load_extension("cogs.users")
    await bot.load_extension("cogs.access")


# --------------------
# Main
# --------------------

async def main():
    async with bot:
        await load()
        await bot.start(TOKEN)


asyncio.run(main())
