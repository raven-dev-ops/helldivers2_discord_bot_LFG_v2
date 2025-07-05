# cogs/menu_view_cog.py

import discord
from discord.ext import commands
import logging
# Removed database and utils imports as per your correction
# from database import get_mongo_client
# from utils import log_to_monitor_channel
import os # Import os for path joining

# Map each clan name to the ID of the guild where we store the invite link
CLAN_SERVER_IDS = {
    "Guardians of Freedom": 1172948128509468742,
    "Heck Snorkelers": 1221490168670715936,
    "Galactic Phantom Taskforce": 1214787549655203862,
}

# Define the path to the image file relative to where the bot is run (e.g., main.py location)
IMAGE_PATH = "gpt_network.png"


class SOSMenuView(discord.ui.View):
    """
    A persistent view providing buttons for SOS-related actions.
    """
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot
        # Ensure the bot has the required intents to see interactions for these buttons
        # e.g., discord.Intents.all() or specific intents like discord.Intents.interactions

    # Button callbacks remain as you provided them in the base code
    @discord.ui.button(label="CALL SOS", style=discord.ButtonStyle.danger, custom_id="launch_sos_button", disabled=False)
    async def launch_sos_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        sos_cog = self.bot.get_cog("SOSCog")
        if sos_cog:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            try:
                await sos_cog.launch_sos(interaction)
            except Exception as e:
                await interaction.followup.send(
                    "An error occurred while launching SOS. Please try again later.",
                    ephemeral=True
                )
                logging.error(f"Error in launch_sos_button: {e}")
        else:
            await interaction.response.send_message(
                "The SOS system is not available at the moment. Please try again later.",
                ephemeral=True
            )

    @discord.ui.button(label="MAKE LFG", style=discord.ButtonStyle.success, custom_id="create_mission_button")
    async def create_mission_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        sos_view_cog = self.bot.get_cog("SOSViewCog")
        if sos_view_cog:
            await interaction.response.defer(ephemeral=True)
            try:
                view = sos_view_cog.get_sos_view()
                await interaction.followup.send(
                    "Let's start creating your SOS mission. Please select your options below:",
                    view=view,
                    ephemeral=True
                )
            except Exception as e:
                await interaction.followup.send(
                    "An error occurred while creating the mission. Please try again later.",
                    ephemeral=True
                )
                logging.error(f"Error in create_mission_button: {e}")
        else:
            await interaction.response.send_message(
                "The mission creation system is not available at the moment. Please try again later.",
                ephemeral=True
            )

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
            await interaction.response.send_message(
                "The registration system is not available at the moment. Please try again later.",
                ephemeral=True
            )

    @discord.ui.button(
        label="SUBMIT STATS", 
        style=discord.ButtonStyle.primary,
        custom_id="submit_stats_button"
    )
    async def submit_stats_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        extract_cog = self.bot.get_cog("ExtractCog")
        if extract_cog:
            await extract_cog.submit_stats_button_flow(interaction)
        else:
            await interaction.response.send_message(
                "The stats submission system is not available at the moment. Please try again later.",
                ephemeral=True
            )

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

    # Keeping on_ready listener as you had it
    @commands.Cog.listener()
    async def on_ready(self):
        logging.info("MenuViewCog is ready.")
        # You can add logic here to send the menu to specific guilds on startup if desired.
        # Example:
        for guild in self.bot.guilds:
            await self.send_sos_menu_to_guild(guild) # Caution: sends every startup


    async def send_sos_menu_to_guild(self, guild: discord.Guild):
        """
        Sends the SOS menu with instructions to a specific guild's designated GPT channel.
        Each clan name links to that clan's server invite link (retrieved from MongoDB).
        Includes an embedded image.
        """
        # Assuming the bot object already has a mongo_db attribute from your main bot setup
        # If not, this will raise an AttributeError when accessing self.bot.mongo_db

        try:
            # Access the Server_Listing collection from the bot's mongo_db attribute
            server_listing = self.bot.mongo_db["Server_Listing"]
            server_data = await server_listing.find_one({"discord_server_id": guild.id})

            if not server_data:
                logging.warning(f"No server data found for guild '{guild.name}'. Skipping sending SOS menu.")
                return

            # 1) Find the GPT channel for the current guild
            gpt_channel_id = server_data.get("gpt_channel_id")
            if not gpt_channel_id:
                logging.warning(f"Server data for '{guild.name}' does not contain 'gpt_channel_id'. Cannot send SOS menu.")
                return

            gpt_channel = guild.get_channel(gpt_channel_id)
            if not gpt_channel:
                logging.warning(f"GPT channel (ID: {gpt_channel_id}) not found in guild '{guild.name}'. Cannot send SOS menu.")
                return

            # 2) For each clan, retrieve the invite link from the corresponding server in MongoDB
            alliance_link_chunks = []
            for clan_name, clan_server_id in CLAN_SERVER_IDS.items():
                # Access the Server_Listing collection again for each clan server
                clan_server_data = await server_listing.find_one({"discord_server_id": clan_server_id})
                invite_link = "https://discord.gg/unknown" # Default placeholder
                if clan_server_data and "discord_invite_link" in clan_server_data:
                    # Use the clan's actual invite link
                    invite_link = clan_server_data["discord_invite_link"]
                else:
                    logging.warning(f"No server data or invite link found in DB for clan '{clan_name}' (Server ID: {clan_server_id}). Using placeholder link.")


                # Build a clickable link for this clan
                alliance_link_chunks.append(f"[{clan_name}]({invite_link})")

            # Combine them into one Markdown string, e.g.:  [Kai's](...) | [Guardians](...) | ...
            alliance_links_md = " | ".join(alliance_link_chunks)

            # 3) Build the embed description
            embed_description = (
                f"**{alliance_links_md}**\n\n"
                "**Instructions:**\n"
                "- **LAUNCH SOS**: Quickly send an SOS for any mission (touchscreens).\n\n"
                "- **CREATE MISSION**: Customize your SOS mission by selecting various options "
                "(Enemy Type, Difficulty, Play Style, Voice Comms, and Notes).\n\n"
                "- **REGISTRATION**: Register your Helldivers 2 player name in your allied server to claim your clan.\n\n"
                "**Notes:** Created voice channels/SOS embeds will expire after **60 seconds** of inactivity.\n\n"
                "Click the invite link to join the SOS voice channel!\n\n"
                "*Please choose an option below:*"
            )

            embed = discord.Embed(
                title="Welcome to the GPT LFG Network!",
                description=embed_description,
                color=discord.Color.blue()
            )

            # >>> Start of image embedding logic <<<
            file = None
            try:
                 file = discord.File("./gpt_network.png", filename="gpt_network.png")
                 embed.set_image(url="attachment://gpt_network.png")
                 logging.debug(f"Image './gpt_network.png' prepared for embed.")
            except FileNotFoundError:
                 logging.warning(f"Image file not found at path: ./gpt_network.png. Cannot embed image.")
                 else:
                      logging.warning(f"Image file not found at path: {IMAGE_PATH}. Cannot embed image.")
            except Exception as e:
                 logging.error(f"Error preparing image file '{IMAGE_PATH}' for embed: {e}", exc_info=True)
                 file = None # Ensure file is None if an error occurred

            # >>> End of image embedding logic <<<


            # 4) Send the embed, attach the file (if prepared), and attach our persistent view
            # Pass the file= argument ONLY if the file object was successfully created
            try:
                 if file:
                      # Attempt to send the message with the file
                      sent_message = await gpt_channel.send(embed=embed, view=self.sos_menu_view, file=file)
                      logging.info(f"SOS menu sent with image to guild '{guild.name}' in channel '{gpt_channel.name}'.")
                 else:
                      # Send without the file if it wasn't found or prepared
                      sent_message = await gpt_channel.send(embed=embed, view=self.sos_menu_view)
                      logging.info(f"SOS menu sent without image to guild '{guild.name}' in channel '{gpt_channel.name}'.")

                 # You might want to store sent_message.id and sent_message.channel.id here if you plan to edit/delete the message later

            except discord.Forbidden:
                 logging.error(f"Bot is forbidden from sending messages (or messages with files) to channel '{gpt_channel.name}' ({gpt_channel.id}) in guild '{guild.name}'. Check channel permissions.")
            except Exception as e:
                 logging.error(f"Error sending SOS menu message to guild '{guild.name}': {e}", exc_info=True)


        except Exception as e:
            # Catch errors from DB access or initial channel finding
            logging.error(f"An unexpected error occurred while preparing to send SOS menu to guild '{guild.name}': {e}", exc_info=True)


async def setup(bot: commands.Bot):
    # Assuming the bot object already has a mongo_db attribute from your main bot setup
    # If not, this cog might fail later when calling send_sos_menu_to_guild
    # No explicit check here, assuming bot.mongo_db will be available.

    await bot.add_cog(MenuViewCog(bot))