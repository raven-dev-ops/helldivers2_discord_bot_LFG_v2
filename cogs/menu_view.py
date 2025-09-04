# cogs/menu_view_cog.py

import discord
from discord.ext import commands
import logging
import os

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
        label="SUBMIT STATS",
        style=discord.ButtonStyle.primary,
        custom_id="submit_stats_button"
    )
    async def submit_stats_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        extract_cog = self.bot.get_cog("ExtractCog")
        if extract_cog:
            await extract_cog.submit_stats_button_flow(interaction)
        else:
            logging.error("ExtractCog not found when pressing SUBMIT STATS. Ensure 'cogs.extract_cog' loaded correctly.")
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
                #"- **CALL SOS**: Quickly send an SOS for any missions. (touchscreens)\n\n"
                #"- **MAKE LFG**: Customize your SOS mission by selecting various options"
                #"(Enemy Type, Difficulty, Play Style, Voice Comms, Details).\n\n"
                "- **REGISTER**: Register your Helldivers 2 player name.\n\n"
                "- **REPORT STATS**: Submit your screenshots for mission stats to the database.\n\n"
                "\n"
                "*Please select an option below:*"
            )

            embed = discord.Embed(
                title="GPTFLEET HD2 CLAN MENU",
                description=embed_description,
                color=discord.Color.blue()
            )

            file = None
            try:
                if os.path.exists(IMAGE_PATH):
                    file = discord.File(IMAGE_PATH, filename="gpt_network.png")
                    embed.set_image(url="attachment://gpt_network.png")
                    logging.debug(f"Image '{IMAGE_PATH}' prepared for embed as image.")
                else:
                    logging.warning(f"Image file not found at path: {IMAGE_PATH}. Cannot embed image.")
            except Exception as e:
                logging.error(f"Error preparing image file '{IMAGE_PATH}' for embed: {e}", exc_info=True)
                file = None

            # Send the embed with persistent view and image (if available)
            try:
                logging.info(f"Attempting to send menu to channel: {gpt_channel} in guild {guild.name}")

                if file:
                    await gpt_channel.send(embed=embed, view=self.sos_menu_view, file=file)
                else:
                    await gpt_channel.send(embed=embed, view=self.sos_menu_view)
                logging.info(f"SOS menu sent to guild '{guild.name}' in channel '{gpt_channel.name}'.")
            except discord.Forbidden:
                logging.error(f"Bot is forbidden from sending messages to channel '{gpt_channel.name}' ({gpt_channel.id}) in guild '{guild.name}'. Check channel permissions.")
            except Exception as e:
                logging.error(f"Error sending SOS menu message to guild '{guild.name}': {e}", exc_info=True)

        except Exception as e:
            logging.error(f"An unexpected error occurred while preparing to send SOS menu to guild '{guild.name}': {e}", exc_info=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(MenuViewCog(bot))