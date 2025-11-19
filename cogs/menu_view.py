# cogs/menu_view_cog.py
import asyncio
import logging
import os
from io import BytesIO

import discord
from discord.ext import commands
from PIL import Image

from .extract_helpers import validate_stat
from database import (
    get_mission_docs,
    get_server_listing_by_id,
    update_mission_player_fields,
)

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

    @discord.ui.button(
        label="STORE",
        style=discord.ButtonStyle.secondary,
        custom_id="store_button",
        emoji="⭐",
    )
    async def store_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        try:
            # Safely acknowledge the interaction, then send a follow-up with the link button.
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)

            view = discord.ui.View()
            view.add_item(
                discord.ui.Button(
                    label="Open Store",
                    style=discord.ButtonStyle.link,
                    url="https://gptfleet-shop.fourthwall.com/",
                )
            )
            await interaction.followup.send("Open the store:", view=view, ephemeral=True)
        except Exception as exc:
            logging.error("Error in store_button: %s", exc, exc_info=True)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "Unable to open store right now.", ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "Unable to open store right now.", ephemeral=True
                    )
            except Exception:
                # Swallow any secondary failures so the original exception is logged only.
                pass

    @discord.ui.button(
        label="REGISTER",
        style=discord.ButtonStyle.primary,
        custom_id="register_button",
    )
    async def register_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        register_modal_cog = self.bot.get_cog("RegisterModalCog")
        if not register_modal_cog:
            logging.error(
                "RegisterModalCog not found when pressing REGISTER. "
                "Ensure 'cogs.register_modal' is loaded correctly."
            )
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "The registration system is not available at the moment. "
                        "Please try again later.",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        "The registration system is not available at the moment. "
                        "Please try again later.",
                        ephemeral=True,
                    )
            except Exception:
                pass
            return

        try:
            modal = register_modal_cog.get_register_modal(interaction)
            await interaction.response.send_modal(modal)
        except Exception as exc:
            logging.error("Error in register_button: %s", exc, exc_info=True)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "An error occurred while opening the registration modal. "
                        "Please try again later.",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        "An error occurred while opening the registration modal. "
                        "Please try again later.",
                        ephemeral=True,
                    )
            except Exception:
                pass

    @discord.ui.button(
        label="UPLOAD MISSION",
        style=discord.ButtonStyle.success,
        custom_id="submit_stats_button",
    )
    async def submit_stats_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        try:
            extract_cog = self.bot.get_cog("ExtractCog")
            if not extract_cog:
                logging.warning(
                    "ExtractCog not found on button press. Attempting dynamic load of "
                    "'cogs.extract_cog'."
                )
                try:
                    await self.bot.load_extension("cogs.extract_cog")
                    extract_cog = self.bot.get_cog("ExtractCog")
                except Exception as exc:
                    logging.error(
                        "Failed to dynamically load 'cogs.extract_cog': %s",
                        exc,
                        exc_info=True,
                    )

            if extract_cog:
                # Delegate full flow to the ExtractCog, which is responsible for
                # acknowledging the interaction and handling follow-ups.
                await extract_cog.submit_stats_button_flow(interaction)
            else:
                logging.error("ExtractCog still unavailable after dynamic load attempt.")
                try:
                    if interaction.response.is_done():
                        await interaction.followup.send(
                            "Upload is not available at the moment. "
                            "Please try again later.",
                            ephemeral=True,
                        )
                    else:
                        await interaction.response.send_message(
                            "Upload is not available at the moment. "
                            "Please try again later.",
                            ephemeral=True,
                        )
                except Exception:
                    pass
        except Exception as exc:
            logging.error("Error in submit_stats_button: %s", exc, exc_info=True)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "An unexpected error occurred while starting the upload. "
                        "Please try again.",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        "An unexpected error occurred while starting the upload. "
                        "Please try again.",
                        ephemeral=True,
                    )
            except Exception:
                pass

    @discord.ui.button(
        label="EDIT MISSION",
        style=discord.ButtonStyle.success,
        custom_id="edit_submission_button",
    )
    async def edit_submission_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        try:
            modal = EditSubmissionModal(self.bot)
            await interaction.response.send_modal(modal)
        except Exception as exc:
            logging.error("Error opening edit submission modal: %s", exc, exc_info=True)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "Unable to start edit flow.", ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "Unable to start edit flow.", ephemeral=True
                    )
            except Exception:
                pass


class EditSubmissionModal(discord.ui.Modal, title="Edit Submission"):
    mission_id = discord.ui.TextInput(
        label="Mission ID", placeholder="e.g. 1042", required=True, max_length=20
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            try:
                mission_id_value = int(str(self.mission_id.value).strip())
            except Exception:
                await interaction.response.send_message(
                    "Mission ID must be a number.", ephemeral=True
                )
                return

            docs = await get_mission_docs(mission_id_value)
            if not docs:
                await interaction.response.send_message(
                    f"No records found for Mission #{mission_id_value}.", ephemeral=True
                )
                return

            view = EditMissionView(self.bot, mission_id_value, docs)
            player_list = ", ".join(doc.get("player_name", "Unknown") for doc in docs)
            embed = discord.Embed(
                title="EDIT MISSION",
                description=(
                    f"Players: {player_list}\n"
                    f"Mission #{mission_id_value:07d}"
                ),
                color=discord.Color.purple(),
            )
            await interaction.response.send_message(
                content="Select a player and field to edit:",
                embed=embed,
                view=view,
                ephemeral=True,
            )
        except Exception as exc:
            logging.error("Error starting edit mission flow: %s", exc, exc_info=True)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "Failed to start edit flow.", ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "Failed to start edit flow.", ephemeral=True
                    )
            except Exception:
                pass


class EditMissionView(discord.ui.View):
    def __init__(
        self, bot: commands.Bot, mission_id: int, docs: list[dict]
    ) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.mission_id = mission_id
        self.docs = docs
        self.selected_player: str | None = None

        # Build player select
        options = [
            discord.SelectOption(label=doc.get("player_name", "Unknown"))
            for doc in docs
        ]
        self.add_item(PlayerSelect(options, self))

        # Build field select
        fields = [
            "Kills",
            "Shots Fired",
            "Shots Hit",
            "Deaths",
            "Melee Kills",
            "Stims Used",
            "Samples Extracted",
            "Stratagems Used",
        ]
        field_options = [discord.SelectOption(label=field) for field in fields]
        self.add_item(FieldSelect(field_options, self))

    @discord.ui.button(label="DONE", style=discord.ButtonStyle.success)
    async def done(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        try:
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(
                content=f"Finished editing Mission #{self.mission_id}.", view=self
            )
        except Exception as exc:
            logging.error(
                "Error completing edit mission view: %s", exc, exc_info=True
            )
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "Unable to finish the edit session. Please try again.",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        "Unable to finish the edit session. Please try again.",
                        ephemeral=True,
                    )
            except Exception:
                pass


class PlayerSelect(discord.ui.Select):
    def __init__(self, options, parent: EditMissionView) -> None:
        super().__init__(placeholder="Select player", options=options)
        self.parent = parent

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            self.parent.selected_player = self.values[0]
            await interaction.response.edit_message(
                content=(
                    f"Selected player: {self.parent.selected_player}. "
                    "Now select a field."
                )
            )
        except Exception as exc:
            logging.error("Error in PlayerSelect callback: %s", exc, exc_info=True)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "An error occurred while selecting the player. "
                        "Please try again.",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        "An error occurred while selecting the player. "
                        "Please try again.",
                        ephemeral=True,
                    )
            except Exception:
                pass


class FieldSelect(discord.ui.Select):
    def __init__(self, options, parent: EditMissionView) -> None:
        super().__init__(placeholder="Select field", options=options)
        self.parent = parent

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            if not self.parent.selected_player:
                await interaction.response.send_message(
                    "Please select a player first.", ephemeral=True
                )
                return

            await interaction.response.edit_message(
                content=(
                    f"Enter new value for {self.values[0]} "
                    f"(Player {self.parent.selected_player}) in chat."
                )
            )

            def message_check(message: discord.Message) -> bool:
                return (
                    message.author == interaction.user
                    and message.channel == interaction.channel
                )

            # Remove dropdowns/components from the ephemeral message after selection
            try:
                await interaction.edit_original_response(view=None)
            except Exception:
                pass

            try:
                message = await self.parent.bot.wait_for(
                    "message", check=message_check, timeout=60.0
                )
                try:
                    await message.delete()
                except Exception:
                    pass

                field_name = self.values[0]

                # Capture old value from provided docs
                old_value = None
                try:
                    previous_doc = next(
                        (
                            doc
                            for doc in self.parent.docs
                            if doc.get("player_name") == self.parent.selected_player
                        ),
                        None,
                    )
                    if previous_doc is not None:
                        old_value = previous_doc.get(field_name)
                except Exception:
                    previous_doc = None

                try:
                    new_value = validate_stat(field_name, message.content.strip())
                except Exception:
                    await interaction.followup.send(
                        "Invalid value.", ephemeral=True
                    )
                    return

                # Prepare updates dict; validate_stat may return formatted strings
                updates = {field_name: new_value}
                updated = await update_mission_player_fields(
                    self.parent.mission_id, self.parent.selected_player, updates
                )
                if updated:
                    await interaction.followup.send(
                        (
                            f"Updated Mission #{self.parent.mission_id:07d} – "
                            f"{self.parent.selected_player} – "
                            f"{field_name} = {new_value}"
                        ),
                        ephemeral=True,
                    )

                    # Post an audit entry to the stat-reports channel and update local snapshot
                    try:
                        server_data = await get_server_listing_by_id(
                            interaction.guild_id
                        )
                        monitor_channel_id = (
                            server_data.get("monitor_channel_id")
                            if server_data
                            else None
                        )
                        channel = (
                            interaction.guild.get_channel(monitor_channel_id)
                            if monitor_channel_id
                            else None
                        )
                        if channel is None:
                            channel = next(
                                (
                                    text_channel
                                    for text_channel in interaction.guild.text_channels
                                    if text_channel.name
                                    in {"❗｜stat-reports", "stat-reports"}
                                ),
                                None,
                            )
                        if channel is not None:
                            embed = discord.Embed(
                                title="Mission Edit",
                                color=discord.Color.orange(),
                            )
                            embed.description = (
                                f"Mission #{self.parent.mission_id:07d}"
                            )
                            embed.add_field(
                                name="Player",
                                value=self.parent.selected_player,
                                inline=True,
                            )
                            embed.add_field(name="Field", value=field_name, inline=True)
                            if old_value is not None:
                                embed.add_field(
                                    name="From",
                                    value=str(old_value),
                                    inline=True,
                                )
                            embed.add_field(
                                name="To", value=str(new_value), inline=True
                            )
                            embed.set_footer(
                                text=(
                                    f"Edited by {interaction.user} "
                                    f"({interaction.user.id})"
                                )
                            )
                            await channel.send(embed=embed)
                    except Exception as audit_exc:
                        logging.warning(
                            "Failed to post edit audit to stat-reports: %s",
                            audit_exc,
                        )

                    try:
                        if previous_doc is not None:
                            previous_doc[field_name] = new_value
                    except Exception:
                        pass
                    try:
                        await interaction.edit_original_response(view=None)
                    except Exception:
                        pass
                else:
                    await interaction.followup.send(
                        "Update failed; mission/player not found.", ephemeral=True
                    )
            except asyncio.TimeoutError:
                await interaction.followup.send(
                    "Timed out waiting for input.", ephemeral=True
                )
        except Exception as exc:
            logging.error("Error in FieldSelect callback: %s", exc, exc_info=True)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "An error occurred while updating the mission. "
                        "Please try again.",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        "An error occurred while updating the mission. "
                        "Please try again.",
                        ephemeral=True,
                    )
            except Exception:
                pass


class MenuViewCog(commands.Cog):
    """
    A cog to manage and provide the SOSMenuView. It builds a menu message
    with buttons and an embedded image for each guild's configured GPT channel.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sos_menu_view = SOSMenuView(bot)
        # Register the persistent view so its custom_ids are recognized after restarts.
        self.bot.add_view(self.sos_menu_view)
        logging.info("SOSMenuView registered globally as a persistent view.")

    async def send_sos_menu_to_guild(self, guild: discord.Guild) -> None:
        """
        Sends the SOS menu with instructions to a specific guild's GPT channel.
        Includes an embedded image and registers the menu message ID.
        """
        try:
            # Access the Server_Listing collection from the bot's mongo_db attribute
            server_listing = self.bot.mongo_db["Server_Listing"]
            server_data = await server_listing.find_one(
                {"discord_server_id": guild.id}
            )

            if not server_data:
                logging.warning(
                    "No server data found for guild '%s'. Skipping SOS menu.",
                    guild.name,
                )
                return

            gpt_channel_id = server_data.get("gpt_channel_id")
            if not gpt_channel_id:
                logging.warning(
                    "Server data for '%s' missing 'gpt_channel_id'. Cannot send SOS menu.",
                    guild.name,
                )
                return

            gpt_channel = guild.get_channel(gpt_channel_id)
            if not gpt_channel or not isinstance(gpt_channel, discord.TextChannel):
                logging.warning(
                    "GPT channel (ID: %s) not found or not a TextChannel in guild '%s'.",
                    gpt_channel_id,
                    guild.name,
                )
                return

            embed_description = (
                "- REGISTER: Register your Helldivers 2 player and Super Earth ship name.\n\n"
                "- UPLOAD MISSION: Submit your screenshots for mission stats to the database.\n\n"
                "- EDIT MISSION: Edit a previous mission by ID.\n\n"
                "- STORE: Support the fleet at gptfleet-shop.fourthwall.com.\n\n"
                "*Please select an option below:*"
            )

            embed = discord.Embed(
                title="GPTFLEET HD2 CLAN MENU",
                description=embed_description,
                color=discord.Color.blue(),
            )

            image_file = None
            try:
                if os.path.exists(IMAGE_PATH):
                    image = Image.open(IMAGE_PATH)
                    scale = 1.3
                    new_size = (
                        int(image.width * scale),
                        int(image.height * scale),
                    )
                    resized = image.resize(new_size, Image.LANCZOS)
                    buffer = BytesIO()
                    resized.save(buffer, format="PNG")
                    buffer.seek(0)
                    image_file = discord.File(
                        buffer, filename="gpt_network_scaled.png"
                    )
                    embed.set_image(url="attachment://gpt_network_scaled.png")
                    logging.debug(
                        "Image '%s' resized to %s and prepared for embed.",
                        IMAGE_PATH,
                        new_size,
                    )
                else:
                    logging.warning(
                        "Image file not found at path: %s. Cannot embed image.",
                        IMAGE_PATH,
                    )
            except Exception as image_exc:
                logging.error(
                    "Error preparing image file '%s' for embed: %s",
                    IMAGE_PATH,
                    image_exc,
                    exc_info=True,
                )
                image_file = None

            try:
                logging.info(
                    "Preparing to upsert menu in channel: %s in guild %s",
                    gpt_channel,
                    guild.name,
                )
                menu_message_id = server_data.get("menu_message_id")
                existing_message = None
                if menu_message_id:
                    try:
                        existing_message = await gpt_channel.fetch_message(
                            int(menu_message_id)
                        )
                    except Exception:
                        existing_message = None

                # Always delete previous menu posts before posting a new one
                try:
                    # Delete the tracked menu if it exists
                    if existing_message:
                        try:
                            await existing_message.delete()
                            logging.info(
                                "Deleted existing tracked menu message %s in '%s'.",
                                existing_message.id,
                                gpt_channel.name,
                            )
                        except Exception:
                            pass

                    # Purge any other old menu messages authored by the bot
                    total_deleted = 0
                    async for message in gpt_channel.history(limit=200):
                        if (
                            message.author == self.bot.user
                            and message.embeds
                            and message.embeds[0].title
                            and "CLAN MENU"
                            in message.embeds[0].title.upper()
                        ):
                            try:
                                await message.delete()
                                total_deleted += 1
                            except Exception:
                                pass
                    if total_deleted:
                        logging.info(
                            "Deleted %s old clan menu messages in '%s' for guild '%s'.",
                            total_deleted,
                            gpt_channel.name,
                            guild.name,
                        )
                except Exception as cleanup_exc:
                    logging.warning(
                        "Failed to purge old clan menu messages in '%s' for guild '%s': %s",
                        gpt_channel.name,
                        guild.name,
                        cleanup_exc,
                    )

                # Post the new menu message
                if image_file:
                    sent_message = await gpt_channel.send(
                        embed=embed, view=self.sos_menu_view, file=image_file
                    )
                else:
                    sent_message = await gpt_channel.send(
                        embed=embed, view=self.sos_menu_view
                    )

                # Store new message ID
                try:
                    await server_listing.update_one(
                        {"discord_server_id": guild.id},
                        {"$set": {"menu_message_id": int(sent_message.id)}},
                        upsert=True,
                    )
                    logging.info(
                        "Stored menu_message_id for guild '%s': %s",
                        guild.name,
                        sent_message.id,
                    )
                except Exception as update_exc:
                    logging.warning(
                        "Failed to store menu_message_id for guild '%s': %s",
                        guild.name,
                        update_exc,
                    )
                logging.info(
                    "Sent new SOS menu to guild '%s' in channel '%s'.",
                    guild.name,
                    gpt_channel.name,
                )
            except discord.Forbidden:
                logging.error(
                    "Bot is forbidden from sending/editing messages in channel '%s' (%s) "
                    "in guild '%s'.",
                    gpt_channel.name,
                    gpt_channel.id,
                    guild.name,
                )
            except Exception as send_exc:
                logging.error(
                    "Error upserting SOS menu message in guild '%s': %s",
                    guild.name,
                    send_exc,
                    exc_info=True,
                )

        except Exception as unexpected_exc:
            logging.error(
                "Unexpected error while preparing to send SOS menu to guild '%s': %s",
                guild.name,
                unexpected_exc,
                exc_info=True,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MenuViewCog(bot))

