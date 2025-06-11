# sos_view.py
import discord
from discord.ext import commands
import logging

class SOSView(discord.ui.View):
    """
    A Discord UI View for creating an SOS with dropdown selections.
    Allows selecting enemy, difficulty, mission, voice, and optional notes.
    """
    def __init__(self, bot):
        # Set the timeout as you prefer; ephemeral interactions expire after 15min anyway.
        super().__init__(timeout=180)  # View times out after 3 minutes
        self.bot = bot

        self.enemy_type = None
        self.difficulty = None
        self.mission = None
        self.voice = None
        self.notes = None

        self.add_enemy_type_select()

    def add_enemy_type_select(self):
        self.clear_items()
        self.add_item(EnemyTypeSelect())

    def add_difficulty_select(self):
        self.clear_items()
        self.add_item(DifficultySelect())

    def add_mission_select(self):
        self.clear_items()
        self.add_item(MissionSelect())

    def add_voice_select(self):
        self.clear_items()
        self.add_item(VoiceSelect())

    def add_notes_buttons(self):
        self.clear_items()
        self.add_item(AddNotesButton())
        # Add the finish button as a separate item
        self.add_item(FinishSOSButton())

    async def submit_sos(self, interaction: discord.Interaction):
        sos_cog = self.bot.get_cog('SOSCog')
        if not sos_cog:
            # Safely respond or follow up
            if not interaction.response.is_done():
                await interaction.response.send_message("SOSCog not loaded. Cannot submit SOS.", ephemeral=True)
            else:
                await interaction.followup.send("SOSCog not loaded. Cannot submit SOS.", ephemeral=True)
            logging.warning("SOSCog is not loaded.")
            return

        try:
            await sos_cog.process_sos(interaction, self)
        except Exception as e:
            logging.error(f"Error submitting SOS: {e}")
            # Again, respond or followup safely
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "An unexpected error occurred while submitting the SOS.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "An unexpected error occurred while submitting the SOS.",
                    ephemeral=True
                )


class EnemyTypeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label='Any', value='Any'),
            discord.SelectOption(label='Automaton', value='Automaton'),
            discord.SelectOption(label='Terminid', value='Terminid'),
            discord.SelectOption(label='Illuminate', value='Illuminate')
        ]
        super().__init__(placeholder="Select Enemy Type", options=options)

    async def callback(self, interaction: discord.Interaction):
        view: SOSView = self.view
        view.enemy_type = self.values[0]
        self.disabled = True
        self.placeholder = f"Selected: {self.values[0]}"
        
        # Safely defer
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        
        view.add_difficulty_select()
        await interaction.edit_original_response(
            content="Enemy type selected. Please select the difficulty:",
            view=view
        )


class DifficultySelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label='Trivial', value='Trivial'),
            discord.SelectOption(label='Easy', value='Easy'),
            discord.SelectOption(label='Medium', value='Medium'),
            discord.SelectOption(label='Challenging', value='Challenging'),
            discord.SelectOption(label='Hard', value='Hard'),
            discord.SelectOption(label='Extreme', value='Extreme'),
            discord.SelectOption(label='Suicide Mission', value='Suicide Mission'),
            discord.SelectOption(label='Impossible', value='Impossible'),
            discord.SelectOption(label='Helldive', value='Helldive'),
            discord.SelectOption(label='Super Helldive', value='Super Helldive'),
        ]
        super().__init__(placeholder="Select Difficulty", options=options)

    async def callback(self, interaction: discord.Interaction):
        view: SOSView = self.view
        view.difficulty = self.values[0]
        self.disabled = True
        self.placeholder = f"Selected: {self.values[0]}"
        
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        
        view.add_mission_select()
        await interaction.edit_original_response(
            content="Difficulty selected. Please select the mission focus:",
            view=view
        )


class MissionSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label='Credit Farm', value='Credit Farm'),
            discord.SelectOption(label='Sample Farm', value='Sample Farm'),
            discord.SelectOption(label='Hardcore', value='Hardcore'),
            discord.SelectOption(label='Casual', value='Casual'),
            discord.SelectOption(label='Competitive', value='Competitive'),
        ]
        super().__init__(placeholder="Select Mission Focus", options=options)

    async def callback(self, interaction: discord.Interaction):
        view: SOSView = self.view
        view.mission = self.values[0]
        self.disabled = True
        self.placeholder = f"Selected: {self.values[0]}"
        
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        
        view.add_voice_select()
        await interaction.edit_original_response(
            content="Mission focus selected. Please select the voice option:",
            view=view
        )


class VoiceSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label='Required', value='Required'),
            discord.SelectOption(label='Optional', value='Optional'),
        ]
        super().__init__(placeholder="Select Voice Option", options=options)

    async def callback(self, interaction: discord.Interaction):
        view: SOSView = self.view
        view.voice = self.values[0]
        self.disabled = True
        self.placeholder = f"Selected: {self.values[0]}"
        
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        
        view.add_notes_buttons()
        await interaction.edit_original_response(
            content="Voice option selected. You may add notes or finalize your SOS:",
            view=view
        )


class NotesModal(discord.ui.Modal):
    def __init__(self, view: SOSView):
        super().__init__(title="Mission Notes", timeout=300)
        self.view = view
        self.notes_input = discord.ui.TextInput(
            label="Enter mission-specific notes:",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1000,
            placeholder="Anything special you want others to know?"
        )
        self.add_item(self.notes_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.view.notes = self.notes_input.value
        
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        
        await interaction.followup.send(
            "Your notes have been recorded! Click 'Finish SOS' to launch it.",
            ephemeral=True
        )


class AddNotesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Add Notes", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        view: SOSView = self.view
        modal = NotesModal(view)
        
        # Show the modal
        await interaction.response.send_modal(modal)


class FinishSOSButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Finish SOS", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        sos_cog = interaction.client.get_cog("SOSCog")
        if sos_cog:
            # Defer if no response is done yet
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)

            try:
                # Submit/finalize SOS
                await sos_cog.process_sos(interaction, self.view)

                # After everything succeeds, delete the ephemeral message
                await interaction.delete_original_response()

            except discord.NotFound:
                # Interaction or webhook could be too old
                await interaction.followup.send(
                    "Sorry, this request could not be completed (interaction is stale).",
                    ephemeral=True
                )
            except Exception as e:
                logging.error(f"Error in finish_sos_button: {e}")
                # Attempt a fallback response
                if not interaction.response.is_done():
                    await interaction.response.send_message("An error occurred.", ephemeral=True)
                else:
                    await interaction.followup.send("An error occurred.", ephemeral=True)
        else:
            if not interaction.response.is_done():
                await interaction.response.send_message("SOSCog not found.", ephemeral=True)
            else:
                await interaction.followup.send("SOSCog not found.", ephemeral=True)

class SOSViewCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_sos_view(self):
        return SOSView(self.bot)

async def setup(bot):
    await bot.add_cog(SOSViewCog(bot))
