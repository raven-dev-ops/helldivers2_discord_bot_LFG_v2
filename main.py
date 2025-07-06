import os
import logging
import discord
from discord.ext import commands
from motor.motor_asyncio import AsyncIOMotorClient

logging.basicConfig(level=logging.INFO)

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    print('------')
    print('Cogs loaded:', list(bot.cogs.keys()))  # See actual registered cog class names

async def load_cogs():
    """
    Load the bot's cogs in the correct order.
    """
    cogs = [
        'cogs.departure_cog',
        'cogs.members_cog',
        'cogs.promotion_cog',
        'cogs.arrival_cog',
        'cogs.guild_management_cog',
        'cogs.leaderboard_cog',
        'cogs.sos_cog',
        'cogs.cleanup_cog',
        'cogs.dm_response',
        'cogs.extract_cog',
    ]
    for cog in cogs:
        try:
            await bot.load_extension(cog)
            logging.info(f"Successfully loaded cog: {cog}")
        except Exception as e:
            logging.error(f"Failed to load cog {cog}: {e}")
            logging.error(traceback.format_exc())

if __name__ == '__main__':
    import asyncio

    token = os.environ.get('DISCORD_TOKEN')
    mongo_uri = os.environ.get('MONGODB_URI')
    db_name = 'GPTHellbot'

    if not token:
        raise ValueError("DISCORD_TOKEN environment variable is not set!")
    if not mongo_uri:
        raise ValueError("MONGODB_URI environment variable is not set!")

    mongo_client = AsyncIOMotorClient(mongo_uri)
    bot.mongo_db = mongo_client[db_name]

    async def runner():
        await load_cogs()
        await bot.start(token)

    asyncio.run(runner())
