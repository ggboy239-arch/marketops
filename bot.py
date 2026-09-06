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
)


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


# --------------------
# Main
# --------------------

async def main():
    async with bot:
        await load()
        await bot.start(TOKEN)


asyncio.run(main())
