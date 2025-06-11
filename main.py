import os
import discord
from discord.ext import commands
import logging

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

# List your cogs/extensions
initial_extensions = [
    'cogs.cleanup_cog',
    'cogs.dm_response',
    'cogs.guild_management_cog',
    'cogs.leaderboard_cog',
    'cogs.menu_view',
    'cogs.register_modal',
    'cogs.sos_cog',
    'cogs.sos_view',
    'cogs.extract_cog',
]

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    print('------')

async def setup():
    for ext in initial_extensions:
        try:
            await bot.load_extension(ext)
        except Exception as e:
            print(f'Failed to load extension {ext}: {e}')

if __name__ == '__main__':
    import asyncio

    # Load your Discord bot token from the environment variable
    token = os.environ.get('DISCORD_TOKEN')
    if not token:
        raise ValueError("DISCORD_TOKEN environment variable is not set!")

    # Run bot with setup, then start
    async def runner():
        await setup()
        await bot.start(token)

    asyncio.run(runner())
