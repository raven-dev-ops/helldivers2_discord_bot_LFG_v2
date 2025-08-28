import os
import logging
import discord
from discord.ext import commands, tasks
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from collections import defaultdict
from datetime import datetime
from config import class_a_role_id

CATEGORY_NAME = "GPT NETWORK"
LEADERBOARD_CHANNEL_NAME = "❗｜leaderboard"
LEADERBOARD_IMAGE_PATH = "sos_leaderboard.png"

logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
logger = logging.getLogger(__name__)

# Each tuple: (label, stat_key)
MONTHLY_FOCUSES = [
    ("Most Average Kills", "average_kills"),    # JANUARY
    ("Most Total Kills", "kills"),              # FEBRUARY
    ("Most Melee Kills", "melee_kills"),        # MARCH
    ("Most Shots Fired", "shots_fired"),        # APRIL
    ("Least Deaths", "least_deaths"),           # MAY
    ("Most Average Kills", "average_kills"),    # JUNE
    ("Best Accuracy", "average_accuracy"),      # JULY (special stat)
    ("Most Total Kills", "kills"),              # AUGUST
    ("Most Melee Kills", "melee_kills"),        # SEPTEMBER
    ("Most Shots Fired", "shots_fired"),        # OCTOBER
    ("Least Deaths", "least_deaths"),           # NOVEMBER
    ("Most Average Kills", "average_kills"),    # DECEMBER
]

def get_current_focus():
    month_idx = datetime.utcnow().month - 1
    return MONTHLY_FOCUSES[month_idx]

class LeaderboardCog(commands.Cog):
    """Dynamic monthly leaderboard with correct visibility."""

    def __init__(self, bot):
        self.bot = bot
        self.leaderboard_lock = asyncio.Lock()
        self.update_leaderboard_task.start()
        self.schedule_monthly_update.start()

    def cog_unload(self):
        self.update_leaderboard_task.cancel()
        self.schedule_monthly_update.cancel()

    @tasks.loop(hours=8)
    async def update_leaderboard_task(self):
        await self._run_leaderboard_update()

    @tasks.loop(hours=1)
    async def schedule_monthly_update(self):
        now = datetime.utcnow()
        if now.day == 28 and now.hour == 0:
            logger.info("It's the 28th - triggering forced leaderboard update for monthly rollover!")
            await self._run_leaderboard_update(force=True)

    @update_leaderboard_task.before_loop
    @schedule_monthly_update.before_loop
    async def before_loops(self):
        await self.bot.wait_until_ready()

    async def _run_leaderboard_update(self, force=False):
        if force:
            logger.info("Forced leaderboard update requested.")
        async with self.leaderboard_lock:
            title, stat_key = get_current_focus()
            leaderboard_data = await self.calculate_leaderboard_data(stat_key)
            await self.promote_class_a_citizens(leaderboard_data)
            embeds, image_path = await self.build_leaderboard_embeds(leaderboard_data, title, stat_key)
            for guild in self.bot.guilds:
                channel = await self.ensure_leaderboard_channel(guild)
                if not channel:
                    continue
                # Clean up old leaderboard messages
                if channel.permissions_for(guild.me).manage_messages:
                    async for msg in channel.history(limit=20):
                        if msg.author == self.bot.user:
                            try:
                                await msg.delete()
                                await asyncio.sleep(0.6)
                            except Exception:
                                pass
                # Post leaderboard
                if not embeds:
                    now = datetime.utcnow()
                    month_str = now.strftime("%B").upper()
                    embed = discord.Embed(
                        title=f"**GPT {month_str} {now.year} LEADERBOARD**",
                        description="No leaderboard data available.",
                        color=discord.Color.blue()
                    )
                    file = discord.File(image_path, filename=os.path.basename(image_path)) if image_path else None
                    if file:
                        embed.set_image(url=f"attachment://{os.path.basename(image_path)}")
                    await channel.send(embed=embed, file=file if file else discord.utils.MISSING)
                else:
                    for idx, embed in enumerate(embeds):
                        file = None
                        if image_path and idx == 0:
                            file = discord.File(image_path, filename=os.path.basename(image_path))
                        await channel.send(embed=embed, file=file if file else discord.utils.MISSING)
                        await asyncio.sleep(1.1)

    async def promote_class_a_citizens(self, leaderboard_data):
        """Assign Class A Citizen role to players with >=3 games."""
        if class_a_role_id is None:
            return
        for entry in leaderboard_data:
            if entry.get("games_played", 0) < 3:
                continue
            discord_id = entry.get("discord_id")
            server_id = entry.get("discord_server_id")
            if not discord_id or not server_id:
                continue
            guild = self.bot.get_guild(int(server_id))
            if not guild:
                continue
            member = guild.get_member(int(discord_id))
            if not member:
                continue
            role = guild.get_role(class_a_role_id)
            if not role or role in member.roles:
                continue
            try:
                await member.add_roles(role, reason="Reached 3 games on leaderboard")
            except Exception as e:
                logger.error(f"Failed to assign Class A role to {discord_id}: {e}")

    async def ensure_leaderboard_channel(self, guild: discord.Guild):
        # Try to get channel
        channel = discord.utils.get(guild.text_channels, name=LEADERBOARD_CHANNEL_NAME)
        category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False),
            guild.me: discord.PermissionOverwrite(send_messages=True, embed_links=True, attach_files=True, manage_messages=True)
        }
        # Check for creation
        if not category and guild.me.guild_permissions.manage_channels:
            category = await guild.create_category(CATEGORY_NAME)
        if not channel and guild.me.guild_permissions.manage_channels:
            channel = await guild.create_text_channel(
                LEADERBOARD_CHANNEL_NAME, category=category, overwrites=overwrites)
        # Update overwrites on existing channel to ensure visibility
        elif channel:
            changed = False
            # Make sure @everyone can see, but not send
            current_ow = channel.overwrites_for(guild.default_role)
            if current_ow.view_channel is not True or current_ow.send_messages not in [False, None]:
                await channel.set_permissions(guild.default_role, view_channel=True, send_messages=False)
                changed = True
            # Make sure bot can send
            bot_ow = channel.overwrites_for(guild.me)
            if not bot_ow.send_messages or not bot_ow.embed_links or not bot_ow.attach_files:
                await channel.set_permissions(guild.me, send_messages=True, embed_links=True, attach_files=True, manage_messages=True)
                changed = True
            if changed:
                logger.info(f"Updated overwrites for leaderboard channel in guild {guild.name} ({guild.id})")
        return channel

    async def calculate_leaderboard_data(self, stat_key):
        mongo_uri = os.getenv('MONGODB_URI')
        if not mongo_uri:
            return []
        try:
            db = self.bot.mongo_db if hasattr(self.bot, 'mongo_db') else AsyncIOMotorClient(mongo_uri)['GPTHellbot']
            stats_collection = db['User_Stats']
            alliance_collection = db['Alliance']
            servers = await alliance_collection.find({}, {"discord_server_id": 1, "server_name": 1}).to_list(None)
            server_map = {str(s['discord_server_id']): s['server_name'] for s in servers if 'discord_server_id' in s and 'server_name' in s}
            players = defaultdict(lambda: {
                "melee_kills": 0, "kills": 0, "deaths": 0, "shots_fired": 0, "shots_hit": 0,
                "games_played": 0, "Clan": "Unknown Clan", "discord_id": None, "discord_server_id": None
            })
            all_stats = await stats_collection.find({}).to_list(None)
            for doc in all_stats:
                name = doc.get('player_name')
                if not name:
                    continue
                try:
                    melee = int(doc.get('Melee Kills', 0) or 0)
                    kills = int(doc.get('Kills', 0) or 0)
                    deaths = int(doc.get('Deaths', 0) or 0)
                    shots_fired = int(doc.get('Shots Fired', 0) or 0)
                    shots_hit = int(doc.get('Shots Hit', 0) or 0)
                except Exception:
                    melee = kills = deaths = shots_fired = shots_hit = 0
                players[name]["melee_kills"] += melee
                players[name]["kills"] += kills
                players[name]["deaths"] += deaths
                players[name]["shots_fired"] += shots_fired
                players[name]["shots_hit"] += shots_hit
                players[name]["games_played"] += 1
                discord_id = doc.get('discord_id')
                if discord_id and players[name].get("discord_id") is None:
                    players[name]["discord_id"] = str(discord_id)
                server_id = doc.get('discord_server_id')
                if server_id is not None:
                    players[name]["discord_server_id"] = int(server_id)
                    server_id_str = str(server_id)
                    if server_id_str in server_map:
                        players[name]["Clan"] = server_map[server_id_str]
            leaderboard = []
            for name, d in players.items():
                average_kills = d["kills"] / d["games_played"] if d["games_played"] else 0.0
                average_accuracy = (d["shots_hit"] / d["shots_fired"] * 100) if d["shots_fired"] > 0 else 0.0
                leaderboard.append({
                    "player_name": name,
                    "melee_kills": d["melee_kills"],
                    "kills": d["kills"],
                    "deaths": d["deaths"],
                    "shots_fired": d["shots_fired"],
                    "shots_hit": d["shots_hit"],
                    "games_played": d["games_played"],
                    "Clan": d["Clan"],
                    "average_kills": average_kills,
                    "average_accuracy": average_accuracy,
                    "least_deaths": -d["deaths"],  # Negative for sorting (least at top)
                    "discord_id": d.get("discord_id"),
                    "discord_server_id": d.get("discord_server_id"),
                })
            if stat_key == "least_deaths":
                leaderboard.sort(key=lambda x: (x[stat_key], -x["games_played"]))  # fewest deaths, most games
            else:
                leaderboard.sort(key=lambda x: (-x[stat_key], -x["games_played"]))
            return leaderboard
        except Exception as e:
            logger.error(f"Error fetching leaderboard: {e}")
            return []

    async def build_leaderboard_embeds(self, leaderboard_data, focus_title, stat_key):
        embeds = []
        batch_size = 10
        image_path = LEADERBOARD_IMAGE_PATH if os.path.exists(LEADERBOARD_IMAGE_PATH) else None

        if not leaderboard_data:
            return [], image_path

        now = datetime.utcnow()
        month_str = now.strftime("%B").upper()
        num_pages = (len(leaderboard_data) + batch_size - 1) // batch_size
        for i in range(num_pages):
            batch = leaderboard_data[i*batch_size:(i+1)*batch_size]
            embed = discord.Embed(
                title=f"**{month_str} {now.year} GALACTIC HELLDIVER LEADERBOARD**\n*({focus_title})*",
                color=discord.Color.blurple()
            )
            if num_pages > 1:
                embed.title += f" (Page {i+1}/{num_pages})"
            embed.set_footer(text=f"Updated every 12 hours. New Yearly, Monthly, Weekly, Daily, and Solo Leadboards coming soon.")

            if image_path and i == 0:
                embed.set_image(url=f"attachment://{os.path.basename(image_path)}")

            for idx, player in enumerate(batch, start=i*batch_size + 1):
                if idx == 1:
                    rank_emoji = "🥇 "
                elif idx == 2:
                    rank_emoji = "🥈 "
                elif idx == 3:
                    rank_emoji = "🥉 "
                name = (player['player_name'][:22] + "...") if len(player['player_name']) > 25 else player['player_name']
                stat_val = player[stat_key]
                if stat_key == "average_accuracy":
                    stat_val_str = f"{stat_val:.1f}%"
                elif stat_key == "average_kills":
                    stat_val_str = f"{stat_val:.2f}"
                elif stat_key == "least_deaths":
                    stat_val_str = f"{-stat_val}"  # Show as positive number
                else:
                    stat_val_str = f"{stat_val}"
                embed.add_field(
                    name=f"{rank_emoji}#{idx}. {name}",
                    value=(
                        f"**Clan:** {player['Clan']}\n"
                        f"**{focus_title}:** {stat_val_str}\n"
                        f"**Kills:** {player['kills']}\n"
                        f"**Deaths:** {player['deaths']}\n"
                        f"**Accuracy:** {(player['shots_hit'] / player['shots_fired'] * 100 if player['shots_fired'] else 0.0):.1f}%\n"
                        f"**Shots Hit:** {player['shots_hit']}\n"
                        f"**Shots Fired:** {player['shots_fired']}\n"
                        f"*Games: {player['games_played']}*"
                    ),
                    inline=True
                )
            embeds.append(embed)
        return embeds, image_path

async def setup(bot):
    if not hasattr(bot, 'mongo_db'):
        raise RuntimeError("LeaderboardCog requires bot.mongo_db to be initialized.")
    await bot.add_cog(LeaderboardCog(bot))
