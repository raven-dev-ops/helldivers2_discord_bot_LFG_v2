import discord
from discord.ext import commands
from datetime import datetime
import logging
import asyncio

class RegisterModal(discord.ui.Modal, title="Register as a Helldiver"):
    """
    A modal for user registration.
    """
    helldiver_name = discord.ui.TextInput(
        label="Helldiver Name",
        placeholder="Enter your Helldiver Name...",
        required=True,
        max_length=100
    )

    def __init__(self, bot, interaction: discord.Interaction):
        super().__init__()
        self.bot = bot
        self.interaction = interaction
        # No additional role select; deprecated

    async def _add_role_select(self):
        # Deprecated: role selection has been removed.
        return

    async def on_submit(self, interaction: discord.Interaction):
        """
        Handle the modal submission.
        """
        try:
            # Collect user data
            discord_id = int(interaction.user.id)
            discord_server_id = int(interaction.guild.id)
            server_name = interaction.guild.name.strip()
            server_nickname = interaction.user.display_name.strip()
            player_name = self.helldiver_name.value.strip()
            logging.info(f"Registering user '{player_name}' (Discord ID: {discord_id}) in guild '{server_name}' ({discord_server_id}).")

            # Insert into the Alliance collection
            alliance_collection = self.bot.mongo_db['Alliance']
            filter_doc = {
                "discord_id": discord_id,
                "discord_server_id": discord_server_id,
            }
            update_doc = {
                "$set": {
                    "player_name": player_name,
                    "server_name": server_name,
                    "server_nickname": server_nickname,
                },
                "$setOnInsert": {"registered_at": datetime.utcnow()}
            }

            result = await alliance_collection.update_one(filter_doc, update_doc, upsert=True)
            if result.upserted_id is not None:
                logging.info(f"User '{player_name}' registered in Alliance collection via upsert.")
            else:
                logging.info(f"User '{player_name}' Alliance registration updated without creating a duplicate.")

            await interaction.response.send_message(
                f"Registration successful! Welcome, **{player_name}**!",
                ephemeral=True
            )  # Send this if no role was selected or role assignment failed
            logging.info(f"User {player_name} ({discord_id}) registered successfully.")

        except Exception as e:  # Catch errors during the initial registration process
            logging.error(f"Error during registration: {e}")
            await interaction.response.send_message(
                "An error occurred while registering. Please try again later.",
                ephemeral=True
            )

class RegisterModalCog(commands.Cog):
    """
    A cog to manage the RegisterModal.
    """
    def __init__(self, bot):
        self.bot = bot

    def get_register_modal(self, interaction: discord.Interaction):
        """
        Returns an instance of RegisterModal.
        """
        logging.info("Creating RegisterModal for user interaction.")
        return RegisterModal(self.bot, interaction)

    def get_register_ship_modal(self, interaction: discord.Interaction):
        logging.info("Creating RegisterShipModal for user interaction.")
        return RegisterShipModal(self.bot, interaction)

async def setup(bot):
    await bot.add_cog(RegisterModalCog(bot))


class RegisterShipModal(discord.ui.Modal, title="Register a Ship"):
    ship_name = discord.ui.TextInput(
        label="Ship Name",
        placeholder="Enter your ship name...",
        required=True,
        max_length=100
    )

    def __init__(self, bot, interaction: discord.Interaction):
        super().__init__()
        self.bot = bot
        self.interaction = interaction

    async def on_submit(self, interaction: discord.Interaction):
        try:
            discord_id = int(interaction.user.id)
            discord_server_id = int(interaction.guild.id)
            server_name = interaction.guild.name.strip()
            ship_name = self.ship_name.value.strip()
            logging.info(f"Registering ship '{ship_name}' for user {discord_id} in guild '{server_name}' ({discord_server_id}).")

            alliance_collection = self.bot.mongo_db['Alliance']
            filter_doc = {
                "discord_id": discord_id,
                "discord_server_id": discord_server_id,
            }
            update_doc = {
                "$set": {
                    "ship_name": ship_name,
                    "server_name": server_name,
                },
                "$setOnInsert": {"registered_at": datetime.utcnow()}
            }

            result = await alliance_collection.update_one(filter_doc, update_doc, upsert=True)
            if result.upserted_id is not None:
                logging.info(f"Ship '{ship_name}' registered in Alliance collection via upsert.")
            else:
                logging.info(f"Ship for user {discord_id} updated without creating a duplicate.")

            await interaction.response.send_message(
                f"Ship registration successful! **{ship_name}** is now linked to your profile.",
                ephemeral=True
            )
        except Exception as e:
            logging.error(f"Error during ship registration: {e}")
            await interaction.response.send_message(
                "An error occurred while registering your ship. Please try again later.",
                ephemeral=True
            )

