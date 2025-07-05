# cogs/members_cog.py

import discord
from discord.ext import commands
import logging
from database import get_mongo_client
from utils import log_to_monitor_channel

class MembersCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Updates the Alliance collection if a member changes their server nickname."""
        try:
            if before.display_name != after.display_name:
                mongo_client = await get_mongo_client()
                db = mongo_client['GPTHellbot']
                alliance_collection = db['Alliance']

                # Update the 'server_nickname' in the Alliance collection
                new_server_nickname = after.display_name.strip()
                result = await alliance_collection.update_one(
                    {
                        "discord_id": str(after.id),
                        "discord_server_id": str(after.guild.id)
                    },
                    {
                        "$set": {
                            "server_nickname": new_server_nickname
                        }
                    }
                )
                if result.matched_count > 0:
                    logging.info(f"Updated server_nickname for Discord ID {after.id} to '{new_server_nickname}'.")
                else:
                    logging.warning(f"No Alliance entry found for Discord ID {after.id} during nickname update.")
        except Exception as e:
            logging.error(f"Error updating nickname for {after.display_name}: {e}")
            await log_to_monitor_channel(self.bot, f"Error updating nickname for {after.display_name}: {e}", logging.ERROR)

async def setup(bot):
    await bot.add_cog(MembersCog(bot))