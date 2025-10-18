import discord
from discord.ext import commands
import logging
from config import guild_id
from utils import log_to_monitor_channel
from datetime import datetime

class ArrivalCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Register/upsert the member on join. No DMs or auto-roles here."""
        try:
            # Restrict welcomes to the configured guild only
            if not guild_id or member.guild.id != guild_id:
                return

            # Register the user in the Alliance collection
            alliance_collection = self.bot.mongo_db['Alliance']

            filter_doc = {
                "discord_id": int(member.id),
                "discord_server_id": int(member.guild.id)
            }
            update_doc = {
                "$set": {
                    "player_name": member.name.strip(),
                    "server_name": member.guild.name.strip(),
                    "server_nickname": member.display_name.strip(),
                },
                "$setOnInsert": {"registered_at": datetime.utcnow()}
            }

            result = await alliance_collection.update_one(filter_doc, update_doc, upsert=True)
            if result.upserted_id is not None:
                logging.info(
                    f"[ArrivalCog] Registered new member {member.display_name} in Alliance collection via upsert."
                )
            else:
                logging.info(
                    f"[ArrivalCog] Updated existing Alliance registration for {member.display_name}."
                )

            # Region assignment handled during registration interactions, not here.

        except Exception as e:
            logging.error(f"[ArrivalCog] Error registering {member.display_name}: {e}")
            await log_to_monitor_channel(
                self.bot,
                f"Error registering new member {member.display_name}: {e}",
                logging.ERROR
            )

async def setup(bot):
    await bot.add_cog(ArrivalCog(bot))
