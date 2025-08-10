import discord
from discord.ext import commands
import logging
import asyncio  # Import asyncio for sleep

class GuildManagementCog(commands.Cog):
    """
    A cog to manage guild setup and configurations, including ensuring a
    GPT NETWORK category exists with only required channels and specific roles.
    """

    def __init__(self, bot):
        self.bot = bot

    async def _find_and_clean_specific_channel(
        self,
        guild: discord.Guild,
        category: discord.CategoryChannel,
        channel_name: str,
        overwrites: dict,
        reason: str
    ):
        channels_with_name = [c for c in guild.text_channels if c.name == channel_name]
        target_channel = None
        channels_in_category_with_name = [c for c in channels_with_name if c.category == category]

        if channels_in_category_with_name:
            channels_in_category_with_name.sort(key=lambda c: c.created_at, reverse=True)
            target_channel = channels_in_category_with_name[0]
            for old_channel in channels_in_category_with_name[1:]:
                if old_channel.permissions_for(guild.me).manage_channels:
                    try:
                        logging.info(f"Deleting older duplicate channel '{old_channel.name}' (ID: {old_channel.id}) in category '{category.name}' in guild '{guild.name}'.")
                        await old_channel.delete(reason=f"Cleaning up older duplicate '{channel_name}' channel.")
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        logging.error(f"Error deleting older duplicate channel '{old_channel.name}' (ID: {old_channel.id}): {e}")

        elif channels_with_name:
            channels_with_name.sort(key=lambda c: c.created_at, reverse=True)
            target_channel = channels_with_name[0]
            for old_channel in channels_with_name[1:]:
                if old_channel.permissions_for(guild.me).manage_channels:
                    try:
                        logging.info(f"Deleting extraneous global channel '{old_channel.name}' (ID: {old_channel.id}) in guild '{guild.name}'.")
                        await old_channel.delete(reason=f"Cleaning up extraneous global '{channel_name}' channel.")
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        logging.error(f"Error deleting extraneous global channel '{old_channel.name}' (ID: {old_channel.id}): {e}")

        if target_channel is None:
            try:
                logging.info(f"Creating channel '#{channel_name}' in category '{category.name}' in guild '{guild.name}'.")
                target_channel = await guild.create_text_channel(
                    name=channel_name,
                    overwrites=overwrites,
                    category=category,
                    reason=reason
                )
            except Exception as e:
                logging.error(f"Error creating channel '#{channel_name}' in guild '{guild.name}': {e}")
                return None
        else:
            if target_channel.category != category:
                logging.info(f"Moving channel '#{target_channel.name}' (ID: {target_channel.id}) to category '{category.name}'.")
            if target_channel.permissions_for(guild.me).manage_channels:
                try:
                    await target_channel.edit(category=category, overwrites=overwrites, reason=f"Ensuring channel setup for '{channel_name}'.")
                    logging.info(f"Updated channel '#{target_channel.name}' (ID: {target_channel.id}) category/overwrites.")
                except Exception as e:
                    logging.error(f"Error editing channel '#{target_channel.name}' (ID: {target_channel.id}) in guild '{guild.name}': {e}")
            else:
                logging.warning(f"Bot lacks 'Manage Channels' permission for channel '{target_channel.name}' (ID: {target_channel.id}). Cannot edit category/overwrites.")
        return target_channel

    async def setup_guild(self, guild: discord.Guild, force_refresh=False):
        category_name = "GPT NETWORK"
        gpt_channel_name = "❗｜LFG-SOS"
        monitor_channel_name = "❗｜monitor"
        leaderboard_channel_name = "❗｜leaderboard"
        sos_lfg_role_name = "SOS LFG"
        sos_lfg_role_color = 0xfaee10

        target_channel_names = {gpt_channel_name, monitor_channel_name, leaderboard_channel_name}
        logging.info(f"Starting setup for guild: {guild.name} (ID: {guild.id})")
        bot_member = guild.me
        required_permissions = discord.Permissions(
            manage_channels=True,
            manage_roles=True,
            create_instant_invite=True,
            read_message_history=True,
            manage_messages=True
        )
        if not bot_member.guild_permissions.administrator:
            if not bot_member.guild_permissions >= required_permissions:
                logging.warning(
                    f"Bot lacks sufficient permissions to perform setup in guild '{guild.name}' (ID: {guild.id}). Skipping setup."
                )
                return

        logging.info(f"Bot has sufficient permissions for setup in guild '{guild.name}'. Proceeding.")

        category_overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=False,
                connect=True,
                add_reactions=False
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                add_reactions=True,
                read_message_history=True
            )
        }

        category = discord.utils.get(guild.categories, name=category_name)
        if not category:
            try:
                category = await guild.create_category(
                    name=category_name,
                    overwrites=category_overwrites,
                    reason="Category for GPT Network channels."
                )
                logging.info(f"Created category '{category.name}' (ID: {category.id}) in guild '{guild.name}'.")
            except Exception as e:
                logging.error(f"Error creating category '{category_name}' in guild '{guild.name}': {e}")
                return
        else:
            try:
                await category.edit(overwrites=category_overwrites, reason="Updating category overwrites.")
                logging.info(f"Updated permission overwrites for category '{category.name}' (ID: {category.id}).")
            except Exception as e:
                logging.warning(f"Could not update category overwrites for '{category_name}': {e}")

        if not category:
            logging.error(f"Could not find or create category '{category_name}' in guild '{guild.name}'. Skipping channel setup.")
            return

        logging.info(f"Cleaning extraneous channels in category '{category.name}' (ID: {category.id}) for guild '{guild.name}'.")
        channels_in_category = list(category.channels)
        for channel in channels_in_category:
            if isinstance(channel, discord.TextChannel):
                if channel.name not in target_channel_names:
                    if channel.permissions_for(guild.me).manage_channels:
                        try:
                            logging.info(f"Deleting extraneous channel '{channel.name}' (ID: {channel.id}) in category '{category.name}'.")
                            await channel.delete(reason="Cleanup of extraneous channel in GPT NETWORK category during setup.")
                            await asyncio.sleep(0.5)
                        except Exception as e:
                            logging.error(f"Failed to delete extraneous channel '{channel.name}' (ID: {channel.id}): {e}")
                    else:
                        logging.warning(f"Bot lacks 'Manage Channels' permission for extraneous channel '{channel.name}' (ID: {channel.id}). Cannot delete.")
                else:
                    logging.debug(f"Skipping deletion of channel '{channel.name}' (ID: {channel.id}) as it matches a target name.")
            else:
                logging.debug(f"Skipping non-text channel '{channel.name}' (ID: {channel.id}) in category '{category.name}'.")

        gpt_channel_overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=True,
                attach_files=True,
                add_reactions=False
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                add_reactions=True,
                read_message_history=True
            )
        }
        gpt_channel = await self._find_and_clean_specific_channel(
            guild,
            category,
            gpt_channel_name,
            gpt_channel_overwrites,
            f"Ensuring '#{gpt_channel_name}' channel setup."
        )
        if not gpt_channel:
            logging.error(f"Failed to setup '#{gpt_channel_name}' channel. Skipping remaining setup for guild '{guild.name}'.")
            return

        discord_invite_link = ""
        if gpt_channel:
            try:
                existing_invites = await gpt_channel.invites()
                permanent_invites = [inv for inv in existing_invites if inv.max_age == 0 and inv.max_uses == 0]
                if permanent_invites:
                    invite = permanent_invites[0]
                    logging.info(f"Using existing permanent invite link for '#{gpt_channel_name}' (ID: {gpt_channel.id}): {invite.url}")
                else:
                    invite = await gpt_channel.create_invite(max_age=0, max_uses=0, unique=True, reason="Permanent invite for GPT Network channel.")
                    logging.info(f"Created new permanent invite link for '#{gpt_channel_name}' (ID: {gpt_channel.id}): {invite.url}")
                discord_invite_link = invite.url
            except discord.Forbidden:
                logging.warning(f"Bot lacks 'Create Instant Invite' permission in '{gpt_channel.name}' (ID: {gpt_channel.id}) in guild '{guild.name}'. Cannot create invite link.")
            except Exception as e:
                logging.error(f"Error creating/finding invite link for '#{gpt_channel_name}': {e}")

        gpt_stat_access_role = discord.utils.get(guild.roles, name="GPT STAT ACCESS")
        if not gpt_stat_access_role:
            try:
                permissions = discord.Permissions.none()
                permissions.use_application_commands = True
                gpt_stat_access_role = await guild.create_role(
                    name="GPT STAT ACCESS",
                    mentionable=True,
                    permissions=permissions,
                    reason="Role for stats access, including slash commands."
                )
                logging.info(f"Created role 'GPT STAT ACCESS' (ID: {gpt_stat_access_role.id}) in guild '{guild.name}'.")
            except Exception as e:
                logging.error(f"Error creating role 'GPT STAT ACCESS' in guild '{guild.name}': {e}")
        else:
            logging.info(f"Role 'GPT STAT ACCESS' (ID: {gpt_stat_access_role.id}) already exists in guild '{guild.name}'.")
            try:
                current_perms = gpt_stat_access_role.permissions
                if not current_perms.use_application_commands:
                    updated_perms = discord.Permissions(current_perms.value)
                    updated_perms.use_application_commands = True
                    await gpt_stat_access_role.edit(
                        permissions=updated_perms,
                        reason="Enabling slash commands for GPT STAT ACCESS role"
                    )
                    logging.info(
                        f"Updated GPT STAT ACCESS role (ID: {gpt_stat_access_role.id}) to allow use of slash commands in guild "
                        f"'{guild.name}'."
                    )
            except Exception as e:
                logging.error(f"Failed to set use_application_commands for GPT STAT ACCESS role (ID: {gpt_stat_access_role.id}) in guild '{guild.name}': {e}")

        sos_lfg_role = discord.utils.get(guild.roles, name=sos_lfg_role_name)
        if not sos_lfg_role:
            try:
                permissions = discord.Permissions.none()
                sos_lfg_role = await guild.create_role(
                    name=sos_lfg_role_name,
                    mentionable=True,
                    permissions=permissions,
                    color=discord.Color(sos_lfg_role_color),
                    reason="Role for pinging users interested in SOS LFG."
                )
                logging.info(f"Created role '{sos_lfg_role_name}' (ID: {sos_lfg_role.id}) in guild '{guild.name}' with color {hex(sos_lfg_role_color)}.")
            except Exception as e:
                logging.error(f"Error creating role '{sos_lfg_role_name}' in guild '{guild.name}': {e}")
        else:
            logging.info(f"Role '{sos_lfg_role_name}' (ID: {sos_lfg_role.id}) already exists in guild '{guild.name}'.")
            if sos_lfg_role.color != discord.Color(sos_lfg_role_color):
                try:
                    await sos_lfg_role.edit(color=discord.Color(sos_lfg_role_color), reason=f"Updating color for {sos_lfg_role_name} role.")
                    logging.info(f"Updated color for role '{sos_lfg_role_name}' (ID: {sos_lfg_role.id}) to {hex(sos_lfg_role_color)} in guild '{guild.name}'.")
                except Exception as e:
                    logging.error(f"Failed to update color for role '{sos_lfg_role_name}' (ID: {sos_lfg_role.id}) in guild '{guild.name}': {e}")

        monitor_overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False,
                read_message_history=False,
                send_messages=False,
                add_reactions=False
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                add_reactions=True,
                read_message_history=True
            )
        }
        if gpt_stat_access_role:
            monitor_overwrites[gpt_stat_access_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                add_reactions=False,
                read_message_history=True
            )
        if sos_lfg_role:
            monitor_overwrites[sos_lfg_role] = discord.PermissionOverwrite(
                view_channel=False
            )

        monitor_channel = await self._find_and_clean_specific_channel(
            guild,
            category,
            monitor_channel_name,
            monitor_overwrites,
            f"Ensuring '#{monitor_channel_name}' channel setup."
        )
        if not monitor_channel:
            logging.warning(f"Failed to setup '#{monitor_channel_name}' channel in guild '{guild.name}'.")

        leaderboard_overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                add_reactions=False,
                read_message_history=True
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                add_reactions=True,
                read_message_history=True
            )
        }
        if sos_lfg_role:
            leaderboard_overwrites[sos_lfg_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                add_reactions=False,
                read_message_history=True
            )

        leaderboard_channel = await self._find_and_clean_specific_channel(
            guild,
            category,
            leaderboard_channel_name,
            leaderboard_overwrites,
            f"Ensuring '#{leaderboard_channel_name}' channel setup."
        )
        if not leaderboard_channel:
            logging.warning(f"Failed to setup '#{leaderboard_channel_name}' channel in guild '{guild.name}'.")

        server_listing = self.bot.mongo_db["Server_Listing"]
        update_data = {
            "discord_server_id": guild.id,
            "discord_server_name": guild.name,
            "category_id": category.id if category else None,
            "gpt_channel_id": gpt_channel.id if gpt_channel else None,
            "discord_invite_link": discord_invite_link,
            "gpt_stat_access_role_id": gpt_stat_access_role.id if gpt_stat_access_role else None,
            "sos_lfg_role_id": sos_lfg_role.id if sos_lfg_role else None,
            "monitor_channel_id": monitor_channel.id if monitor_channel else None,
            "leaderboard_channel_id": leaderboard_channel.id if leaderboard_channel else None,
        }
        try:
            await server_listing.update_one(
                {"discord_server_id": guild.id},
                {"$set": update_data},
                upsert=True
            )
            logging.info(f"Upserted server data (channels, role IDs) for guild '{guild.name}'.")
        except Exception as e:
            logging.error(f"Error updating server listing for '{guild.name}': {e}")

        if gpt_channel:
            await self.refresh_sos_menu(guild, force_refresh)
        else:
            logging.warning(f"Skipping SOS menu refresh for guild '{guild.name}' because gpt_channel was not set up.")

    async def refresh_sos_menu(self, guild, force_refresh=False):
        menu_view_cog = self.bot.get_cog("MenuViewCog")
        if not menu_view_cog:
            logging.warning("MenuViewCog is not loaded. Cannot refresh SOS menu.")
            return

        server_listing = self.bot.mongo_db['Server_Listing']
        server_data = await server_listing.find_one({"discord_server_id": guild.id})
        if not server_data:
            logging.warning(f"Server data for guild '{guild.name}' not found. Cannot refresh SOS menu.")
            return

        gpt_channel_id = server_data.get("gpt_channel_id")
        gpt_channel = guild.get_channel(gpt_channel_id)
        if not gpt_channel or not isinstance(gpt_channel, discord.TextChannel):
            logging.warning(
                f"GPT channel for guild '{guild.name}' not found or not a TextChannel. "
                f"Channel ID from DB: {gpt_channel_id}. Cannot refresh SOS menu."
            )
            return

        can_read_history = gpt_channel.permissions_for(guild.me).read_message_history
        can_manage_messages = gpt_channel.permissions_for(guild.me).manage_messages
        can_send_messages = gpt_channel.permissions_for(guild.me).send_messages

        if force_refresh:
            if not can_manage_messages or not can_read_history:
                logging.warning(
                    f"Bot lacks 'Manage Messages' or 'Read Message History' permission in '{gpt_channel.name}' (ID: {gpt_channel.id}). "
                    f"Skipping old bot message deletion during menu refresh."
                )
            else:
                try:
                    deleted_count = 0
                    async for message in gpt_channel.history(limit=50):
                        if message.author == self.bot.user and message.embeds:
                            embed = message.embeds[0]
                            if embed.title in ["SOS ACTIVATED", "Welcome to the SOS Alliance Network!"]:
                                try:
                                    logging.info(f"Deleting old bot message in '{guild.name}' channel '{gpt_channel.name}' (Message ID: {message.id}, Title: '{embed.title}').")
                                    await message.delete()
                                    deleted_count += 1
                                except Exception as delete_error:
                                    logging.error(f"Error deleting message {message.id} in '{gpt_channel.name}' in guild '{guild.name}': {delete_error}")
                    if deleted_count > 0:
                        logging.info(f"Finished cleaning old messages in '{gpt_channel.name}' in guild '{guild.name}'. Deleted {deleted_count} messages.")
                except Exception as e:
                    logging.error(f"Error fetching message history for cleanup in '{gpt_channel.name}' in guild '{guild.name}': {e}")

        if not can_send_messages:
            logging.warning(f"Bot lacks 'Send Messages' permission in '{gpt_channel.name}' (ID: {gpt_channel.id}) in guild '{guild.name}'. Cannot send SOS menu.")
            return

        try:
            await menu_view_cog.send_sos_menu_to_guild(guild)
            logging.info(f"Sent SOS menu to '{guild.name}'.")
        except Exception as e:
            logging.error(f"Error sending SOS menu to '{guild.name}': {e}")

    async def _leave_unknown_guilds(self):
        logging.info("Checking for unknown guilds...")
        try:
            server_listing = self.bot.mongo_db['Server_Listing']
            known_guild_ids_cursor = server_listing.find({}, {"discord_server_id": 1})
            known_guild_ids = set([doc["discord_server_id"] for doc in await known_guild_ids_cursor.to_list(None)])
            for guild in list(self.bot.guilds):
                if guild.id not in known_guild_ids:
                    logging.warning(f"Bot is in unknown guild: {guild.name} (ID: {guild.id}). Leaving guild.")
                    try:
                        await guild.leave()
                        logging.info(f"Successfully left guild: {guild.name} (ID: {guild.id}).")
                    except discord.Forbidden:
                        logging.error(f"Forbidden from leaving guild: {guild.name} (ID: {guild.id}). Check bot permissions.")
                    except Exception as e:
                        logging.error(f"Error leaving guild {guild.name} (ID: {guild.id}): {e}")
                else:
                    logging.debug(f"Guild {guild.name} (ID: {guild.id}) is a known guild. Staying.")
        except Exception as e:
            logging.error(f"Error during unknown guild check: {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info("GuildManagementCog is ready.")
        logging.info("Starting guild setup for allowed guilds on startup.")
        allowed_guild_ids = [1172948128509468742, 1221490168670715936, 1214787549655203862]

        for guild in self.bot.guilds:
            logging.info(f"Checking setup for guild: {guild.name} (ID: {guild.id})")
            if guild.id in allowed_guild_ids:
                try:
                    await self.setup_guild(guild, force_refresh=True)
                except Exception as e:
                    logging.error(f"Error setting up guild '{guild.name}': {e}")
            else:
                logging.info(f"Skipping setup for guild: {guild.name} (ID: {guild.id}) - Not in the allowed list.")

        await self._leave_unknown_guilds()
        logging.info("Finished initial guild setup for all joined guilds.")

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        logging.info(f"Joined new guild: {guild.name} (ID: {guild.id})")
        try:
            await self.setup_guild(guild, force_refresh=True)
        except Exception as e:
            logging.error(f"Error setting up new guild '{guild.name}': {e}")

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        """
        When the bot is removed from a guild, prune its Server_Listing entry to avoid stale records.
        """
        try:
            server_listing = self.bot.mongo_db['Server_Listing']
            result = await server_listing.delete_one({"discord_server_id": guild.id})
            if result.deleted_count:
                logging.info(f"Pruned Server_Listing entry for removed guild '{guild.name}' (ID: {guild.id}).")
            else:
                logging.info(f"No Server_Listing entry found to prune for removed guild '{guild.name}' (ID: {guild.id}).")
        except Exception as e:
            logging.error(f"Failed to prune Server_Listing on guild removal for '{guild.name}' (ID: {guild.id}): {e}")

async def setup(bot):
    await bot.add_cog(GuildManagementCog(bot))
