# sos_cog.py
import discord
from discord.ext import commands
import asyncio
import logging
from datetime import datetime
from cogs.sos_view import SOSView # Ensure this import path is correct
import time

class SOSCog(commands.Cog):
    """
    A cog to manage SOS creation and related functionality.
    Includes pinging the SOS LFG role when an SOS is posted.
    """
    def __init__(self, bot):
        self.bot = bot
        self.voice_channels = {}  # Track created voice channels
        self.sos_data_by_channel = {}  # Map voice channel IDs to SOS data
        self.cleanup_tasks = {}  # Map voice channel IDs to their cleanup tasks

    def get_sos_view(self):
        """Returns an instance of the SOSView."""
        # Always pass bot to SOSView constructor
        return SOSView(self.bot)

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info("SOSCog is ready.")
        # Note: The cleanup task should ideally be managed by a dedicated cleanup cog
        # or handled during startup in GuildManagementCog's setup for persistence across restarts.
        # Leaving it here for now as per provided code structure.
        # You might see warnings if cleanup_cog attempts similar actions.


    async def check_bot_permissions(self, guild: discord.Guild):
        """Verify the bot has the required permissions in a guild for basic SOS ops."""
        # This check might be redundant if GuildManagementCog already did a strict check
        # and setup failed, but can be useful for operations beyond initial setup.
        # Added mention_roles check here as it's used in process_sos broadcast.
        permissions = guild.me.guild_permissions
        required_perms = ["manage_channels", "send_messages", "embed_links", "mention_roles"]
        missing_perms = [
            perm for perm in required_perms if not getattr(permissions, perm, False)
        ]
        if missing_perms:
            logging.warning(f"Bot missing basic required permissions in guild '{guild.name}': {', '.join(missing_perms)}. Some SOS features may fail.")
            # Don't return False here, let process_sos handle per-channel/guild failures
            # during broadcast where specific channel perms matter.
            pass # Just log, don't block the whole process_sos attempt

    async def get_or_create_category(self, guild: discord.Guild, category_name: str = "GPT NETWORK"):
        """Retrieves or creates a dedicated category for GPT voice channels."""
        # This logic should ideally be handled by GuildManagementCog during setup
        # and the category ID stored/retrieved from the database.
        # Keeping it here for now as per the provided code structure, but it's
        # inconsistent with the GuildManagementCog's approach.
        category = discord.utils.get(guild.categories, name=category_name)
        if category is None:
            # Ensure bot has permission to create categories before attempting
            if not guild.me.guild_permissions.manage_channels:
                 logging.warning(f"Bot lacks 'Manage Channels' permission in guild '{guild.name}'. Cannot create category '{category_name}'.")
                 return None
            try:
                # Define basic overwrites for the category if creating
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(view_channel=True),
                    guild.me: discord.PermissionOverwrite(view_channel=True, manage_channels=True)
                }
                category = await guild.create_category(name=category_name, overwrites=overwrites)
                logging.info(f"Created category '{category_name}' in guild '{guild.name}'.")
            except Exception as e:
                logging.error(f"Failed to create category '{category_name}' in guild '{guild.name}': {e}")
                return None
        return category


    async def launch_sos(self, interaction: discord.Interaction):
        """Handles the 'Launch SOS' action with OPEN parameters (no defaults)."""
        # You might want an initial check here to ensure the bot has basic
        # permissions in the interaction's guild before proceeding.
        # Example:
        # if not interaction.guild or not interaction.guild.me.guild_permissions.send_messages:
        #    await interaction.response.send_message("I don't have permission to respond here or in this guild.", ephemeral=True)
        #    return

        try:
            sos_view_cog = self.bot.get_cog("SOSViewCog")
            if sos_view_cog:
                 # Get view from the cog instance if needed for state/persistence
                view = sos_view_cog.get_sos_view()
            else:
                 # Fallback if cog not found, instantiate directly with bot
                view = SOSView(self.bot)


            # No default parameters
            view.enemy_type = None
            view.difficulty = None
            view.mission = None
            view.voice = None
            view.notes = None

            # Defer interaction to prevent timeout
            # Use try-except because interaction.response.is_done() might not exist in older versions
            try:
                 if not interaction.response.is_done():
                      await interaction.response.defer(ephemeral=True)
                 else:
                      logging.debug("Interaction already responded to, skipping defer.")
            except AttributeError:
                 logging.warning("discord.py version does not support interaction.response.is_done(). Skipping defer check.")
                 # In older versions without is_done(), just defer directly if confident it hasn't been responded to
                 # Or handle this case based on your known older version capabilities.
                 # For robustness across versions, a simple try-except is safer.


            # Directly process the SOS with all fields open
            await self.process_sos(interaction, view)
        except Exception as e:
            logging.error(f"An unexpected error occurred in launch_sos for guild {interaction.guild.id}: {e}")
            # Use followup.send after deferring
            try:
                 # Use interaction.is_original_response() or similar if is_done() isn't reliable
                 # Given the AttributeError on is_done(), using just followup.send might be necessary
                 await interaction.followup.send(
                     "An unexpected error occurred while processing your request. Please try again later.",
                     ephemeral=True
                     )
            except (discord.InteractionResponded, discord.NotFound): # Catch InteractionResponded for older versions
                 logging.warning("Interaction already responded to or not found before sending followup error.")
            except Exception as fu_e:
                 logging.error(f"Failed to send followup error message: {fu_e}")


    async def process_sos(self, interaction: discord.Interaction, view: SOSView):
        """
        Process the creation of an SOS and broadcast it to all servers' GPT network channels.
        """
        sos_data = None
        invite_url = None # Initialize invite_url here

        try:
            # Ensure MongoDB client is available
            if not hasattr(self.bot, 'mongo_db') or self.bot.mongo_db is None:
                 logging.error("MongoDB client not available in bot. Cannot process SOS.")
                 # Use followup.send after deferring
                 await interaction.followup.send("Database connection not available. Cannot launch SOS.", ephemeral=True)
                 return


            sos_collection = self.bot.mongo_db['User_SOS']

            # Insert the new SOS into the database
            sos_document = {
                "discord_id": interaction.user.id,
                "user_nickname": interaction.user.display_name,
                "created_at": datetime.utcnow(),
                "enemy": view.enemy_type,
                "difficulty": view.difficulty,
                "mission": view.mission,
                "voice": view.voice,
                "notes": view.notes or ""
            }

            await sos_collection.insert_one(sos_document)
            logging.info(f"SOS document inserted for user {interaction.user.id} in guild {interaction.guild.id}")


            host_guild = interaction.guild

            # Basic check for the hosting guild (where the interaction came from)
            # More granular checks are done per broadcast guild below.
            if not host_guild.me.guild_permissions.send_messages or not host_guild.me.guild_permissions.embed_links:
                logging.warning(f"Bot is missing basic send/embed permissions in the host guild '{host_guild.name}'. SOS embed may not send correctly even in the host guild.")
                # Don't return here, still attempt broadcast to other guilds


            # Get or create GPT category (This should ideally be managed by GuildManagementCog)
            # Using get_or_create_category here maintains existing logic but is inconsistent
            # with GuildManagementCog's single source of truth approach via DB.
            # Consider refactoring this to use the category ID from the database if available.
            # category = await self.get_or_create_category(host_guild, "GPT NETWORK")
            # if not category:
            #    # If category couldn't be found/created in the host guild, voice channel creation might fail
            #    logging.warning(f"Could not get/create GPT NETWORK category in host guild '{host_guild.name}'. Voice channel creation might fail.")
            #    # Still attempt broadcast to other guilds


            # Generate unique name for the voice channel in the host guild
            # This logic is specific to the host guild where the SOS is initiated
            category = discord.utils.get(host_guild.categories, name="GPT NETWORK") # Try to get category
            # If category doesn't exist or bot can't manage channels, voice channel creation might fail below.
            # The error handling around voice channel creation will catch this.

            existing_channels = [
                c.name for c in host_guild.voice_channels if c.name.startswith("SOS QRF#")
            ]
            next_number = (
                max(
                    [
                        int(c.split("#")[-1])
                        for c in existing_channels
                        if c.split("#")[-1].isdigit()
                    ],
                    default=0
                ) + 1
            )
            voice_channel_name = f"SOS QRF#{next_number}"

            # Permissions for the voice channel
            overwrites = {
                host_guild.default_role: discord.PermissionOverwrite(
                    connect=True, speak=True, view_channel=True, use_voice_activation=True
                ),
                host_guild.me: discord.PermissionOverwrite( # Ensure bot can manage its own voice channel
                     manage_channels=True, connect=True, speak=True, view_channel=True
                 )
            }

            voice_channel = None # Initialize voice_channel
            try:
                 # Create the voice channel, attempting to place it under the category
                 # If category is None or bot lacks permissions, it might create it globally.
                 voice_channel = await host_guild.create_voice_channel(
                     name=voice_channel_name,
                     overwrites=overwrites,
                     user_limit=99,
                     category=category # category can be None
                 )
                 logging.info(f"Created voice channel '{voice_channel.name}' (ID: {voice_channel.id}) in guild '{host_guild.name}'.")
                 # Track the voice channel globally across all SOS
                 self.voice_channels[voice_channel.id] = voice_channel
                 logging.debug(f"Added voice channel {voice_channel.id} to tracking.")

                 # Create an invite link (1-hour expiry)
                 invite = await voice_channel.create_invite(max_age=3600, max_uses=0)
                 invite_url = invite.url
                 logging.info(f"Created invite link for voice channel {voice_channel.id}: {invite_url}")

            except discord.Forbidden:
                 logging.error(f"Bot lacks 'Manage Channels' permission to create voice channel in guild '{host_guild.name}'.")
                 # Use followup.send after deferring
                 await interaction.followup.send(
                      "Bot is missing necessary permissions to create the voice channel.",
                      ephemeral=True
                  )
                 return # Cannot proceed without a voice channel
            except Exception as e:
                 logging.error(f"Failed to create voice channel in guild '{host_guild.name}': {e}")
                 # Use followup.send after deferring
                 await interaction.followup.send(
                      "An error occurred while creating the voice channel. Please try again later.",
                      ephemeral=True
                  )
                 return # Cannot proceed without a voice channel


            # Initialize sos_data after successful voice channel creation
            sos_data = {
                "users": {interaction.user.id: interaction.user.display_name},
                "embed": None, # Embed will be created below
                "status_index": None,
                "fleet_response_index": None,
                "voice_channel": voice_channel,
                "lock": asyncio.Lock(), # Use a lock for modifying sos_data
                "sos_messages": {}, # Map guild_id to the broadcast message object
                "initiator_id": interaction.user.id,
                "last_activity": time.time(),
                "prompted_users": set(), # Track users who have been prompted to join
                "dm_messages": {} # Optional: track DM messages sent
            }


            fleet_response = '\n'.join(sos_data['users'].values())

            # Build the embed
            embed = discord.Embed(
                title="SOS ACTIVATED",
                description=(
                    # Use the invite_url variable here
                    f"**Comms:** {invite_url}\n\n" # Plain text URL
                    f"**Enemy:** {view.enemy_type or 'Open'}\n"
                    f"**Difficulty:** {view.difficulty or 'Open'}\n"
                    f"**Mission Focus:** {view.mission or 'Open'}\n"
                    f"**Voice:** {view.voice or 'Open'}\n"
                    f"**Notes:** {view.notes or 'None'}\n\n"
                ),
                color=discord.Color.red()
            )
            embed.add_field(name="HOST CLAN", value=host_guild.name, inline=False)
            embed.add_field(name="Status", value="**Open**", inline=False)
            status_index = len(embed.fields) - 1
            embed.add_field(name="Fleet Response", value=fleet_response, inline=False)
            fleet_response_index = len(embed.fields) - 1

            sos_data['embed'] = embed
            sos_data['status_index'] = status_index
            sos_data['fleet_response_index'] = fleet_response_index


            # Broadcast to all known GPT channels in the network
            server_listing = self.bot.mongo_db['Server_Listing']
            # Fetch only necessary fields to minimize data transfer, including the role ID
            all_servers_cursor = server_listing.find({}, {"discord_server_id": 1, "gpt_channel_id": 1, "sos_lfg_role_id": 1})
            all_servers_data = await all_servers_cursor.to_list(None)

            logging.info(f"Broadcasting SOS to {len(all_servers_data)} configured servers.")

            for server_data in all_servers_data:
                server_guild_id = server_data.get("discord_server_id")
                server_gpt_channel_id = server_data.get("gpt_channel_id")
                sos_lfg_role_id = server_data.get("sos_lfg_role_id") # Get role ID from DB

                server_guild = self.bot.get_guild(server_guild_id)
                if not server_guild:
                    logging.warning(f"Bot is not in guild with ID {server_guild_id} found in database. Skipping broadcast.")
                    continue

                server_gpt_channel = server_guild.get_channel(server_gpt_channel_id)
                if not server_gpt_channel:
                    logging.warning(f"GPT channel configured in DB (ID: {server_gpt_channel_id}) not found in guild '{server_guild.name}'. Skipping broadcast.")
                    continue

                # --- Prepare Ping Content ---
                ping_content = ""
                if sos_lfg_role_id:
                    sos_lfg_role = server_guild.get_role(sos_lfg_role_id)
                    # Check if role exists, is mentionable, AND bot has permission to mention roles in this channel
                    if sos_lfg_role and sos_lfg_role.mentionable:
                         # Check bot's permission in the *specific channel* where the message is sent
                         # This check requires discord.py 2.0+
                         try:
                             if server_gpt_channel.permissions_for(server_guild.me).mention_roles:
                                 ping_content = sos_lfg_role.mention
                                 logging.debug(f"Bot has mention_roles permission in '{server_guild.name}' channel '{server_gpt_channel.name}'. Adding SOS LFG role mention.")
                             else:
                                 logging.warning(f"Bot lacks 'Mention Roles' permission in channel '{server_gpt_channel.name}' ({server_gpt_channel.id}) in guild '{server_guild.name}'. Cannot ping SOS LFG role.")
                                 # ping_content remains ""
                         except AttributeError:
                              logging.warning(f"discord.py version does not support 'mention_roles' permission check in guild '{server_guild.name}'. Attempting ping anyway.")
                              # If the attribute doesn't exist, assume it might work or fail on send
                              ping_content = sos_lfg_role.mention # Attempt to include mention, discord.py will raise Forbidden on send if not allowed.


                    elif sos_lfg_role_id and not sos_lfg_role:
                         logging.warning(f"SOS LFG role ID {sos_lfg_role_id} found in DB but role object not found in guild '{server_guild.name}'. Cannot ping.")


                try:
                    # Ensure bot has send_messages permission in this channel before sending
                    if not server_gpt_channel.permissions_for(server_guild.me).send_messages:
                         logging.warning(f"Bot lacks 'Send Messages' permission in channel '{server_gpt_channel.name}' ({server_gpt_channel.id}) in guild '{server_guild.name}'. Cannot send SOS embed.")
                         continue # Skip this guild if cannot send messages

                    # Send the message with the optional ping_content AND the embed
                    # discord.py will handle Forbidden for mentions if somehow the permission check above is insufficient
                    sos_message = await server_gpt_channel.send(content=ping_content, embed=embed)
                    sos_data['sos_messages'][server_guild.id] = sos_message
                    logging.info(f"Sent SOS embed {'with' if ping_content else 'without'} ping to guild '{server_guild.name}'.")
                except discord.Forbidden:
                    # Catch forbidden errors specifically, might happen for send or mention
                    logging.error(f"Bot is forbidden from sending messages/mentions to channel '{server_gpt_channel.name}' ({server_gpt_channel.id}) in guild '{server_guild.name}'. Check channel permissions.")
                except Exception as e:
                    logging.error(f"Error sending SOS embed to guild '{server_guild.name}': {e}")

            # Store sos_data after broadcasting (even if some broadcasts failed)
            if voice_channel: # Ensure voice_channel was created successfully
                 self.sos_data_by_channel[voice_channel.id] = sos_data
                 logging.debug(f"Added sos_data for channel {voice_channel.id} to tracking.")

            # Confirm to the user via the original interaction followup
            # Use try-except blocks for interaction responses as well
            try:
                 # Check if the initial defer/response is done (requires discord.py 2.0+)
                 # If not done, send followup.
                 # If done, skip followup or handle appropriately.
                 # Given the AttributeError on is_done(), relying solely on followup.send and catching InteractionResponded might be necessary for older versions.
                 await interaction.followup.send(
                     f"Your SOS has been launched and broadcast to {len(all_servers_data)} servers. Voice channel '{voice_channel_name}' is open in '{category.name if category else 'guild'}' in the host server.", # Include category name if available
                     ephemeral=True
                 )

            except (discord.InteractionResponded, discord.NotFound): # Catch InteractionResponded for older versions
                 logging.warning("Interaction was already responded to before sending final followup.")
            except Exception as e:
                 logging.error(f"Failed to send final SOS launch followup message: {e}")


        except Exception as e:
            # This catches errors from DB access, voice channel creation, or initial steps
            logging.exception(f"An unexpected error occurred during the SOS launch process in guild {interaction.guild.id}: {e}")
            # Use followup.send after deferring, handle potential ResponseAlreadyAcknowledged
            try:
                 # Only send error followup if interaction hasn't been fully responded to yet.
                 # Given AttributeError on is_done(), just attempt followup and catch InteractionResponded
                 await interaction.followup.send(
                     "An internal error occurred while processing your SOS request. Please try again later.",
                     ephemeral=True
                 )
            except (discord.InteractionResponded, discord.NotFound): # Catch InteractionResponded for older versions
                 logging.warning("Interaction already responded to before sending internal error followup.")
            except Exception as fu_e:
                 logging.error(f"Failed to send internal error followup message: {fu_e}")


    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Monitor voice channel activity and manage cleanup timers."""
        # Ignore bot state updates
        voice_channel_id = None

        # Check if the channel has been empty for 2 minutes (120 seconds) at the start
        # This handles cases where the event might be delayed
        if before.channel and before.channel.id in self.voice_channels:
            voice_channel_id = before.channel.id
            voice_channel = self.voice_channels.get(voice_channel_id)
            sos_data = self.sos_data_by_channel.get(voice_channel_id)

            if voice_channel and len(voice_channel.members) == 0 and sos_data and (time.time() - sos_data['last_activity']) > 120:
                logging.info(f"Voice channel {voice_channel_id} was empty for over 2 minutes. Deleting.")
                await self.delete_voice_channel_and_message(voice_channel_id)
                return # Stop processing if the channel was just deleted

        if member.bot:
            return

        # Member joined a voice channel
        if after.channel and after.channel.id in self.voice_channels:
            voice_channel_id = after.channel.id
            # Cancel any pending cleanup task for this channel
            cleanup_task = self.cleanup_tasks.pop(voice_channel_id, None)
            if cleanup_task and not cleanup_task.done(): # .done() also requires discord.py 2.0+
                 try:
                     cleanup_task.cancel()
                     logging.debug(f"Cancelled cleanup task for channel {voice_channel_id} because a member joined.")
                 except AttributeError:
                      logging.warning("discord.py version does not support task.done(). Cannot check/cancel cleanup task reliably.")


            sos_data = self.sos_data_by_channel.get(voice_channel_id)
            if sos_data:
                 sos_data['last_activity'] = time.time() # Update last activity time
                 # Acquire the lock before modifying shared sos_data
                 async with sos_data['lock']:
                     status_field = sos_data['embed'].fields[sos_data['status_index']]
                     if status_field.value != '**Closed**': # Check if status isn't already closed
                         if member.id not in sos_data['users']: # Check if user is already in the list
                             sos_data['users'][member.id] = member.display_name
                             fleet_response = '\n'.join(sos_data['users'].values())
                             # Update the embed field
                             sos_data['embed'].set_field_at(
                                 index=sos_data['fleet_response_index'],
                                 name='Fleet Response',
                                 value=fleet_response,
                                 inline=False
                             )
                             # Check if team is full (4 members)
                             if len(sos_data['users']) >= 4:
                                 sos_data['embed'].set_field_at(
                                     index=sos_data['status_index'],
                                     name='Status',
                                     value='**Closed**', # Set status to Closed
                                     inline=False
                                 )
                             # Update the SOS message embeds in all guilds
                             for guild_id, sos_message in sos_data['sos_messages'].items():
                                 try:
                                     # Check if message object is still valid/cached
                                     if sos_message and isinstance(sos_message, discord.Message):
                                         await sos_message.edit(embed=sos_data['embed'])
                                         logging.debug(f"Updated SOS embed in guild {guild_id} for channel {voice_channel_id} after {member.display_name} joined.")
                                     else:
                                         logging.warning(f"SOS message object for guild {guild_id} in channel {voice_channel_id} is invalid/not cached during update.")

                                 except discord.NotFound:
                                      logging.warning(f"Failed to find message {sos_message.id if isinstance(sos_message, discord.Message) else 'invalid'} in guild {guild_id} for channel {voice_channel_id} during update (NotFound).")
                                 except Exception as e:
                                     logging.error(f"Error updating SOS embed in guild {guild_id} for channel {voice_channel_id}: {e}")
                     # If status is already closed, no need to update users/status


        # Member left a voice channel
        if before.channel and before.channel.id in self.voice_channels:
            voice_channel_id = before.channel.id
            # sos_data is needed to update last_activity, but we don't need the lock just for that.
            voice_channel = self.voice_channels.get(voice_channel_id)

            if voice_channel and len(voice_channel.members) == 0:
                # Schedule cleanup if it's not already scheduled
                # Ensure we don't schedule cleanup if members are still present
                if voice_channel_id not in self.cleanup_tasks:
                    cleanup_task = asyncio.create_task(self.schedule_cleanup(voice_channel_id, 60)) # 60 second delay
                    # Update last activity time when the channel becomes empty
                    sos_data = self.sos_data_by_channel.get(voice_channel_id)
                    if sos_data:
                        sos_data['last_activity'] = time.time()
                    self.cleanup_tasks[voice_channel_id] = cleanup_task
                    logging.debug(f"Scheduled cleanup task for channel {voice_channel_id} in 60 seconds.")
            elif voice_channel and len(voice_channel.members) > 0:
                 # If members are still in the channel, ensure any cleanup task is cancelled
                 # This handles cases where the last person left briefly, then someone else joined
                 cleanup_task = self.cleanup_tasks.pop(voice_channel_id, None)
                 if cleanup_task: # Check if task exists
                     try: # Check if task is done before cancelling (requires discord.py 2.0+)
                         if not cleanup_task.done():
                              cleanup_task.cancel()
                              logging.debug(f"Cancelled cleanup task for channel {voice_channel_id} because members are still present.")
                         else:
                             logging.debug(f"Cleanup task for channel {voice_channel_id} was already done.")
                     except AttributeError:
                         logging.warning("discord.py version does not support task.done(). Cannot reliably cancel cleanup task.")
                         # If done() is not supported, we might cancel a completed task, which is harmless.
                         # Just attempt cancel if task exists.
                         try:
                              cleanup_task.cancel()
                              logging.debug(f"Attempted to cancel cleanup task for channel {voice_channel_id} (done() not supported).")
                         except Exception as e:
                             logging.error(f"Error attempting to cancel cleanup task for channel {voice_channel_id}: {e}")


    async def schedule_cleanup(self, channel_id, delay):
        try:
            logging.debug(f"Cleanup task for channel {channel_id} starting sleep for {delay} seconds.")
            await asyncio.sleep(delay)
            logging.debug(f"Cleanup task for channel {channel_id} finished sleep.")

            voice_channel = self.voice_channels.get(channel_id)
            # Re-check if the channel is still empty after the delay
            if voice_channel and len(voice_channel.members) == 0:
                logging.info(f"Channel {channel_id} is still empty after delay. Proceeding with deletion.")
                await self.delete_voice_channel_and_message(channel_id)
            elif voice_channel:
                logging.info(f"Channel {channel_id} has members again. Cleanup cancelled.")
                # If members are back, remove the cleanup task entry
                self.cleanup_tasks.pop(channel_id, None)
            else:
                 logging.warning(f"Voice channel object with ID {channel_id} not found during scheduled cleanup.")


        except asyncio.CancelledError:
            logging.debug(f"Cleanup task for channel {channel_id} was cancelled.")
            # Clean up the task entry if it was cancelled
            self.cleanup_tasks.pop(channel_id, None)
        except Exception as e:
            logging.error(f"Error in scheduled cleanup for channel {channel_id}: {e}")
            # Clean up the task entry on unexpected errors
            self.cleanup_tasks.pop(channel_id, None)


    async def delete_voice_channel_and_message(self, channel_id):
        """Delete the voice channel and its associated SOS embeds from all servers."""
        # Get and remove sos_data first
        sos_data = self.sos_data_by_channel.pop(channel_id, None)
        # Get and remove voice channel object
        voice_channel = self.voice_channels.pop(channel_id, None)

        if not voice_channel:
            logging.warning(f"Voice channel object with ID {channel_id} not found for deletion.")
            # If voice_channel is not found, maybe sos_data still exists?
            # Proceed to try deleting messages if sos_data was found.

        if voice_channel and len(voice_channel.members) > 0:
            logging.warning(f"Voice channel '{voice_channel.name}' (ID: {channel_id}) unexpectedly has members during deletion attempt. Aborting deletion.")
            # If members are found despite the scheduled cleanup check, put the channel/sos_data back
            self.voice_channels[channel_id] = voice_channel
            if sos_data:
                 self.sos_data_by_channel[channel_id] = sos_data
            return # Do not delete


        logging.info(f"Proceeding to delete voice channel (ID: {channel_id}) and associated messages.")

        # Delete associated SOS messages from all broadcast channels
        if sos_data:
             for guild_id, sos_message in list(sos_data.get("sos_messages", {}).items()): # Iterate over a copy
                 try:
                     # Check if message object is still valid/cached before attempting delete
                     if sos_message and isinstance(sos_message, discord.Message):
                         await sos_message.delete()
                         logging.info(f"Deleted SOS embed message (ID: {sos_message.id}) in guild ID {guild_id} for channel {channel_id}.")
                     else:
                         logging.warning(f"SOS message object for guild {guild_id} in channel {channel_id} is invalid/not cached during deletion.")

                     # Always remove from tracking after attempting deletion for this guild's message
                     sos_data["sos_messages"].pop(guild_id, None)

                 except discord.NotFound:
                     logging.warning(f"SOS embed message in guild ID {guild_id} already deleted or not found for channel {channel_id} (NotFound).")
                     sos_data["sos_messages"].pop(guild_id, None) # Ensure it's removed from tracking
                 except Exception as e:
                     logging.error(f"Error deleting SOS embed message in guild ID {guild_id} for channel {channel_id}: {e}")
                     # Decide whether to remove from tracking on error or retry later?
                     # For simplicity now, let's remove it on error to prevent infinite loops on problematic messages.
                     sos_data["sos_messages"].pop(guild_id, None)


        # Delete the voice channel
        if voice_channel:
             try:
                 await voice_channel.delete(reason="SOS QRF channel cleanup: empty.")
                 logging.info(f"Deleted voice channel '{voice_channel.name}' (ID: {channel_id}).")
             except discord.Forbidden:
                 logging.error(f"Permission denied to delete voice channel '{voice_channel.name}' (ID: {channel_id}).")
             except discord.NotFound:
                 logging.warning(f"Voice channel '{voice_channel.name}' (ID: {channel_id}) already deleted.")
             except Exception as e:
                 logging.error(f"Failed to delete voice channel '{voice_channel.name}' (ID: {channel_id}): {e}")


async def setup(bot):
    # Ensure the bot has the mongo_db client before adding the cog
    if not hasattr(bot, 'mongo_db') or bot.mongo_db is None:
        logging.error("MongoDB client not found in bot object. SOSCog cannot be loaded.")
        return

    await bot.add_cog(SOSCog(bot))