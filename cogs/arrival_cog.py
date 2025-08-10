# cogs/arrival_cog.py

import discord
from discord.ext import commands
import logging
from database import get_mongo_client
from config import welcome_channel_id, role_to_assign_id
from utils import log_to_monitor_channel
from datetime import datetime

class ArrivalCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Welcomes a new member, assigns a role, and registers them."""
        try:
            logging.info(f"on_member_join event received for {member} in guild '{member.guild.name}' ({member.guild.id})")
            # Resolve welcome channel with fallbacks
            welcome_channel = self.bot.get_channel(welcome_channel_id)
            # Use env-configured channel only if it belongs to this guild
            if welcome_channel and getattr(welcome_channel, 'guild', None) and welcome_channel.guild.id != member.guild.id:
                welcome_channel = None
            if not welcome_channel:
                # Try system channel
                welcome_channel = member.guild.system_channel
            if not welcome_channel:
                # Try to find a reasonable text channel by common names
                candidate_names = ["welcome", "introductions", "general"]
                for name in candidate_names:
                    ch = discord.utils.get(member.guild.text_channels, name=name)
                    if ch:
                        welcome_channel = ch
                        break
            if not welcome_channel:
                logging.error(f"Welcome channel not found in guild '{member.guild.name}'.")
                await log_to_monitor_channel(self.bot, f"Welcome channel not found in guild '{member.guild.name}'.", logging.WARNING)
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
                try:
                    await member.add_roles(role, reason="Auto-assign on join")
                    logging.info(f"Assigned role '{role.name}' to {member.display_name}.")
                except discord.Forbidden:
                    logging.warning(f"Insufficient permissions to assign role '{role.name}' in guild '{member.guild.name}'.")
                except Exception as e:
                    logging.error(f"Error assigning role '{role.name}' to {member.display_name}: {e}")
            else:
                logging.warning(f"Role with ID {role_to_assign_id} not found in guild '{member.guild.name}'.")

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
