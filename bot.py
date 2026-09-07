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

COMMAND_CHANNELS = {
    "status": ["bot-status"],
    "market": ["market-dashboard"],
    "brief": ["morning-brief"],
    "learn": ["market-school"],
    "playbook": ["market-school"],
    "watchlist": ["watchlist"],
    "alerts": ["watchlist"],
    "watch": ["watchlist"],
    "unwatch": ["watchlist"],
    "watchreset": ["watchlist"],
    "alertstatus": ["watchlist"],
    "alertson": ["watchlist"],
    "alertsoff": ["watchlist"],
    "newson": ["watchlist"],
    "newsoff": ["watchlist"],
    "threshold": ["watchlist"],
    "mysettings": ["watchlist"],
    "mytimezone": ["watchlist"],
    "mybrief": ["watchlist"],
    "mythreshold": ["watchlist"],
    "mywatch": ["watchlist"],
    "myunwatch": ["watchlist"],
    "mywatchlist": ["watchlist"],
    "myalerts": ["watchlist"],
    "myreset": ["watchlist"],
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

    if command_name in HELP_COMMANDS:
        return True

    allowed_channels = COMMAND_CHANNELS.get(command_name)
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


# --------------------
# Main
# --------------------

async def main():
    async with bot:
        await load()
        await bot.start(TOKEN)


asyncio.run(main())
