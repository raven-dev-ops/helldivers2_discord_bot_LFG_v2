import discord
from discord.ext import commands
import logging
from database import get_mongo_client
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
                    f"Welcome {member.mention} to the server!\n"
                    f"Thank you for your service and interest in becoming a part of our community!\n"
                    f"If you have any questions, please ask.\n"
                    f"If you need moderation, please make a ticket.\n"
                    f"If you are looking for LFG, use the GPT Network.\n"
                    f"IRL comes first, everything is viable, and do your best!"
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
            mongo_client = await get_mongo_client()
            db = mongo_client['GPTHellbot']
            alliance_collection = db['Alliance']

            new_registration = {
                "discord_id": str(member.id),
                "discord_server_id": str(member.guild.id),
                "player_name": member.name.strip(),
                "server_name": member.guild.name.strip(),
                "server_nickname": member.display_name.strip(),
                "registered_at": datetime.utcnow().isoformat()
            }

            await alliance_collection.insert_one(new_registration)
            logging.info(
                f"[ArrivalCog] Registered new member {member.display_name} in Alliance collection."
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
