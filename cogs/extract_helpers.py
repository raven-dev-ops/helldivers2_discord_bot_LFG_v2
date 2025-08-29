import re
import discord

def prevent_discord_formatting(name: str) -> str:
    if not name:
        return ""
    return name.replace('<#', '<\u200B#').replace('<@&', '<\u200B@&')

def highlight_zero_values(player: dict) -> list:
    fields = ["Kills", "Accuracy", "Shots Fired", "Shots Hit"]
    zero_fields = []
    for field in fields:
        val = str(player.get(field, 'N/A'))
        if val in ['0', '0.0', 'None', 'N/A']:
            zero_fields.append(field)
    return zero_fields

def validate_stat(field_name: str, raw_value: str):
    raw_value = raw_value.strip()
    if raw_value.upper() == 'N/A':
        return 'N/A'
    if field_name in ['Kills', 'Shots Fired', 'Shots Hit', 'Deaths']:
        return int(raw_value)
    elif field_name == 'Accuracy':
        numeric_part = raw_value.replace('%', '')
        parsed = float(numeric_part)
        return f"{parsed:.1f}%"
    else:
        return raw_value

def clean_for_match(name):
    if not name:
        return ""
    name = name.lower()
    name = re.sub(r'[^a-z0-9]', '', name)
    name = re.sub(r'^(mr|ms|mrs|dr)', '', name)
    return name

def build_single_embed(players_data: list, submitter_player_name: str) -> discord.Embed:
    embed = discord.Embed(
        title="GPT FLEET STAT EXTRACTION",
        description=f"Submitted by: {submitter_player_name}",
        color=discord.Color.blue()
    )
    for index, player in enumerate(players_data, start=1):
        player_name = prevent_discord_formatting(player.get('player_name', 'Unknown'))
        clan_name = player.get('clan_name', 'N/A')
        kills = str(player.get('Kills', 'N/A'))
        deaths = str(player.get('Deaths', 'N/A'))
        shots_fired = str(player.get('Shots Fired', 'N/A'))
        shots_hit = str(player.get('Shots Hit', 'N/A'))
        accuracy = str(player.get('Accuracy', 'N/A'))
        melee_kills = str(player.get('Melee Kills', 'N/A'))
        player_info = (
            f"**Name**: {player_name}\n"
            f"**Kills**: {kills}\n"
            f"**Deaths**: {deaths}\n"
            f"**Shots Fired**: {shots_fired}\n"
            f"**Shots Hit**: {shots_hit}\n"
            f"**Accuracy**: {accuracy}\n"
            f"**Melee Kills**: {melee_kills}\n")
        zero_vals = highlight_zero_values(player)
        if zero_vals:
            player_info += f"\n**Needs Confirmation**: {', '.join(zero_vals)}"
        embed.add_field(name=f"Player {index}", value=player_info, inline=False)
    return embed

def build_monitor_embed(players_data: list, submitter_name: str) -> discord.Embed:
    embed = discord.Embed(
        title="Saved Results",
        description=f"Submitted by: {submitter_name}",
        color=discord.Color.green()
    )
    for index, player in enumerate(players_data, start=1):
        player_name = prevent_discord_formatting(player.get('player_name', 'Unknown'))
        clan_name = player.get('clan_name', 'N/A')
        kills = str(player.get('Kills', 'N/A'))
        deaths = str(player.get('Deaths', 'N/A'))
        shots_fired = str(player.get('Shots Fired', 'N/A'))
        shots_hit = str(player.get('Shots Hit', 'N/A'))
        accuracy = str(player.get('Accuracy', 'N/A'))
        melee_kills = str(player.get('Melee Kills', 'N/A'))
        final_info = (
            f"**Name**: {player_name}\n"
            f"**Clan**: {clan_name}\n"
            f"**Kills**: {kills}\n"
            f"**Accuracy**: {accuracy}\n"
            f"**Shots Fired**: {shots_fired}\n"
            f"**Shots Hit**: {shots_hit}\n"
            f"**Deaths**: {deaths}\n"
            f"**Melee Kills**: {melee_kills}\n")
        embed.add_field(name=f"Player {index}", value=final_info, inline=False)
    return embed
