import os
import importlib
import inspect
import logging
import sys
from unittest.mock import MagicMock

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import pytest
import discord
from discord.ext import commands

logging.basicConfig(level=logging.INFO)

COG_DIR = "cogs"


def get_cog_modules():
    """Yield module names for each cog file."""
    for filename in os.listdir(COG_DIR):
        if filename.endswith("_cog.py") or filename == "dm_response.py":
            yield filename[:-3]


@pytest.mark.asyncio
async def test_cogs_load_and_have_async_commands():
    for module_name in get_cog_modules():
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix="!", intents=intents)
        bot.mongo_db = MagicMock()
        module = importlib.import_module(f"{COG_DIR}.{module_name}")
        await module.setup(bot)
        assert bot.cogs, f"{module_name} failed to load"
        cog = next(iter(bot.cogs.values()))
        # Verify commands
        for command in cog.get_commands():
            logging.info("Testing %s.%s", module_name, command.name)
            assert inspect.iscoroutinefunction(command.callback)
        # Verify listeners
        for attr_name in dir(cog):
            if attr_name.startswith("on_"):
                func = getattr(cog, attr_name)
                if inspect.iscoroutinefunction(func):
                    logging.info("Found listener %s.%s", module_name, attr_name)
        await bot.close()

