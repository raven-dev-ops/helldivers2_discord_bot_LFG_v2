import discord
from discord.ext import commands
import logging
import asyncio
from PIL import Image
from io import BytesIO
import numpy as np
import traceback

from .extract_helpers import (
    highlight_zero_values,
    validate_stat,
    clean_for_match,
    build_single_embed,
    build_monitor_embed,
)
from database import (
    get_registered_users,
    insert_player_data,
    count_user_missions,
    find_best_match,
    get_registered_user_by_discord_id,
    get_clan_name_by_discord_server_id,
    get_server_listing_by_id,
    upsert_registered_user
)
from config import (
    ALLOWED_EXTENSIONS,
    MATCH_SCORE_THRESHOLD,
    class_a_role_id,
    class_b_role_id,
)
from ocr_processing import process_for_ocr, clean_ocr_result
from boundary_drawing import define_regions, draw_boundaries
import cv2

logger = logging.getLogger(__name__)


async def maybe_promote(bot: commands.Bot, player: dict):
    """Grant Class A role if the player has 3 or more missions."""
    try:
        discord_id = player.get("discord_id")
        guild_id = player.get("discord_server_id")
        if not discord_id or not guild_id:
            return
        guild = bot.get_guild(int(guild_id))
        if not guild:
            return
        member = guild.get_member(int(discord_id))
        if not member:
            try:
                member = await guild.fetch_member(int(discord_id))
            except Exception:
                return
        if any(r.id == class_a_role_id for r in member.roles):
            return
        completed = await count_user_missions(int(discord_id))
        if completed >= 3:
            role = guild.get_role(class_a_role_id)
            if role:
                await member.add_roles(role, reason="Completed 3 missions")
    except Exception as e:
        logger.error(f"Error during promotion check: {e}")

# --- Shared Data & Views ---
class SharedData:
    def __init__(
        self, players_data, submitter_player_name, registered_users, monitor_channel_id,
        screenshot_bytes=None, screenshot_filename=None, missing_players=None
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
        self.missing_players = missing_players or []

class ConfirmationView(discord.ui.View):
    def __init__(self, shared_data, bot):
        super().__init__(timeout=None)
        self.shared_data = shared_data
        self.bot = bot

    @discord.ui.button(label="YES", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
            # Prevent saving an empty mission; require at least one registered player
            if not self.shared_data.players_data:
                await interaction.followup.send(
                    "Please register at least one player before saving.",
                    ephemeral=True
                )
                return
            # Recalculate Accuracy from Shots before saving; allow zeros
            for p in self.shared_data.players_data:
                try:
                    sf = int(float(p.get('Shots Fired', 0)) or 0)
                except Exception:
                    sf = 0
                try:
                    sh = int(float(p.get('Shots Hit', 0)) or 0)
                except Exception:
                    sh = 0
                if sh > sf:
                    sh = sf
                acc = (sh / sf * 100) if sf > 0 else 0
                p['Shots Fired'] = sf
                p['Shots Hit'] = sh
                p['Accuracy'] = f"{min(acc, 100.0):.1f}%"

            mission_id = await insert_player_data(self.shared_data.players_data, self.shared_data.submitter_player_name)
            for player in self.shared_data.players_data:
                await maybe_promote(self.bot, player)
            leaderboard_cog = self.bot.get_cog("LeaderboardCog")
            if leaderboard_cog:
                asyncio.create_task(leaderboard_cog._run_leaderboard_update(force=True))

            # Include submitter's ship on the monitor embed
            submitter_user = await get_registered_user_by_discord_id(interaction.user.id)
            submitter_ship = submitter_user.get('ship_name') if submitter_user else None
            monitor_embed = build_monitor_embed(
                self.shared_data.players_data,
                self.shared_data.submitter_player_name,
                mission_id=mission_id,
                submitter_ship=submitter_ship
            )
            annotated_file = None
            if self.shared_data.screenshot_bytes and self.shared_data.screenshot_filename:
                try:
                    pil = Image.open(BytesIO(self.shared_data.screenshot_bytes)).convert('RGB')
                    img_cv = np.array(pil)
                    regions = define_regions(img_cv.shape)
                    img_bgr = cv2.cvtColor(img_cv, cv2.COLOR_RGB2BGR)
                    annotated = draw_boundaries(img_bgr.copy(), regions)
                    ok, buf = cv2.imencode('.png', annotated)
                    if ok:
                        annotated_file = discord.File(BytesIO(bytearray(buf)), filename=f"ocr_regions_{self.shared_data.screenshot_filename.rsplit('.',1)[0]}.png")
                except Exception as e:
                    logger.warning(f"Failed to annotate OCR regions for monitor image: {e}")
            monitor_channel = self.bot.get_channel(self.shared_data.monitor_channel_id)
            if monitor_channel:
                if annotated_file:
                    await monitor_channel.send(embed=monitor_embed, file=annotated_file)
                else:
                    await monitor_channel.send(embed=monitor_embed)
            else:
                logger.error("Monitor channel not found or invalid ID in DB.")
            await self.shared_data.message.edit(
                content=f"Data confirmed and saved successfully! Mission #{mission_id:07d}.",
                embeds=[],
                view=None
            )
        except Exception as e:
            logger.error(f"Error in YES button callback: {e}")
            await interaction.followup.send("Error while confirming data.", ephemeral=True)

    @discord.ui.button(label="EDIT", style=discord.ButtonStyle.primary)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.edit_player_selection(interaction)

    @discord.ui.button(label="SHOW REGIONS", style=discord.ButtonStyle.secondary)
    async def show_regions(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            if not (self.shared_data.screenshot_bytes and self.shared_data.screenshot_filename):
                await interaction.followup.send("No screenshot available for annotation.", ephemeral=True)
                return
            try:
                pil = Image.open(BytesIO(self.shared_data.screenshot_bytes)).convert('RGB')
                img_cv = np.array(pil)
                regions = define_regions(img_cv.shape)
                img_bgr = cv2.cvtColor(img_cv, cv2.COLOR_RGB2BGR)
                annotated = draw_boundaries(img_bgr.copy(), regions)
                ok, buf = cv2.imencode('.png', annotated)
                if ok:
                    file = discord.File(
                        BytesIO(bytearray(buf)),
                        filename=f"ocr_regions_{self.shared_data.screenshot_filename.rsplit('.',1)[0]}.png"
                    )
                    await interaction.followup.send("OCR regions overlay:", file=file, ephemeral=True)
                else:
                    await interaction.followup.send("Failed to render annotated image.", ephemeral=True)
            except Exception as e:
                logger.warning(f"Failed to generate OCR regions overlay on request: {e}")
                await interaction.followup.send("Unable to generate overlay.", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in SHOW REGIONS button: {e}")
            try:
                await interaction.followup.send("Error showing regions.", ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(label="REGISTER MISSING", style=discord.ButtonStyle.danger)
    async def register_missing(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            missing = self.shared_data.missing_players or []
            if not missing:
                # No detected missing players — still allow manual/guild/voice registration
                voice_channel = getattr(getattr(interaction.user, 'voice', None), 'channel', None)
                members = []
                if voice_channel and isinstance(voice_channel, discord.VoiceChannel):
                    members = [m for m in voice_channel.members if not m.bot and m.id != interaction.user.id]
                if members:
                    view = MemberPickView(self.shared_data, self.bot, interaction.guild_id, None, "", members, title="Pick a voice member")
                    await interaction.response.send_message(
                        "Pick a voice member to pre-fill Discord ID, or press Manual Entry:",
                        view=view,
                        ephemeral=True
                    )
                    return
                # Fallback to manual entry (and the modal allows typing any Discord ID)
                modal = RegisterPlayerModal(self.shared_data, self.bot, interaction.guild_id, None, "")
                await interaction.response.send_modal(modal)
            else:
                view = RegisterMissingView(self.shared_data, self.bot, interaction.guild_id)
                await interaction.response.send_message("Select a missing player to register:", view=view, ephemeral=True)
        except Exception as e:
            logger.error(f"Error opening Register Missing flow: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("Unable to open registration flow.", ephemeral=True)

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

    

class RegisterMissingView(discord.ui.View):
    def __init__(self, shared_data: SharedData, bot: commands.Bot, guild_id: int):
        super().__init__(timeout=120)
        self.shared_data = shared_data
        self.bot = bot
        self.guild_id = guild_id
        options = []
        for idx, p in enumerate(self.shared_data.missing_players):
            label = p.get('unregistered_name', f"Missing {idx+1}") or f"Missing {idx+1}"
            options.append(discord.SelectOption(label=label[:100], value=str(idx)))
        self.add_item(RegisterMissingSelect(options, self))

class RegisterMissingSelect(discord.ui.Select):
    def __init__(self, options, parent: RegisterMissingView):
        super().__init__(placeholder="Choose a player to register", options=options, min_values=1, max_values=1)
        self.parent = parent

    async def callback(self, interaction: discord.Interaction):
        try:
            sel = int(self.values[0])
            missing = self.parent.shared_data.missing_players
            if sel < 0 or sel >= len(missing):
                await interaction.response.send_message("Invalid selection.", ephemeral=True)
                return
            default_name = missing[sel].get('unregistered_name', '') or ''
            # If the editor is in a voice channel, offer picking a member to auto-fill ID
            voice_channel = getattr(getattr(interaction.user, 'voice', None), 'channel', None)
            if voice_channel and isinstance(voice_channel, discord.VoiceChannel):
                members = [m for m in voice_channel.members if not m.bot and m.id != interaction.user.id]
                if members:
                    view = MemberPickView(self.parent.shared_data, self.parent.bot, self.parent.guild_id, sel, default_name, members, title="Pick a voice member")
                    await interaction.response.send_message("Pick a voice member to pre-fill Discord ID, or press Manual Entry:", view=view, ephemeral=True)
                    return
            # Fallback: suggest from entire guild based on OCR name similarity
            try:
                guild = interaction.guild
                if guild is not None:
                    all_members = [m for m in guild.members if not m.bot and m.id != interaction.user.id]
                    key = clean_for_match(default_name)
                    if key:
                        filtered = []
                        for m in all_members:
                            n = (m.display_name or m.name or "")
                            if key in clean_for_match(n):
                                filtered.append(m)
                        candidates = filtered or all_members
                    else:
                        candidates = all_members
                    # Limit to 25 for select
                    candidates = candidates[:25]
                    if candidates:
                        view = MemberPickView(self.parent.shared_data, self.parent.bot, self.parent.guild_id, sel, default_name, candidates, title="Pick a guild member")
                        await interaction.response.send_message("Pick a guild member to pre-fill Discord ID, or press Manual Entry:", view=view, ephemeral=True)
                        return
            except Exception:
                pass
            # Fallback: open modal without suggestion
            modal = RegisterPlayerModal(self.parent.shared_data, self.parent.bot, self.parent.guild_id, sel, default_name)
            await interaction.response.send_modal(modal)
        except Exception as e:
            logger.error(f"Error in RegisterMissingSelect callback: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("Failed to open registration modal.", ephemeral=True)

class MemberPickView(discord.ui.View):
    def __init__(self, shared_data: SharedData, bot: commands.Bot, guild_id: int, missing_index: int, default_name: str, members: list[discord.Member], title: str = "Pick member"):
        super().__init__(timeout=120)
        self.shared_data = shared_data
        self.bot = bot
        self.guild_id = guild_id
        self.missing_index = missing_index
        self.default_name = default_name
        self.title = title
        # Build options from voice members
        options = []
        for m in members[:25]:
            label = (m.display_name or m.name or str(m.id))[:100]
            desc = f"{m.mention}"
            options.append(discord.SelectOption(label=label, description=desc[:100], value=str(m.id)))
        self.add_item(MemberSelect(options, self))

    @discord.ui.button(label="Manual Entry", style=discord.ButtonStyle.secondary)
    async def manual(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = RegisterPlayerModal(self.shared_data, self.bot, self.guild_id, self.missing_index, self.default_name)
        await interaction.response.send_modal(modal)

class MemberSelect(discord.ui.Select):
    def __init__(self, options, parent: MemberPickView):
        super().__init__(placeholder="Select a voice member", options=options, min_values=1, max_values=1)
        self.parent = parent

    async def callback(self, interaction: discord.Interaction):
        try:
            picked_id = int(self.values[0])
            modal = RegisterPlayerModal(self.parent.shared_data, self.parent.bot, self.parent.guild_id, self.parent.missing_index, self.parent.default_name, default_discord_id=picked_id)
            await interaction.response.send_modal(modal)
        except Exception as e:
            logger.error(f"Error in MemberSelect: {e}")
            await interaction.response.send_message("Failed to open modal.", ephemeral=True)

class RegisterPlayerModal(discord.ui.Modal, title="Register Player"):
    discord_id = discord.ui.TextInput(label="Discord ID (numbers)", placeholder="e.g. 123456789012345678", required=True, max_length=20)
    player_name = discord.ui.TextInput(label="Helldiver Name", placeholder="Exact in-game name", required=True, max_length=50)

    def __init__(self, shared_data: SharedData, bot: commands.Bot, guild_id: int, missing_index: int, default_name: str, default_discord_id: int | None = None):
        super().__init__()
        self.shared_data = shared_data
        self.bot = bot
        self.guild_id = guild_id
        self.missing_index = missing_index
        try:
            # Pre-fill name if available
            self.player_name.default = default_name
        except Exception:
            pass
        try:
            if default_discord_id is not None:
                self.discord_id.default = str(int(default_discord_id))
        except Exception:
            pass

    async def on_submit(self, interaction: discord.Interaction):
        try:
            try:
                did = int(str(self.discord_id.value).strip())
            except Exception:
                await interaction.response.send_message("Discord ID must be a number.", ephemeral=True)
                return
            name_val = str(self.player_name.value).strip()
            if not name_val:
                await interaction.response.send_message("Player name is required.", ephemeral=True)
                return
            ok = await upsert_registered_user(did, int(self.guild_id), name_val)
            if not ok:
                await interaction.response.send_message("Failed to register player in database.", ephemeral=True)
                return
            # Transform missing entry into a registered player row
            try:
                mp = self.shared_data.missing_players.pop(self.missing_index)
            except Exception:
                mp = {}
            stats_row = {
                'player_name': name_val,
                'discord_id': did,
                'discord_server_id': int(self.guild_id),
                'Kills': mp.get('Kills', 'N/A'),
                'Accuracy': mp.get('Accuracy', 'N/A'),
                'Shots Fired': mp.get('Shots Fired', 'N/A'),
                'Shots Hit': mp.get('Shots Hit', 'N/A'),
                'Deaths': mp.get('Deaths', 'N/A'),
                'Melee Kills': mp.get('Melee Kills', 'N/A'),
                'Stims Used': mp.get('Stims Used', 'N/A'),
                'Samples Extracted': mp.get('Samples Extracted', 'N/A'),
                'Stratagems Used': mp.get('Stratagems Used', 'N/A'),
                'clan_name': 'N/A',
            }
            try:
                clan = await get_clan_name_by_discord_server_id(self.guild_id)
                stats_row['clan_name'] = clan or 'N/A'
            except Exception:
                pass
            # Ensure key presence
            for k in ['Kills','Accuracy','Shots Fired','Shots Hit','Deaths','Melee Kills','Stims Used','Samples Extracted','Stratagems Used','clan_name']:
                stats_row.setdefault(k, 'N/A')
            self.shared_data.players_data.append(stats_row)
            # Rebuild confirmation embed
            embed = build_single_embed(self.shared_data.players_data, self.shared_data.submitter_player_name)
            try:
                await self.shared_data.message.edit(embeds=[embed], view=self.shared_data.view)
            except Exception:
                pass
            await interaction.response.send_message(f"Registered {name_val} and added to this mission.", ephemeral=True)
        except Exception as e:
            logger.error(f"Error registering missing player: {e}")
            try:
                await interaction.response.send_message("Registration failed.", ephemeral=True)
            except Exception:
                pass

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

            # UPDATED: Include the new fields so users can edit them
            fields = [
                'player_name',
                'Kills', 'Shots Fired', 'Shots Hit', 'Deaths', 'Melee Kills',
                'Stims Used', 'Samples Extracted', 'Stratagems Used'
            ]

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
        logger.info(
            f"submit_stats_button_flow invoked by user {interaction.user} (ID: {interaction.user.id}) in guild {getattr(interaction.guild, 'name', 'DM')} ({interaction.guild_id})"
        )
        if not interaction.guild_id:
            logger.warning("Attempted to submit stats in DM; disallowed.")
            await interaction.response.send_message("This command cannot be used in DMs.", ephemeral=True)
            return

        server_data = await get_server_listing_by_id(interaction.guild_id)
        if not server_data:
            logger.error(f"Server_Listing not found for guild_id {interaction.guild_id}.")
            await interaction.response.send_message(
                "Server is not configured. Contact an admin.",
                ephemeral=True
            )
            return

        monitor_channel_id = server_data.get("monitor_channel_id")
        if not monitor_channel_id:
            logger.error(
                f"Missing monitor_channel_id in Server_Listing for guild_id {interaction.guild_id}."
            )
            await interaction.response.send_message(
                "Server is missing required channel configuration in the database. Contact an admin.",
                ephemeral=True
            )
            return

        # Submission is allowed for Class B Citizens
        if class_b_role_id is None:
            logger.error("class_b_role_id is not configured.")
            await interaction.response.send_message(
                "Class B Citizen role is not configured. Contact an admin.",
                ephemeral=True
            )
            return

        role_ids = [r.id for r in getattr(interaction.user, "roles", [])]
        if class_b_role_id not in role_ids:
            logger.warning(
                f"User {interaction.user} (ID: {interaction.user.id}) missing Class B Citizen role ({class_b_role_id})."
            )
            await interaction.response.send_message(
                "You must be a Class B Citizen to submit stats.",
                ephemeral=True
            )
            return

        logger.info("Prompting user to upload screenshot...")
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
            logger.info(f"Received image '{image.filename}' ({image.size} bytes) from user {interaction.user.id}.")
            img_bytes = await image.read()
            # --- DELETE THE USER MESSAGE ASAP! ---
            try:
                await msg.delete()
            except discord.Forbidden:
                logger.warning(f"Failed to delete user's image message (no permission): {msg.id}")
            except Exception as e:
                logger.error(f"Failed to delete user's image message {msg.id}: {e}")

            img_pil = Image.open(BytesIO(img_bytes))
            img_cv = np.array(img_pil)
            regions = define_regions(img_cv.shape)
            logger.info("Starting OCR processing in background thread...")

            await interaction.followup.send(
                content="Here is the submitted image for stats extraction:",
                file=discord.File(BytesIO(img_bytes), filename=image.filename),
                ephemeral=True
            )

            players_data = await asyncio.to_thread(process_for_ocr, img_cv, regions)
            logger.info(f"OCR produced {len(players_data)} player entries before cleanup.")
            players_data = [
                p for p in players_data
                if p.get('player_name') and str(p.get('player_name')).strip() not in ["", "0", ".", "a"]
            ]
            logger.info(f"After initial filtering, {len(players_data)} player entries remain.")
            if len(players_data) < 1:
                # Provide a debug overlay with OCR regions to help adjust
                try:
                    img_bgr = cv2.cvtColor(img_cv, cv2.COLOR_RGB2BGR)
                    annotated = draw_boundaries(img_bgr.copy(), regions)
                    ok, buf = cv2.imencode('.png', annotated)
                    if ok:
                        await interaction.followup.send(
                            content="No players with valid names were detected. Showing OCR regions overlay for debugging.",
                            file=discord.File(BytesIO(bytearray(buf)), filename=f"ocr_regions_{image.filename.rsplit('.',1)[0]}.png"),
                            ephemeral=True
                        )
                except Exception as e:
                    logger.warning(f"Failed to annotate OCR regions for debug (no-name stage): {e}")
                await interaction.followup.send("No players with valid names were detected in the image.", ephemeral=True)
                return
            registered_users = await get_registered_users()
            logger.info(f"Loaded {len(registered_users)} registered users for matching.")
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
                        logger.info(f"No match for OCR name '{ocr_name}'. Marking as unregistered.")
                        # Preserve the OCR read for later registration
                        player['unregistered_name'] = cleaned_ocr or ocr_name
                        player['player_name'] = None
                        player['discord_id'] = None
                        player['discord_server_id'] = None
                        player['clan_name'] = "N/A"
                else:
                    player['player_name'] = None
                    player['discord_id'] = None
                    player['discord_server_id'] = None
                    player['clan_name'] = "N/A"
            missing_players = [p.copy() for p in players_data if not p.get('player_name') and p.get('unregistered_name')]
            players_data = [p for p in players_data if p.get('player_name')]
            logger.info(f"After matching against DB, {len(players_data)} registered players remain.")
            # Relaxed rule: accept as long as at least one registered player is present
            if len(players_data) < 1:
                # Generate debug overlay (to be attached to the same message as the registration view)
                annotated_file = None
                try:
                    img_bgr = cv2.cvtColor(img_cv, cv2.COLOR_RGB2BGR)
                    annotated = draw_boundaries(img_bgr.copy(), regions)
                    ok, buf = cv2.imencode('.png', annotated)
                    if ok:
                        annotated_file = discord.File(
                            BytesIO(bytearray(buf)),
                            filename=f"ocr_regions_{image.filename.rsplit('.',1)[0]}.png"
                        )
                except Exception as e:
                    logger.warning(f"Failed to annotate OCR regions for debug (registration stage): {e}")

                # Show a view that lets the user register missing players immediately
                try:
                    submitter_user = await get_registered_user_by_discord_id(interaction.user.id)
                    submitter_player_name = submitter_user.get('player_name', 'Unknown') if submitter_user else 'Unknown'
                except Exception:
                    submitter_player_name = 'Unknown'

                shared_data = SharedData(
                    players_data,
                    submitter_player_name,
                    registered_users,
                    monitor_channel_id,
                    screenshot_bytes=img_bytes,
                    screenshot_filename=image.filename,
                    missing_players=missing_players
                )
                view = ConfirmationView(shared_data, self.bot)
                shared_data.view = view
                # Build a simple embed listing missing players
                desc_lines = []
                for idx, mp in enumerate(missing_players, start=1):
                    nm = mp.get('unregistered_name', 'Unknown')
                    desc_lines.append(f"{idx}. {nm}")
                embed = discord.Embed(
                    title="Unregistered Players Detected",
                    description=("\n".join(desc_lines) or "No names found."),
                    color=discord.Color.orange()
                )
                embed.set_footer(text="Use REGISTER MISSING to add players, then press YES to save.")
                if annotated_file:
                    message = await interaction.followup.send(
                        content="No registered players were detected. You can register the missing players below.",
                        embed=embed,
                        view=view,
                        file=annotated_file,
                        ephemeral=True
                    )
                else:
                    message = await interaction.followup.send(
                        content="No registered players were detected. You can register the missing players below.",
                        embed=embed,
                        view=view,
                        ephemeral=True
                    )
                shared_data.message = message
                return

            submitter_user = await get_registered_user_by_discord_id(interaction.user.id)
            submitter_player_name = submitter_user.get('player_name', 'Unknown') if submitter_user else 'Unknown'
            logger.info(f"Submitter resolved as '{submitter_player_name}'.")

            # NEW: Normalize expected keys so UI/edit/validation is stable
            for p in players_data:
                p.setdefault('Kills', 'N/A')
                p.setdefault('Accuracy', 'N/A')
                p.setdefault('Shots Fired', 'N/A')
                p.setdefault('Shots Hit', 'N/A')
                p.setdefault('Deaths', 'N/A')
                p.setdefault('Melee Kills', 'N/A')
                p.setdefault('Stims Used', 'N/A')
                p.setdefault('Samples Extracted', 'N/A')
                p.setdefault('Stratagems Used', 'N/A')
                p.setdefault('clan_name', 'N/A')

            single_embed = build_single_embed(players_data, submitter_player_name)
            shared_data = SharedData(
                players_data,
                submitter_player_name,
                registered_users,
                monitor_channel_id,
                screenshot_bytes=img_bytes,
                screenshot_filename=image.filename,
                missing_players=missing_players
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
            logger.info("Presented extracted data for confirmation.")

        except asyncio.TimeoutError:
            logger.warning("Timed out waiting for image upload from user.")
            await interaction.followup.send("Timed out waiting for an image. Please try again.", ephemeral=True)
        except Exception as e:
            logger.error(f"Error processing image: {e}")
            traceback_str = ''.join(traceback.format_tb(e.__traceback__))
            logger.error(f"Traceback: {traceback_str}")
            await interaction.followup.send("An error occurred while processing the image.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(ExtractCog(bot))


