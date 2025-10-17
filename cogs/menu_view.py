# cogs/menu_view_cog.py

import discord
from discord.ext import commands
import logging
import os
import asyncio
from PIL import Image
from io import BytesIO
from .extract_helpers import validate_stat
from database import get_mission_docs, update_mission_player_fields, get_server_listing_by_id

# Map each clan name to the ID of the guild where we store the invite link
CLAN_SERVER_IDS = {
    "Guardians of Freedom": 1172948128509468742,
    "Heck Snorkelers": 1221490168670715936,
    "Galactic Phantom Taskforce": 1214787549655203862,
}

# Define the path to the image file relative to where the bot is run
IMAGE_PATH = "gpt_network.png"

class SOSMenuView(discord.ui.View):
    """
    A persistent view providing buttons for SOS-related actions.
    """
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="STORE", style=discord.ButtonStyle.secondary, custom_id="store_button", emoji="⭐")
    async def store_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Open Store", style=discord.ButtonStyle.link, url="https://gptfleet-shop.fourthwall.com/"))
            await interaction.followup.send("Open the store:", view=view, ephemeral=True)
        except Exception as e:
            await interaction.followup.send("Unable to open store right now.", ephemeral=True)
            logging.error(f"Error in store_button: {e}")

    #@discord.ui.button(label="CALL SOS", style=discord.ButtonStyle.danger, custom_id="launch_sos_button", disabled=False)
    #async def launch_sos_button(self, interaction: discord.Interaction, button: discord.ui.Button):
    #    sos_cog = self.bot.get_cog("SOSCog")
    #    if sos_cog:
    #       if not interaction.response.is_done():
    #            await interaction.response.defer(ephemeral=True)
    #        try:
    #            await sos_cog.launch_sos(interaction)
    #        except Exception as e:
    #            await interaction.followup.send(
    #                "An error occurred while launching SOS. Please try again later.",
    #                ephemeral=True
    #            )
    #            logging.error(f"Error in launch_sos_button: {e}")
    #    else:
    #        logging.error("SOSCog not found when pressing CALL SOS. Ensure 'cogs.sos_cog' loaded correctly.")
    #        await interaction.response.send_message(
    #            "The SOS system is not available at the moment. Please try again later.",
    #            ephemeral=True
    #        )

    #@discord.ui.button(label="MAKE LFG", style=discord.ButtonStyle.success, custom_id="create_mission_button")
    #async def create_mission_button(self, interaction: discord.Interaction, button: discord.ui.Button):
    #    sos_view_cog = self.bot.get_cog("SOSViewCog")
    #    if sos_view_cog:
    #        await interaction.response.defer(ephemeral=True)
    #        try:
    #            view = sos_view_cog.get_sos_view()
    #            await interaction.followup.send(
    #                "Let's start creating your SOS mission. Please select your options below:",
    #                view=view,
    #                ephemeral=True
    #            )
    #        except Exception as e:
    #            await interaction.followup.send(
    #                "An error occurred while creating the mission. Please try again later.",
    #                ephemeral=True
    #            )
    #            logging.error(f"Error in create_mission_button: {e}")
    #    else:
    #        logging.error("SOSViewCog not found when pressing MAKE LFG. Ensure 'cogs.sos_view' loaded correctly.")
    #        await interaction.response.send_message(
    #            "The mission creation system is not available at the moment. Please try again later.",
    #            ephemeral=True
    #        )

    @discord.ui.button(label="REGISTER", style=discord.ButtonStyle.primary, custom_id="register_button")
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        register_modal_cog = self.bot.get_cog("RegisterModalCog")
        if register_modal_cog:
            try:
                modal = register_modal_cog.get_register_modal(interaction)
                await interaction.response.send_modal(modal)
            except Exception as e:
                await interaction.response.send_message(
                    "An error occurred while opening the registration modal. Please try again later.",
                    ephemeral=True
                )
                logging.error(f"Error in register_button: {e}")
        else:
            logging.error("RegisterModalCog not found when pressing REGISTER. Ensure 'cogs.register_modal' loaded correctly.")
            await interaction.response.send_message(
                "The registration system is not available at the moment. Please try again later.",
                ephemeral=True
            )


    @discord.ui.button(
        label="UPLOAD MISSION",
        style=discord.ButtonStyle.success,
        custom_id="submit_stats_button"
    )
    async def submit_stats_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        extract_cog = self.bot.get_cog("ExtractCog")
        if not extract_cog:
            logging.warning("ExtractCog not found on button press. Attempting dynamic load of 'cogs.extract_cog'.")
            try:
                await self.bot.load_extension('cogs.extract_cog')
                extract_cog = self.bot.get_cog("ExtractCog")
            except Exception as e:
                logging.error(f"Failed to dynamically load 'cogs.extract_cog': {e}", exc_info=True)

        if extract_cog:
            await extract_cog.submit_stats_button_flow(interaction)
        else:
            logging.error("ExtractCog still unavailable after dynamic load attempt.")
            await interaction.response.send_message(
                "Upload is not available at the moment. Please try again later.",
                ephemeral=True
            )

    @discord.ui.button(label="EDIT MISSION", style=discord.ButtonStyle.success, custom_id="edit_submission_button")
    async def edit_submission_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            modal = EditSubmissionModal(self.bot)
            await interaction.response.send_modal(modal)
        except Exception as e:
            logging.error(f"Error opening edit submission modal: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("Unable to start edit flow.", ephemeral=True)


class EditSubmissionModal(discord.ui.Modal, title="Edit Submission"):
    mission_id = discord.ui.TextInput(label="Mission ID", placeholder="e.g. 1042", required=True, max_length=20)

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        try:
            try:
                mission_id_val = int(str(self.mission_id.value).strip())
            except Exception:
                await interaction.response.send_message("Mission ID must be a number.", ephemeral=True)
                return

            docs = await get_mission_docs(mission_id_val)
            if not docs:
                await interaction.response.send_message(f"No records found for Mission #{mission_id_val}.", ephemeral=True)
                return

            view = EditMissionView(self.bot, mission_id_val, docs)
            player_list = ", ".join([d.get("player_name", "Unknown") for d in docs])
            embed = discord.Embed(title="EDIT MISSION", description=f"Players: {player_list}\nMission #{mission_id_val:07d}", color=discord.Color.purple())
            await interaction.response.send_message(content="Select a player and field to edit:", embed=embed, view=view, ephemeral=True)
        except Exception as e:
            logging.error(f"Error starting edit mission flow: {e}")
            try:
                await interaction.response.send_message("Failed to start edit flow.", ephemeral=True)
            except Exception:
                pass


class EditMissionView(discord.ui.View):
    def __init__(self, bot: commands.Bot, mission_id: int, docs: list[dict]):
        super().__init__(timeout=180)
        self.bot = bot
        self.mission_id = mission_id
        self.docs = docs
        self.selected_player = None

        # Build player select
        options = [discord.SelectOption(label=d.get("player_name", "Unknown")) for d in docs]
        self.add_item(PlayerSelect(options, self))
        # Build field select
        fields = ['Kills', 'Shots Fired', 'Shots Hit', 'Deaths', 'Melee Kills', 'Stims Used', 'Samples Extracted', 'Stratagems Used']
        field_options = [discord.SelectOption(label=f) for f in fields]
        self.add_item(FieldSelect(field_options, self))

    @discord.ui.button(label="DONE", style=discord.ButtonStyle.success)
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content=f"Finished editing Mission #{self.mission_id}.", view=self)


class PlayerSelect(discord.ui.Select):
    def __init__(self, options, parent: EditMissionView):
        super().__init__(placeholder="Select player", options=options)
        self.parent = parent

    async def callback(self, interaction: discord.Interaction):
        self.parent.selected_player = self.values[0]
        await interaction.response.edit_message(content=f"Selected player: {self.parent.selected_player}. Now select a field.")


class FieldSelect(discord.ui.Select):
    def __init__(self, options, parent: EditMissionView):
        super().__init__(placeholder="Select field", options=options)
        self.parent = parent

    async def callback(self, interaction: discord.Interaction):
        if not self.parent.selected_player:
            await interaction.response.send_message("Please select a player first.", ephemeral=True)
            return
        await interaction.response.edit_message(content=f"Enter new value for {self.values[0]} (Player {self.parent.selected_player}) in chat…")
        def check(m: discord.Message):
            return m.author == interaction.user and m.channel == interaction.channel
        # Remove dropdowns/components from the ephemeral message after selection
        try:
            await interaction.edit_original_response(view=None)
        except Exception:
            pass
        try:
            msg = await self.parent.bot.wait_for('message', check=check, timeout=60.0)
            try:
                await msg.delete()
            except Exception:
                pass
            field = self.values[0]
            # Capture old value from provided docs
            old_value = None
            try:
                prev_doc = next((d for d in self.parent.docs if d.get("player_name") == self.parent.selected_player), None)
                if prev_doc is not None:
                    old_value = prev_doc.get(field)
            except Exception:
                prev_doc = None
            try:
                new_value = validate_stat(field, msg.content.strip())
            except Exception:
                await interaction.followup.send("Invalid value.", ephemeral=True)
                return
            # Prepare updates dict; validate_stat may return formatted strings
            updates = {field: new_value}
            ok = await update_mission_player_fields(self.parent.mission_id, self.parent.selected_player, updates)
            if ok:
                await interaction.followup.send(f"Updated Mission #{self.parent.mission_id:07d} • {self.parent.selected_player} • {field} = {new_value}", ephemeral=True)
                # Post an audit entry to the stat-reports channel and update local snapshot
                try:
                    server_data = await get_server_listing_by_id(interaction.guild_id)
                    monitor_channel_id = server_data.get("monitor_channel_id") if server_data else None
                    channel = interaction.guild.get_channel(monitor_channel_id) if monitor_channel_id else None
                    if channel is None:
                        channel = next((c for c in interaction.guild.text_channels if c.name in {"❗｜stat-reports", "stat-reports"}), None)
                    if channel is not None:
                        embed = discord.Embed(title="Mission Edit", color=discord.Color.orange())
                        embed.description = f"Mission #{self.parent.mission_id:07d}"
                        embed.add_field(name="Player", value=self.parent.selected_player, inline=True)
                        embed.add_field(name="Field", value=field, inline=True)
                        if old_value is not None:
                            embed.add_field(name="From", value=str(old_value), inline=True)
                        embed.add_field(name="To", value=str(new_value), inline=True)
                        embed.set_footer(text=f"Edited by {interaction.user} ({interaction.user.id})")
                        await channel.send(embed=embed)
                except Exception as e:
                    logging.warning(f"Failed to post edit audit to stat-reports: {e}")
                try:
                    if prev_doc is not None:
                        prev_doc[field] = new_value
                except Exception:
                    pass
                try:
                    await interaction.edit_original_response(view=None)
                except Exception:
                    pass
            else:
                await interaction.followup.send("Update failed; mission/player not found.", ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("Timed out waiting for input.", ephemeral=True)

class MenuViewCog(commands.Cog):
    """
    A cog to manage and provide the SOSMenuView. It builds a single Markdown
    string with clickable links for each clan, using the invite link from
    the clan's corresponding server ID, and embeds an image.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sos_menu_view = SOSMenuView(bot)
        self.bot.add_view(self.sos_menu_view)
        logging.info("SOSMenuView registered globally as a persistent view.")

    async def send_sos_menu_to_guild(self, guild: discord.Guild):
        """
        Sends the SOS menu with instructions to a specific guild's designated GPT channel.
        Each clan name links to that clan's server invite link (retrieved from MongoDB).
        Includes an embedded image (as thumbnail).
        """
        try:
            # Access the Server_Listing collection from the bot's mongo_db attribute
            server_listing = self.bot.mongo_db["Server_Listing"]
            server_data = await server_listing.find_one({"discord_server_id": guild.id})

            if not server_data:
                logging.warning(f"No server data found for guild '{guild.name}'. Skipping sending SOS menu.")
                return

            gpt_channel_id = server_data.get("gpt_channel_id")
            if not gpt_channel_id:
                logging.warning(f"Server data for '{guild.name}' does not contain 'gpt_channel_id'. Cannot send SOS menu.")
                return

            gpt_channel = guild.get_channel(gpt_channel_id)
            if not gpt_channel:
                logging.warning(f"GPT channel (ID: {gpt_channel_id}) not found in guild '{guild.name}'. Cannot send SOS menu.")
                return

            embed_description = (
                "- REGISTER: Register your Helldivers 2 player and Super Earth ship name.\n\n"
                "- UPLOAD MISSION: Submit your screenshots for mission stats to the database.\n\n"
                "- EDIT MISSION: Edit a previous mission by ID.\n\n"
                "- STORE: Support the fleet at gptfleet-shop.fourthwall.com.\n\n"
                "*Please select an option below:*"
            )

            embed = discord.Embed(
                title="GPT CLAN MENU",
                description=embed_description,
                color=discord.Color.blue()
            )

            file = None
            try:
                if os.path.exists(IMAGE_PATH):
                    img = Image.open(IMAGE_PATH)
                    scale = 1.3
                    new_size = (int(img.width * scale), int(img.height * scale))
                    img_resized = img.resize(new_size, Image.LANCZOS)
                    buf = BytesIO()
                    img_resized.save(buf, format="PNG")
                    buf.seek(0)
                    file = discord.File(buf, filename="gpt_network_scaled.png")
                    embed.set_image(url="attachment://gpt_network_scaled.png")
                    logging.debug(f"Image '{IMAGE_PATH}' resized to {new_size} and prepared for embed.")
                else:
                    logging.warning(f"Image file not found at path: {IMAGE_PATH}. Cannot embed image.")
            except Exception as e:
                logging.error(f"Error preparing image file '{IMAGE_PATH}' for embed: {e}", exc_info=True)
                file = None

            # Idempotent behavior: edit existing menu if possible; otherwise post and store ID
            try:
                logging.info(f"Preparing to upsert menu in channel: {gpt_channel} in guild {guild.name}")
                menu_message_id = server_data.get("menu_message_id")
                existing_message = None
                if menu_message_id:
                    try:
                        existing_message = await gpt_channel.fetch_message(int(menu_message_id))
                    except Exception:
                        existing_message = None

                # Always delete previous menu posts before posting a new one
                try:
                    # Delete the tracked menu if it exists
                    if existing_message:
                        try:
                            await existing_message.delete()
                            logging.info(f"Deleted existing tracked menu message {existing_message.id} in '{gpt_channel.name}'.")
                        except Exception:
                            pass
                    # Purge any other old menu messages authored by the bot
                    total_deleted = 0
                    while True:
                        found = False
                        async for m in gpt_channel.history(limit=200):
                            if m.author == self.bot.user and m.embeds and m.embeds[0].title and "CLAN MENU" in m.embeds[0].title.upper():
                                try:
                                    await m.delete()
                                    total_deleted += 1
                                    found = True
                                except Exception:
                                    pass
                        if not found:
                            break
                    if total_deleted:
                        logging.info(f"Deleted {total_deleted} old clan menu messages in '{gpt_channel.name}' for guild '{guild.name}'.")
                except Exception as e:
                    logging.warning(f"Failed to purge old clan menu messages in '{gpt_channel.name}' for guild '{guild.name}': {e}")

                # Post the new menu message
                if file:
                    sent = await gpt_channel.send(embed=embed, view=self.sos_menu_view, file=file)
                else:
                    sent = await gpt_channel.send(embed=embed, view=self.sos_menu_view)
                # Store new message ID
                try:
                    await server_listing.update_one(
                        {"discord_server_id": guild.id},
                        {"$set": {"menu_message_id": int(sent.id)}},
                        upsert=True
                    )
                    logging.info(f"Stored menu_message_id for guild '{guild.name}': {sent.id}")
                except Exception as e:
                    logging.warning(f"Failed to store menu_message_id for guild '{guild.name}': {e}")
                logging.info(f"Sent new SOS menu to guild '{guild.name}' in channel '{gpt_channel.name}'.")
            except discord.Forbidden:
                logging.error(f"Bot is forbidden from sending/editing messages in channel '{gpt_channel.name}' ({gpt_channel.id}) in guild '{guild.name}'.")
            except Exception as e:
                logging.error(f"Error upserting SOS menu message in guild '{guild.name}': {e}", exc_info=True)

        except Exception as e:
            logging.error(f"An unexpected error occurred while preparing to send SOS menu to guild '{guild.name}': {e}", exc_info=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(MenuViewCog(bot))

