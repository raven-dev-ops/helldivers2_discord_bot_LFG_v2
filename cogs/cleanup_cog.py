# cleanup_cog.py
import discord
from discord.ext import commands, tasks
import logging
import asyncio

MENU_VIEW_TITLES = [
    "Welcome to the SOS Alliance Network!",
    "GPT SOS LFG NETWORK",
    "HELLDIVERS SOS LFG NETWORK!",
    "Welcome to the GPT LFG Network!"
]

class CleanupCog(commands.Cog):
    """
    Periodically and on-startup cleans up old SOS messages, empty voice channels,
    and old menu view messages in each server's designated GPT channel.
    """
    def __init__(self, bot):
        self.bot = bot
        self.sos_cog = None
        self.guild_management_cog = None

    async def _prune_stale_guild(self, server_listing, guild_id, context: str = ""):
        """Remove entries for guilds the bot has left."""
        try:
            await server_listing.delete_one({"discord_server_id": guild_id})
            logging.info(
                f"Pruned stale Server_Listing entry for missing guild ID {guild_id}{context}."
            )
        except Exception as e:
            logging.error(
                f"Failed to prune stale Server_Listing entry for guild ID {guild_id}{context}: {e}"
            )

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info("CleanupCog is ready.")

        # Only run once (for hot reloads / dev convenience)
        if getattr(self.bot, "cleanup_setup_done", False):
            return
        self.bot.cleanup_setup_done = True

        # Wait for SOSCog and GuildManagementCog to be loaded (max 5 seconds)
        retries = 5
        for attempt in range(retries):
            self.sos_cog = self.bot.get_cog("SOSCog")
            self.guild_management_cog = self.bot.get_cog("GuildManagementCog")
            if self.sos_cog and self.guild_management_cog:
                break
            logging.info(f"CleanupCog waiting for SOSCog and GuildManagementCog... ({attempt+1}/{retries})")
            await asyncio.sleep(1)

        # Final check
        if not self.sos_cog or not self.guild_management_cog:
            logging.warning("SOSCog or GuildManagementCog not loaded after waiting. CleanupCog cannot function properly.")
            return

        # Start the periodic cleanup if not already running
        if not self.periodic_cleanup.is_running():
            self.periodic_cleanup.start()

        # Perform one-time cleanup on startup
        await self.perform_startup_cleanup()

    @tasks.loop(hours=1)
    async def periodic_cleanup(self):
        """
        Regularly cleans up old SOS messages and old menu views in GPT channels.
        """
        logging.info("Starting periodic cleanup of SOS messages and menu views.")
        server_listing = self.bot.mongo_db['Server_Listing']

        all_servers = await server_listing.find({}).to_list(None)
        for server_data in all_servers:
            guild_id = server_data.get("discord_server_id")
            guild = self.bot.get_guild(guild_id)
            if not guild:
                await self._prune_stale_guild(server_listing, guild_id)
                continue

            gpt_channel_id = server_data.get("gpt_channel_id")
            gpt_channel = guild.get_channel(gpt_channel_id)
            if not gpt_channel or not isinstance(gpt_channel, discord.TextChannel):
                logging.warning(f"GPT channel for guild '{guild.name}' not found or not a TextChannel.")
                continue

            await self.delete_old_sos_and_menu_messages(guild, gpt_channel)

    @periodic_cleanup.before_loop
    async def before_periodic_cleanup(self):
        await self.bot.wait_until_ready()

    async def perform_startup_cleanup(self):
        """
        Cleans up leftover 'SOS QRF#' voice channels and old messages 
        (SOS or menu views) in the GPT channel on startup.
        """
        logging.info("Performing startup cleanup.")
        server_listing = self.bot.mongo_db['Server_Listing']
        all_servers = await server_listing.find({}).to_list(None)

        for server_data in all_servers:
            guild_id = server_data.get("discord_server_id")
            gpt_channel_id = server_data.get("gpt_channel_id")

            guild = self.bot.get_guild(guild_id)
            if not guild:
                await self._prune_stale_guild(server_listing, guild_id, " during startup cleanup")
                continue

            # 1) Remove leftover 'SOS QRF#' channels that are empty
            for voice_channel in guild.voice_channels:
                if voice_channel.name.startswith("SOS QRF#"):
                    if len(voice_channel.members) == 0:
                        try:
                            logging.info(f"Deleting leftover voice channel: {voice_channel.name} in guild: {guild.name}")
                            await voice_channel.delete()
                        except Exception as e:
                            logging.error(f"Failed to delete voice channel {voice_channel.name}: {e}")

            # 2) Remove old SOS/menu messages from the GPT channel
            gpt_channel = guild.get_channel(gpt_channel_id)
            if not gpt_channel or not isinstance(gpt_channel, discord.TextChannel):
                logging.warning(
                    f"GPT channel with ID {gpt_channel_id} not found or not a TextChannel in guild '{guild.name}'. Skipping cleanup."
                )
                continue

            await self.delete_old_sos_and_menu_messages(guild, gpt_channel)

    async def delete_old_sos_and_menu_messages(self, guild: discord.Guild, gpt_channel: discord.TextChannel):
        """
        Deletes old SOS 'activated' messages and old 'menu view' 
        messages from the specified GPT channel.
        """
        try:
            async for message in gpt_channel.history(limit=100):
                if message.author == self.bot.user and message.embeds:
                    embed = message.embeds[0]
                    if embed.title == "SOS ACTIVATED":
                        logging.info(f"Deleting old SOS message in '{guild.name}' (Message ID: {message.id}).")
                        await message.delete()
                    elif embed.title in MENU_VIEW_TITLES:
                        logging.info(f"Deleting old menu view message in '{guild.name}' (Message ID: {message.id}).")
                        await message.delete()
        except Exception as e:
            logging.error(f"Error during cleanup in guild '{guild.name}': {e}")

async def setup(bot):
    await bot.add_cog(CleanupCog(bot))
