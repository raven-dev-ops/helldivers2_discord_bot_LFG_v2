# cogs/arrival_cog.py

import discord
from discord.ext import commands
import logging
from database import get_mongo_client
from config import welcome_channel_id, role_to_assign_id, sos_network_id
from utils import log_to_monitor_channel
from datetime import datetime

class ArrivalCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Welcomes a new member, assigns a role, and registers them."""
        try:
            # Send welcome message
            welcome_channel = self.bot.get_channel(welcome_channel_id)
            if not welcome_channel:
                logging.error(f"Welcome channel with ID {welcome_channel_id} not found.")
                return

            await welcome_channel.send(
                f"Welcome {member.mention} to the server!\n"
                f"Thank you for your service and interest in becoming a part of our community!\n"
                f"If you have any questions, please ask.\n"
                f"If you need moderation, please make a ticket.\n"
                f"If you are looking for LFG, use the GPT Network.\n"
                f"IRL comes first, everything is viable, and do your best!"
                
            )

            # Assign the role
            role = member.guild.get_role(role_to_assign_id)
            if role:
                await member.add_roles(role)
                logging.info(f"Assigned role '{role.name}' to {member.display_name}.")
            else:
                logging.error(f"Role with ID {role_to_assign_id} not found.")
                return  # Exit if role not found

            # Register the user in the Alliance collection
            mongo_client = await get_mongo_client()
            db = mongo_client['GPTHellbot']
            alliance_collection = db['Alliance']

            # Create a registration document for the new user
            new_registration = {
                "discord_id": str(member.id),
                "discord_server_id": str(member.guild.id),
                "player_name": member.name.strip(),  # Discord username
                "server_name": member.guild.name.strip(),
                "server_nickname": member.display_name.strip(),
                "registered_at": datetime.utcnow().isoformat()
            }

            # Insert the new user into the Alliance collection
            await alliance_collection.insert_one(new_registration)
            logging.info(f"Registered new member {member.display_name} in the Alliance collection.")

        except Exception as e:
            logging.error(f"Error welcoming or registering new member {member.display_name}: {e}")
            await log_to_monitor_channel(self.bot, f"Error welcoming or registering new member {member.display_name}: {e}", logging.ERROR)

async def setup(bot):
    await bot.add_cog(ArrivalCog(bot))
