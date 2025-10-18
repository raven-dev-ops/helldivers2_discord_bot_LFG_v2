import discord
from discord.ext import commands
from datetime import datetime
import logging
import asyncio
from config import lfg_ping_role_id, na_role_id, eu_role_id, uk_role_id, au_role_id, asia_role_id

class RegisterModal(discord.ui.Modal, title="Register"):
    """
    A modal for user registration.
    """
    helldiver_name = discord.ui.TextInput(
        label="Helldiver Name",
        placeholder="Enter your Helldiver Name...",
        required=True,
        max_length=100
    )
    ship_name = discord.ui.TextInput(
        label="Super Earth Ship Name (optional)",
        placeholder="Enter your Super Earth Ship Name...",
        required=False,
        max_length=100
    )
    region = discord.ui.TextInput(
        label="Region (optional)",
        placeholder="NA, EU, UK, AU, ASIA",
        required=False,
        max_length=16
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
            ship_name = (self.ship_name.value or "").strip()
            logging.info(f"Registering user '{player_name}' (Discord ID: {discord_id}) in guild '{server_name}' ({discord_server_id}).")

            # Insert into the Alliance collection
            alliance_collection = self.bot.mongo_db['Alliance']
            filter_doc = {
                "discord_id": discord_id,
                "discord_server_id": discord_server_id,
            }
            set_fields = {
                "player_name": player_name,
                "server_name": server_name,
                "server_nickname": server_nickname,
            }
            if ship_name:
                set_fields["ship_name"] = ship_name

            update_doc = {
                "$set": set_fields,
                "$setOnInsert": {"registered_at": datetime.utcnow()}
            }

            result = await alliance_collection.update_one(filter_doc, update_doc, upsert=True)
            if result.upserted_id is not None:
                logging.info(f"User '{player_name}' registered in Alliance collection via upsert.")
            else:
                logging.info(f"User '{player_name}' Alliance registration updated without creating a duplicate.")

            # Try to assign the LFG PING! role on successful registration
            try:
                role = None
                try:
                    if lfg_ping_role_id is not None:
                        role = interaction.guild.get_role(int(lfg_ping_role_id))
                except Exception:
                    role = None
                if role is None:
                    role = discord.utils.get(interaction.guild.roles, name="LFG PING!")
                if role is not None and all(r.id != role.id for r in interaction.user.roles):
                    await interaction.user.add_roles(role, reason="Registration: grant LFG PING! role")
                    logging.info(f"Assigned LFG PING! role to {interaction.user} ({interaction.user.id}).")
                elif role is None:
                    logging.warning("LFG PING! role not found by ID or name; skipping assignment.")
            except Exception as role_e:
                logging.warning(f"Failed to assign LFG PING! role during registration: {role_e}")

            # Attempt to assign a regional role:
            # 1) If provided in modal (Region field), use it.
            # 2) Else, auto-detect from locale if available.
            try:
                # Determine desired region
                rid_map = {"NA": na_role_id, "EU": eu_role_id, "UK": uk_role_id, "AU": au_role_id, "ASIA": asia_role_id}
                region_code = None
                user_input = (self.region.value or "").strip().upper()
                synonyms = {
                    "NORTH AMERICA": "NA",
                    "USA": "NA",
                    "US": "NA",
                    "CANADA": "NA",
                    "MEXICO": "NA",
                    "EUROPE": "EU",
                    "UNITED KINGDOM": "UK",
                    "GREAT BRITAIN": "UK",
                    "BRITAIN": "UK",
                    "OCEANIA": "AU",
                    "AUSTRALIA": "AU",
                    "NEW ZEALAND": "AU",
                }
                if user_input:
                    if user_input in rid_map:
                        region_code = user_input
                    else:
                        region_code = synonyms.get(user_input)
                if not region_code:
                    loc = getattr(interaction, 'user_locale', None) or getattr(interaction, 'locale', None)
                    if isinstance(loc, str):
                        lc = loc.lower()
                        if any(k in lc for k in ("en-us", "en-ca", "es-419")):
                            region_code = "NA"
                        elif any(k in lc for k in ("en-gb",)):
                            region_code = "UK"
                        elif any(k in lc for k in ("en-au", "en-nz")):
                            region_code = "AU"
                        elif any(k in lc for k in ("ja", "ko", "zh", "th", "vi", "id", "ms")):
                            region_code = "ASIA"
                        elif any(k in lc for k in ("de", "fr", "es", "it", "pl", "nl", "pt", "sv", "da", "fi", "no", "cs", "hu", "tr", "ru")):
                            region_code = "EU"

                if region_code:
                    target_role = None
                    rid = rid_map.get(region_code)
                    if rid is not None:
                        target_role = interaction.guild.get_role(int(rid))
                    if target_role is None:
                        name_fallbacks = {
                            "NA": ["NA", "North America"],
                            "EU": ["EU", "Europe"],
                            "UK": ["UK", "United Kingdom"],
                            "AU": ["AU", "Australia", "Oceania"],
                            "ASIA": ["ASIA", "Asia"],
                        }
                        for n in name_fallbacks.get(region_code, []):
                            target_role = discord.utils.get(interaction.guild.roles, name=n)
                            if target_role:
                                break
                    if target_role:
                        all_region_ids = [rid for rid in rid_map.values() if rid is not None]
                        to_remove = [r for r in interaction.user.roles if r.id in all_region_ids and r.id != target_role.id]
                        if to_remove:
                            try:
                                await interaction.user.remove_roles(*to_remove, reason="Region role cleanup")
                            except Exception:
                                pass
                        if all(r.id != target_role.id for r in interaction.user.roles):
                            await interaction.user.add_roles(target_role, reason="Registration: set region role")
                            logging.info(f"Assigned region role {target_role.name} to {interaction.user}.")
            except Exception as re:
                logging.warning(f"Failed to auto-assign region role from locale: {re}")

            msg = f"Registration successful! Welcome, **{player_name}**!"
            if ship_name:
                msg += f" Ship: **{ship_name}**."
            await interaction.response.send_message(msg, ephemeral=True)
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

