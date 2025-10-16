import discord
from discord.ext import commands
import logging
from config import welcome_channel_id, class_b_role_id, guild_id
from utils import log_to_monitor_channel
from datetime import datetime

class ArrivalCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Welcomes a new member, assigns a role, and registers them."""
        try:
            # Restrict welcomes to the configured guild only
            if not guild_id or member.guild.id != guild_id:
                return

            # IMPORTANT: fetch the channel from the SAME guild
            welcome_channel = member.guild.get_channel(welcome_channel_id)
            if not welcome_channel:
                logging.error(
                    f"[ArrivalCog] Welcome channel {welcome_channel_id} not found in guild {member.guild.id}."
                )
                return

            await welcome_channel.send(
                (
                    f"Welcome {member.mention} to the front lines!\n"
                )
            )

            # Assign the Class B Citizen role
            role = member.guild.get_role(class_b_role_id)
            if role:
                await member.add_roles(role, reason="Auto-welcome role assignment")
                logging.info(f"[ArrivalCog] Assigned role '{role.name}' to {member.display_name}.")
            else:
                logging.error(
                    f"[ArrivalCog] Role {class_b_role_id} not found in guild {member.guild.id}."
                )
                return  # Stop if role not found

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

        except Exception as e:
            logging.error(f"[ArrivalCog] Error welcoming/ registering {member.display_name}: {e}")
            await log_to_monitor_channel(
                self.bot,
                f"Error welcoming or registering new member {member.display_name}: {e}",
                logging.ERROR
            )

async def setup(bot):
    await bot.add_cog(ArrivalCog(bot))
