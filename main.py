import os
import logging
import discord
import traceback
from discord.ext import commands
from motor.motor_asyncio import AsyncIOMotorClient
from database import create_indexes

logging.basicConfig(level=logging.INFO)

# Add filter to reduce noisy discord reconnect logs
class DiscordNoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = str(record.getMessage())
        # Suppress benign reconnect/close messages
        if "Attempting a reconnect" in msg:
            return False
        if "WebSocket closed with 1000" in msg:
            return False
        return True

# Apply filter and set discord log level
discord_logger = logging.getLogger("discord")
discord_logger.setLevel(logging.WARNING)
for handler in logging.getLogger().handlers:
    handler.addFilter(DiscordNoiseFilter())

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
bot = commands.Bot(command_prefix='!', intents=intents)


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    print('------')
    print('Cogs loaded:', list(bot.cogs.keys()))  # See actual registered cog class names
    if not bot.intents.members:
        logging.warning("GUILD_MEMBERS intent is disabled. Member join/leave events will not fire. Enable it in the Discord Developer Portal.")

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
        'cogs.sos_view',
        'cogs.sos_cog',
        'cogs.cleanup_cog',
        'cogs.dm_response',
        'cogs.register_modal',
        'cogs.menu_view',
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
        await create_indexes()
        await load_cogs()
        await bot.start(token)

    if __name__ == "__main__":
        asyncio.run(runner())
