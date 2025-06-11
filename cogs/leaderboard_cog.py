import os
import logging
import discord
from discord.ext import commands, tasks
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from collections import defaultdict

CATEGORY_NAME = "GPT NETWORK"
LEADERBOARD_CHANNEL_NAME = "❗｜leaderboard"
LEADERBOARD_IMAGE_PATH = "sos_leaderboard.png"
MIN_GAMES_PLAYED = 3

logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
logger = logging.getLogger(__name__)

class LeaderboardCog(commands.Cog):
    """
    June 2025: Best Melee Kills (shows all stats).
    """

    def __init__(self, bot):
        self.bot = bot
        self.leaderboard_lock = asyncio.Lock()
        self.update_leaderboard_task.start()

    def cog_unload(self):
        self.update_leaderboard_task.cancel()

    @tasks.loop(hours=8)
    async def update_leaderboard_task(self):
        async with self.leaderboard_lock:
            leaderboard_data = await self.calculate_leaderboard_data()
            embeds, image_path = await self.build_leaderboard_embeds(leaderboard_data)
            for guild in self.bot.guilds:
                channel = await self.ensure_leaderboard_channel(guild)
                if not channel:
                    continue
                if channel.permissions_for(guild.me).manage_messages:
                    async for msg in channel.history(limit=20):
                        if msg.author == self.bot.user:
                            try:
                                await msg.delete()
                                await asyncio.sleep(0.6)
                            except Exception:
                                pass
                if not embeds:
                    embed = discord.Embed(
                        title="**GPT JUNE 2025 LEADERBOARD**",
                        description=f"No leaderboard data available.\nPlayers must submit at least ({MIN_GAMES_PLAYED}) games to appear!",
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

    @update_leaderboard_task.before_loop
    async def before_update_leaderboard_task(self):
        await self.bot.wait_until_ready()

    async def ensure_leaderboard_channel(self, guild: discord.Guild):
        channel = discord.utils.get(guild.text_channels, name=LEADERBOARD_CHANNEL_NAME)
        if channel and channel.permissions_for(guild.me).send_messages:
            return channel
        try:
            category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
            if not category and guild.me.guild_permissions.manage_channels:
                category = await guild.create_category(CATEGORY_NAME)
            if not channel and guild.me.guild_permissions.manage_channels:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False),
                    guild.me: discord.PermissionOverwrite(send_messages=True, embed_links=True, attach_files=True, manage_messages=True)
                }
                channel = await guild.create_text_channel(
                    LEADERBOARD_CHANNEL_NAME, category=category, overwrites=overwrites)
            return channel
        except Exception:
            return None

    async def calculate_leaderboard_data(self):
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
                "games_played": 0, "Clan": "Unknown Clan"
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
                server_id = str(doc.get('discord_server_id', ''))
                if server_id in server_map:
                    players[name]["Clan"] = server_map[server_id]

            leaderboard = []
            for name, d in players.items():
                if d["games_played"] >= MIN_GAMES_PLAYED:
                    accuracy = (d["shots_hit"] / d["shots_fired"] * 100) if d["shots_fired"] > 0 else 0.0
                    leaderboard.append({
                        "player_name": name,
                        "melee_kills": d["melee_kills"],
                        "kills": d["kills"],
                        "deaths": d["deaths"],
                        "shots_fired": d["shots_fired"],
                        "shots_hit": d["shots_hit"],
                        "games_played": d["games_played"],
                        "Clan": d["Clan"],
                        "accuracy": accuracy,
                    })
            leaderboard.sort(key=lambda x: -x["melee_kills"])
            return leaderboard
        except Exception as e:
            logger.error(f"Error fetching leaderboard: {e}")
            return []

    async def build_leaderboard_embeds(self, leaderboard_data):
        embeds = []
        batch_size = 10
        image_path = LEADERBOARD_IMAGE_PATH if os.path.exists(LEADERBOARD_IMAGE_PATH) else None

        if not leaderboard_data:
            return [], image_path

        num_pages = (len(leaderboard_data) + batch_size - 1) // batch_size
        for i in range(num_pages):
            batch = leaderboard_data[i*batch_size:(i+1)*batch_size]
            embed = discord.Embed(
                title=f"**JUNE ALLIANCE LEADERBOARD**\n*(Most Melee Kills)*",
                color=discord.Color.blurple()
            )
            if num_pages > 1:
                embed.title += f" (Page {i+1}/{num_pages})"
            embed.set_footer(text=f"Leaderboard updates every 8 hours. Minimum {MIN_GAMES_PLAYED} games required.")

            if image_path and i == 0:
                embed.set_image(url=f"attachment://{os.path.basename(image_path)}")

            for idx, player in enumerate(batch, start=i*batch_size + 1):
                rank_emoji = ""
                if idx == 1: rank_emoji = "🥇 "
                elif idx == 2: rank_emoji = "🥈 "
                elif idx == 3: rank_emoji = "🥉 "
                name = (player['player_name'][:22] + "...") if len(player['player_name']) > 25 else player['player_name']
                embed.add_field(
                    name=f"{rank_emoji}#{idx}. {name}",
                    value=(
                        f"**Clan:** {player['Clan']}\n"
                        f"**Melee Kills:** {player['melee_kills']}\n"
                        f"**Kills:** {player['kills']}\n"
                        f"**Deaths:** {player['deaths']}\n"
                        f"**Accuracy:** {player['accuracy']:.1f}%\n"
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
