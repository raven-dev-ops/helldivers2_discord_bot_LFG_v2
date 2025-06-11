# dm_response.py

import discord
from discord.ext import commands
import logging

class DMResponseCog(commands.Cog):
    """
    Cog to handle optional DM prompts for newly joined members to an SOS channel.
    This feature is now deactivated, as the bot automatically adds
    players to the fleet response without needing a DM prompt.
    """
    def __init__(self, bot):
        self.bot = bot

    # Below is the previously used DM approach. We leave it in place, but
    # comment out the on_voice_state_update listener so it won't fire.

    # async def ask_member_to_join_sos(self, member, voice_channel):
    #     """
    #     Sends a DM to the member asking them to join the SOS response,
    #     unless they are the host of the SOS.
    #     """
    #     try:
    #         sos_cog = self.bot.get_cog('SOSCog')
    #         if not sos_cog:
    #             logging.warning("SOSCog is not loaded.")
    #             return

    #         sos_data = sos_cog.sos_data_by_channel.get(voice_channel.id)
    #         if not sos_data:
    #             logging.warning(f"No SOS data found for voice channel {voice_channel.id}")
    #             return

    #         # Skip if the member is the initiator
    #         if member.id == sos_data['initiator_id']:
    #             logging.info(f"Skipping DM for SOS host: {member.display_name}")
    #             return

    #         # Check if the member has already been prompted
    #         if member.id in sos_data['prompted_users']:
    #             return

    #         sos_data['prompted_users'].add(member.id)

    #         dm_channel = await member.create_dm()
    #         view = SOSResponseView(sos_data, member)
    #         dm_message = await dm_channel.send(
    #             content="Do you wish to respond to this SOS?",
    #             view=view
    #         )
    #         sos_data['dm_messages'][member.id] = dm_message
    #         view.interaction_message = dm_message

    #     except Exception as e:
    #         logging.error(f"Failed to send DM to {member}: {e}")

    # Comment out the listener so it won't trigger the DM prompts.
    # @commands.Cog.listener()
    # async def on_voice_state_update(self, member, before, after):
    #     """
    #     Detect if a non-bot user joins an SOS channel, then optionally DM them to respond.
    #     (Now deactivated.)
    #     """
    #     if member.bot:
    #         return

    #     if after.channel and after.channel.id:
    #         sos_cog = self.bot.get_cog('SOSCog')
    #         if not sos_cog:
    #             logging.warning("SOSCog is not loaded.")
    #             return

    #         sos_data = sos_cog.sos_data_by_channel.get(after.channel.id)
    #         if sos_data:
    #             logging.info(f"Member '{member.display_name}' joined SOS channel '{after.channel.name}'.")
    #             await self.ask_member_to_join_sos(member, after.channel)

# The SOSResponseView class can remain in place if you'd like, 
# but it is effectively unused without the DM prompting mechanism.

class SOSResponseView(discord.ui.View):
    """
    A Discord UI view for handling SOS responses via DMs.
    Currently unused, but left for reference if you re-enable DM prompts in the future.
    """
    def __init__(self, sos_data, member):
        super().__init__(timeout=180)  # Timeout after 3 minutes
        self.sos_data = sos_data
        self.member = member
        self.interaction_message = None
        self.add_item(SOSYesButton())
        self.add_item(SOSNoButton())

    async def on_timeout(self):
        try:
            if self.interaction_message:
                await self.interaction_message.delete()
                logging.info(f"Deleted interaction message after timeout for user {self.member.display_name}")
        except discord.NotFound:
            logging.warning("Interaction message already deleted.")
        except Exception as e:
            logging.error(f"Failed to delete message after timeout: {e}")

class SOSYesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label='Yes', style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        sos_data = self.view.sos_data
        member = self.view.member

        async with sos_data['lock']:
            status_field = sos_data['embed'].fields[sos_data['status_index']]
            if status_field.value == '**Closed**':
                await interaction.response.send_message("Sorry, this SOS is already closed.", ephemeral=True)
                return

            if member.id in sos_data['users']:
                await interaction.response.send_message("You have already responded to this SOS.", ephemeral=True)
                return

            # Add the member to Fleet Response
            sos_data['users'][member.id] = member.display_name
            fleet_response = '\n'.join(sos_data['users'].values())

            sos_data['embed'].set_field_at(
                index=sos_data['fleet_response_index'],
                name='Fleet Response',
                value=fleet_response,
                inline=False
            )

            if len(sos_data['users']) >= 4:
                sos_data['embed'].set_field_at(
                    index=sos_data['status_index'],
                    name='Status',
                    value='**Closed**',
                    inline=False
                )

            # Update all SOS messages
            for msg in sos_data['sos_messages'].values():
                await msg.edit(embed=sos_data['embed'])

            await interaction.response.send_message("You have been added to the Fleet Response.", ephemeral=True)
            self.view.stop()

            # Clean up the DM
            try:
                if self.view.interaction_message:
                    await self.view.interaction_message.delete()
                    logging.info(f"Deleted interaction message for user {member.display_name}")
            except discord.NotFound:
                logging.warning("Interaction message already deleted.")
            except Exception as e:
                logging.error(f"Failed to delete the interaction message: {e}")

class SOSNoButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label='No', style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("No problem, you can still stay in the voice channel.", ephemeral=True)
        self.view.stop()

        # Clean up the DM
        try:
            if self.view.interaction_message:
                await self.view.interaction_message.delete()
                logging.info(f"Deleted interaction message for user {self.view.member.display_name}")
        except discord.NotFound:
            logging.warning("Interaction message already deleted.")
        except Exception as e:
            logging.error(f"Failed to delete the interaction message: {e}")

async def setup(bot):
    await bot.add_cog(DMResponseCog(bot))
