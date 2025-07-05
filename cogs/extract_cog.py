import discord
from discord.ext import commands
import logging
import asyncio
from PIL import Image
from io import BytesIO
import numpy as np
import traceback

from .extract_helpers import (
    prevent_discord_formatting,
    highlight_zero_values,
    validate_stat,
    clean_for_match,
    build_single_embed,
    build_monitor_embed,
)
from database import (
    get_registered_users,
    insert_player_data,
    find_best_match,
    get_registered_user_by_discord_id,
    get_clan_name_by_discord_server_id,
    get_server_listing_by_id
)
from config import (
    ALLOWED_EXTENSIONS, MATCH_SCORE_THRESHOLD
)
from ocr_processing import process_for_ocr, clean_ocr_result
from boundary_drawing import define_regions

logger = logging.getLogger(__name__)

# --- Shared Data & Views ---
class SharedData:
    def __init__(
        self, players_data, submitter_player_name, registered_users, monitor_channel_id,
        screenshot_bytes=None, screenshot_filename=None
    ):
        self.players_data = players_data
        self.submitter_player_name = submitter_player_name
        self.registered_users = registered_users
        self.monitor_channel_id = monitor_channel_id
        self.selected_player_index = None
        self.selected_field = None
        self.message = None
        self.view = None
        self.screenshot_bytes = screenshot_bytes
        self.screenshot_filename = screenshot_filename

class ConfirmationView(discord.ui.View):
    def __init__(self, shared_data, bot):
        super().__init__(timeout=None)
        self.shared_data = shared_data
        self.bot = bot

    @discord.ui.button(label="YES", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
            if any(highlight_zero_values(p) for p in self.shared_data.players_data):
                await interaction.followup.send(
                    "Some values are zero or missing. Please EDIT them before confirming.",
                    ephemeral=True
                )
                return
            await insert_player_data(self.shared_data.players_data, self.shared_data.submitter_player_name)
            monitor_embed = build_monitor_embed(
                self.shared_data.players_data, self.shared_data.submitter_player_name
            )
            file_to_send = None
            if self.shared_data.screenshot_bytes and self.shared_data.screenshot_filename:
                file_to_send = discord.File(BytesIO(self.shared_data.screenshot_bytes), filename=self.shared_data.screenshot_filename)
            monitor_channel = self.bot.get_channel(self.shared_data.monitor_channel_id)
            if monitor_channel:
                await monitor_channel.send(embed=monitor_embed)
            else:
                logger.error("Monitor channel not found or invalid ID in DB.")
            await self.shared_data.message.edit(
                content="Data confirmed and saved successfully!",
                embeds=[],
                view=None
            )
        except Exception as e:
            logger.error(f"Error in YES button callback: {e}")
            await interaction.followup.send("Error while confirming data.", ephemeral=True)

    @discord.ui.button(label="EDIT", style=discord.ButtonStyle.primary)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.edit_player_selection(interaction)

    async def edit_player_selection(self, interaction: discord.Interaction):
        try:
            options = []
            for i, player in enumerate(self.shared_data.players_data):
                p_name = player.get('player_name', 'Unknown') or "Unknown"
                options.append(
                    discord.SelectOption(
                        label=f"Player {i + 1}",
                        description=p_name,
                        value=str(i)
                    )
                )
            player_select = PlayerSelect(options, self.shared_data, self.bot)
            view = discord.ui.View()
            view.add_item(player_select)
            await interaction.response.edit_message(
                content="Choose a player to edit:",
                embeds=[],
                view=view
            )
        except Exception as e:
            logger.error(f"Error in edit_player_selection: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("An error occurred while editing.", ephemeral=True)

class PlayerSelect(discord.ui.Select):
    def __init__(self, options, shared_data, bot):
        super().__init__(placeholder="Select a player to edit", options=options)
        self.shared_data = shared_data
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        try:
            self.shared_data.selected_player_index = int(self.values[0])
            fields = ['player_name', 'Kills', 'Accuracy', 'Shots Fired', 'Shots Hit', 'Deaths', 'Melee Kills']
            field_options = [discord.SelectOption(label=f) for f in fields]
            field_select = FieldSelect(field_options, self.shared_data, self.bot)
            view = discord.ui.View()
            view.add_item(field_select)
            await interaction.response.edit_message(
                content=(
                    f"Player {self.shared_data.selected_player_index + 1} selected. "
                    "Now select the field you want to edit:"
                ),
                embeds=[],
                view=view
            )
        except Exception as e:
            logger.error(f"Error in PlayerSelect callback: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("An error occurred. Please try again.", ephemeral=True)

class FieldSelect(discord.ui.Select):
    def __init__(self, options, shared_data, bot):
        super().__init__(placeholder="Select a field to edit", options=options)
        self.shared_data = shared_data
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        try:
            selected_field = self.values[0]
            self.shared_data.selected_field = selected_field
            await interaction.response.edit_message(
                content=(
                    f"Enter the new value for {selected_field} "
                    f"(Player {self.shared_data.selected_player_index + 1}):"
                ),
                embeds=[],
                view=None
            )
            def check(m: discord.Message):
                return m.author == interaction.user and m.channel == interaction.channel
            try:
                msg = await self.bot.wait_for('message', check=check, timeout=60.0)
                await msg.delete()
                new_value_str = msg.content.strip()
                try:
                    new_value = validate_stat(selected_field, new_value_str)
                except ValueError:
                    await interaction.followup.send(
                        f"Invalid input for {selected_field}. Must be numeric or 'N/A' or like '75.3%'.",
                        ephemeral=True
                    )
                    return
                player = self.shared_data.players_data[self.shared_data.selected_player_index]
                if selected_field == 'player_name':
                    cleaned_ocr_name = clean_ocr_result(new_value_str, 'Name')
                    if not cleaned_ocr_name:
                        player['player_name'] = None
                        player['discord_id'] = None
                        player['discord_server_id'] = None
                        player['clan_name'] = "N/A"
                    else:
                        registered_users = await get_registered_users()
                        db_names = [u["player_name"] for u in registered_users]
                        ocr_name_clean = clean_for_match(cleaned_ocr_name)
                        db_names_clean = [clean_for_match(n) for n in db_names]
                        best_match_cleaned, match_score = find_best_match(
                            ocr_name_clean,
                            db_names_clean,
                            threshold=MATCH_SCORE_THRESHOLD
                        )
                        if best_match_cleaned and match_score >= MATCH_SCORE_THRESHOLD:
                            idx = db_names_clean.index(best_match_cleaned)
                            matched_user = registered_users[idx]
                            player['player_name'] = matched_user["player_name"]
                            player['discord_id'] = matched_user.get("discord_id")
                            player['discord_server_id'] = matched_user.get("discord_server_id")
                            if matched_user.get("discord_server_id"):
                                clan_name = await get_clan_name_by_discord_server_id(matched_user["discord_server_id"])
                                player['clan_name'] = clan_name
                            else:
                                player['clan_name'] = "N/A"
                        else:
                            player['player_name'] = None
                            player['discord_id'] = None
                            player['discord_server_id'] = None
                            player['clan_name'] = "N/A"
                else:
                    player[selected_field] = new_value
                updated_embed = build_single_embed(
                    self.shared_data.players_data,
                    self.shared_data.submitter_player_name
                )
                await self.shared_data.message.edit(
                    content="**Updated Data:** Please confirm the updated data.",
                    embeds=[updated_embed],
                    view=ConfirmationView(self.shared_data, self.bot)
                )
            except asyncio.TimeoutError:
                await interaction.followup.send("You took too long to respond. Please try again.", ephemeral=True)
            except Exception as e:
                logger.error(f"Error during data input: {e}")
                await interaction.followup.send("Something went wrong. Please try again.", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in FieldSelect callback: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("An error occurred. Please try again.", ephemeral=True)

class ExtractCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def submit_stats_button_flow(self, interaction: discord.Interaction):
        """Main entrypoint after pressing the SUBMIT STATS button."""
        if not interaction.guild_id:
            await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)
            return

        server_data = await get_server_listing_by_id(interaction.guild_id)
        if not server_data:
            await interaction.response.send_message(
                "Server is not configured. Contact an admin.",
                ephemeral=True
            )
            return
        gpt_stat_access_role_id = server_data.get("gpt_stat_access_role_id")
        monitor_channel_id = server_data.get("monitor_channel_id")
        if not gpt_stat_access_role_id or not monitor_channel_id:
            await interaction.response.send_message(
                "Server is missing required IDs (role or channel) in the database. Contact an admin.",
                ephemeral=True
            )
            return

        role_ids = [r.id for r in getattr(interaction.user, "roles", [])]
        if gpt_stat_access_role_id not in role_ids:
            await interaction.response.send_message(
                "You do not have permission to use this feature (missing GPT STAT ACCESS role).",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "Please upload your mission screenshot image **as a reply in this channel** within 60 seconds.",
            ephemeral=True
        )

        def check(msg):
            return (
                msg.author == interaction.user
                and msg.channel == interaction.channel
                and msg.attachments
                and any(msg.attachments[0].filename.lower().endswith(ext) for ext in ALLOWED_EXTENSIONS)
            )

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=60.0)
            image = msg.attachments[0]
            img_bytes = await image.read()
            img_pil = Image.open(BytesIO(img_bytes))
            img_cv = np.array(img_pil)
            regions = define_regions(img_cv.shape)

            await interaction.followup.send(
                content="Here is the submitted image for stats extraction:",
                file=discord.File(BytesIO(img_bytes), filename=image.filename),
                ephemeral=True
            )

            players_data = await asyncio.to_thread(process_for_ocr, img_cv, regions)
            players_data = [
                p for p in players_data
                if p.get('player_name') and str(p.get('player_name')).strip() not in ["", "0", ".", "a"]
            ]
            if len(players_data) < 2:
                await interaction.followup.send("At least 2 players with valid names must be present in the image.", ephemeral=True)
                return
            registered_users = await get_registered_users()
            for player in players_data:
                ocr_name = player.get('player_name')
                if ocr_name:
                    cleaned_ocr = clean_ocr_result(ocr_name, 'Name')
                    db_names = [u["player_name"] for u in registered_users]
                    ocr_name_clean = clean_for_match(cleaned_ocr)
                    db_names_clean = [clean_for_match(n) for n in db_names]
                    best_match_cleaned, match_score = find_best_match(
                        ocr_name_clean,
                        db_names_clean,
                        threshold=MATCH_SCORE_THRESHOLD
                    )
                    if best_match_cleaned and match_score is not None and match_score >= MATCH_SCORE_THRESHOLD:
                        idx = db_names_clean.index(best_match_cleaned)
                        matched_user = registered_users[idx]
                        player['player_name'] = matched_user["player_name"]
                        player['discord_id'] = matched_user.get("discord_id")
                        player['discord_server_id'] = matched_user.get("discord_server_id")
                        if matched_user.get("discord_server_id"):
                            clan_name = await get_clan_name_by_discord_server_id(matched_user["discord_server_id"])
                            player['clan_name'] = clan_name
                        else:
                            player['clan_name'] = "N/A"
                    else:
                        player['player_name'] = None
                        player['discord_id'] = None
                        player['discord_server_id'] = None
                        player['clan_name'] = "N/A"
                else:
                    player['player_name'] = None
                    player['discord_id'] = None
                    player['discord_server_id'] = None
                    player['clan_name'] = "N/A"
            players_data = [p for p in players_data if p.get('player_name')]
            if len(players_data) < 2:
                await interaction.followup.send(
                    "At least 2 registered players must be detected in the image. "
                    "All reported players must be registered in the database.",
                    ephemeral=True
                )
                return
            submitter_user = await get_registered_user_by_discord_id(interaction.user.id)
            submitter_player_name = submitter_user.get('player_name', 'Unknown') if submitter_user else 'Unknown'

            single_embed = build_single_embed(players_data, submitter_player_name)
            shared_data = SharedData(
                players_data,
                submitter_player_name,
                registered_users,
                monitor_channel_id,
                screenshot_bytes=img_bytes,
                screenshot_filename=image.filename
            )
            view = ConfirmationView(shared_data, self.bot)
            shared_data.view = view
            message = await interaction.followup.send(
                content="**Extracted Data:** Please confirm the extracted data.",
                embeds=[single_embed],
                view=view,
                ephemeral=True
            )
            shared_data.message = message

        except asyncio.TimeoutError:
            await interaction.followup.send("Timed out waiting for an image. Please try again.", ephemeral=True)
        except Exception as e:
            logger.error(f"Error processing image: {e}")
            traceback_str = ''.join(traceback.format_tb(e.__traceback__))
            logger.error(f"Traceback: {traceback_str}")
            await interaction.followup.send("An error occurred while processing the image.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(ExtractCog(bot))
