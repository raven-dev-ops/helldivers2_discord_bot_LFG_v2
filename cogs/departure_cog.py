# cogs/departure_cog.py

import discord
from discord.ext import commands
import logging
import random
from config import kia_channel_id
from utils import log_to_monitor_channel

goodbye_messages = [
    "has left the server. Farewell!",
    "has departed. We'll miss you!",
    "is no longer with us. Safe travels!",
    "has moved on to new adventures.",
    "has left the fleet. Best wishes!",
    "has been honorably discharged. Thank you for your service!",
    "has set sail for new horizons.",
    "has bid us adieu. Until we meet again!",
    "has taken leave. We salute you!",
    "has exited the fleet. Good luck on your journey!",
]

class DepartureCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Sends a goodbye message when a member leaves."""
        try:
            logging.info(f"on_member_remove event received for {member} in guild '{member.guild.name}' ({member.guild.id})")
            channel = self.bot.get_channel(kia_channel_id)
            if channel and getattr(channel, 'guild', None) and channel.guild.id != member.guild.id:
                channel = None
            if not channel:
                # Fallback: try a channel named by common names
                candidate_names = ["kia", "farewell", "goodbye", "general"]
                for name in candidate_names:
                    ch = discord.utils.get(member.guild.text_channels, name=name)
                    if ch:
                        channel = ch
                        break
            if not channel:
                logging.error(f"KIA/Goodbye channel not found in guild '{member.guild.name}'.")
                await log_to_monitor_channel(self.bot, f"KIA/Goodbye channel not found in guild '{member.guild.name}'.", logging.WARNING)
                return

            message = f"{member.display_name} {random.choice(goodbye_messages)}"
            await channel.send(message)
            logging.info(f"Sent goodbye message for {member.display_name}.")
        except Exception as e:
            logging.error(f"Error sending goodbye message for {member.display_name}: {e}")
            await log_to_monitor_channel(self.bot, f"Error sending goodbye message for {member.display_name}: {e}", logging.ERROR)

async def setup(bot):
    await bot.add_cog(DepartureCog(bot))
