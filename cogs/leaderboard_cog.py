import os
import logging
import discord
from discord.ext import commands, tasks
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
try:
    # Python <3.9 may not define this; catch broadly
    from zoneinfo import ZoneInfoNotFoundError  # type: ignore
except Exception:  # pragma: no cover
    ZoneInfoNotFoundError = Exception  # Fallback type
from config import class_a_role_id

CATEGORY_NAME = "GPT Network"
LEADERBOARD_CHANNEL_NAME = "\u2757\uFF5Cleaderboard"
ALTERNATE_LEADERBOARD_NAMES = [
    LEADERBOARD_CHANNEL_NAME,
    "leaderboard",
    "\u2757|leaderboard",
]
LEADERBOARD_IMAGE_PATH = "sos_leaderboard.png"

logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
logger = logging.getLogger(__name__)

# Fixed monthly focus per request
FOCUS_TITLE = "Most Shots Fired"
FOCUS_STAT_KEY = "shots_fired"

class LeaderboardCog(commands.Cog):
    """Dynamic monthly leaderboard with correct visibility."""

    def __init__(self, bot):
        self.bot = bot
        self.leaderboard_lock = asyncio.Lock()
        self.last_known_month = datetime.utcnow().month
        self.update_leaderboard_task.start()

    def cog_unload(self):
        self.update_leaderboard_task.cancel()

    @commands.command(name="refresh_leaderboard")
    @commands.has_permissions(administrator=True)
    async def refresh_leaderboard(self, ctx: commands.Context):
        """Admin-only: force refresh the leaderboard now."""
        try:
            await self._run_leaderboard_update(force=True)
            await ctx.reply("Leaderboard refreshed.")
        except Exception as e:
            logger.error(f"Error during manual leaderboard refresh: {e}")
            await ctx.reply("Failed to refresh leaderboard. Check logs.")

    @tasks.loop(hours=1)
    async def update_leaderboard_task(self):
        current_month = datetime.utcnow().month
        is_new_month = current_month != self.last_known_month
        if is_new_month:
            logger.info("New month detected! Forcing leaderboard update.")
            self.last_known_month = current_month
            await self._run_leaderboard_update(force=True)
        else:
            await self._run_leaderboard_update()

    @update_leaderboard_task.before_loop
    async def before_update_leaderboard_task(self):
        await self.bot.wait_until_ready()

    async def _run_leaderboard_update(self, force=False):
        if force:
            logger.info("Forced leaderboard update requested.")
        async with self.leaderboard_lock:
            # Use America/Chicago timezone for title display, fall back to UTC if tzdata missing
            try:
                now = datetime.now(ZoneInfo("America/Chicago"))
            except ZoneInfoNotFoundError:
                logger.warning("tzdata not installed; falling back to UTC for leaderboard title.")
                now = datetime.utcnow()
            month_name = now.strftime("%B %Y")
            # Styled title, keep the word 'Leaderboard' for cleanup detection
            title = f"Most Shots Fired Leaderboard - {month_name}"

            leaderboard_data = await self.calculate_leaderboard_data(FOCUS_STAT_KEY, now.year, now.month)
            await self.promote_class_a_citizens(leaderboard_data)
            embeds = await self.build_leaderboard_embeds(leaderboard_data, title, FOCUS_STAT_KEY)
            for guild in self.bot.guilds:
                channel = await self.ensure_leaderboard_channel(guild)
                if not channel:
                    continue
                # Clean up old leaderboard messages (ensure deletion before posting new)
                try:
                    # 1) Prefer precise deletion using stored message IDs
                    total_deleted = 0
                    try:
                        if hasattr(self.bot, 'mongo_db'):
                            server_listing = self.bot.mongo_db['Server_Listing']
                            doc = await server_listing.find_one({"discord_server_id": guild.id}, {"leaderboard_message_ids": 1})
                            msg_ids = (doc or {}).get("leaderboard_message_ids", []) or []
                            for mid in msg_ids:
                                try:
                                    msg = await channel.fetch_message(int(mid))
                                    await msg.delete()
                                    total_deleted += 1
                                    await asyncio.sleep(0.2)
                                except Exception:
                                    pass
                    except Exception as e:
                        logger.warning(f"Failed precise delete by stored IDs in {guild.name}: {e}")

                    # 2) Heuristic deletion fallback (by title text)
                    def _is_old_lb(m: discord.Message) -> bool:
                        if m.author != self.bot.user or not m.embeds:
                            return False
                        t = (m.embeds[0].title or "").upper()
                        return ("LEADERBOARD" in t or "MOST SHOTS FIRED" in t or "MONTHLY" in t)

                    perms = channel.permissions_for(guild.me)
                    if perms.manage_messages:
                        try:
                            deleted = await channel.purge(limit=1000, check=_is_old_lb, bulk=True)
                            total_deleted += len(deleted)
                        except Exception:
                            async for msg in channel.history(limit=500):
                                if _is_old_lb(msg):
                                    try:
                                        await msg.delete()
                                        total_deleted += 1
                                        await asyncio.sleep(0.2)
                                    except Exception:
                                        pass
                    else:
                        async for msg in channel.history(limit=200):
                            if _is_old_lb(msg):
                                try:
                                    await msg.delete()
                                    total_deleted += 1
                                    await asyncio.sleep(0.2)
                                except Exception:
                                    pass
                    if total_deleted:
                        logger.info(f"Deleted {total_deleted} old leaderboard messages in {guild.name} before posting new.")
                except Exception as e:
                    logger.warning(f"Failed to purge old leaderboard messages in {guild.name}: {e}")
                # Post leaderboard
                new_ids = []
                first_msg_id = None
                if not embeds:
                    embed = discord.Embed(
                        title=title,
                        description="No leaderboard data available.",
                        color=discord.Color.blue()
                    )
                    msg = await channel.send(embed=embed)
                    new_ids.append(int(msg.id))
                    first_msg_id = int(msg.id)
                else:
                    for embed in embeds:
                        msg = await channel.send(embed=embed)
                        new_ids.append(int(msg.id))
                        if first_msg_id is None:
                            first_msg_id = int(msg.id)
                        await asyncio.sleep(1.1)

                # Persist the new message IDs for precise deletion next update
                try:
                    if hasattr(self.bot, 'mongo_db'):
                        server_listing = self.bot.mongo_db['Server_Listing']
                        await server_listing.update_one(
                            {"discord_server_id": guild.id},
                            {"$set": {"leaderboard_message_ids": new_ids}},
                            upsert=True,
                        )
                except Exception as e:
                    logger.warning(f"Failed to store leaderboard_message_ids for {guild.name}: {e}")

                # Pinning not required per request; no action here.

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
        channel = next((c for c in guild.text_channels if c.name in ALTERNATE_LEADERBOARD_NAMES), None)
        category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
        overwrites = {
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
            # Normalize name to the expected one
            if channel.name != LEADERBOARD_CHANNEL_NAME and guild.me.guild_permissions.manage_channels:
                try:
                    await channel.edit(name=LEADERBOARD_CHANNEL_NAME, reason="Normalize leaderboard channel name")
                    changed = True
                except Exception:
                    pass
            # Make sure bot can send
            bot_ow = channel.overwrites_for(guild.me)
            if not bot_ow.send_messages or not bot_ow.embed_links or not bot_ow.attach_files:
                await channel.set_permissions(guild.me, send_messages=True, embed_links=True, attach_files=True, manage_messages=True)
                changed = True
            # Optionally sync with category to enforce Class B-only visibility
            try:
                if channel.category and channel.permissions_synced is False:
                    await channel.edit(sync_permissions=True)
            except Exception:
                pass
            if changed:
                logger.info(f"Updated overwrites for leaderboard channel in guild {guild.name} ({guild.id})")
        return channel

    async def calculate_leaderboard_data(self, stat_key, year, month):
        mongo_uri = os.getenv('MONGODB_URI')
        if not mongo_uri:
            return []
        try:
            db = self.bot.mongo_db if hasattr(self.bot, 'mongo_db') else AsyncIOMotorClient(mongo_uri)['GPTHellbot']
            stats_collection = db['User_Stats']
            alliance_collection = db['Alliance']

            # Date range for month
            start_of_month = datetime(year, month, 1)
            end_of_month = datetime(year + (1 if month == 12 else 0), (1 if month == 12 else month + 1), 1)

            query = {"submitted_at": {"$gte": start_of_month, "$lt": end_of_month}}

            servers = await alliance_collection.find({}, {"discord_server_id": 1, "server_name": 1}).to_list(None)
            server_map = {str(s['discord_server_id']): s['server_name'] for s in servers if 'discord_server_id' in s and 'server_name' in s}

            def to_int(v, default=0):
                try:
                    # handle "", None, numeric strings, etc.
                    return int(v) if v not in (None, "") else default
                except Exception:
                    return default

            players = defaultdict(lambda: {
                "melee_kills": 0, "kills": 0, "deaths": 0,
                "shots_fired": 0, "shots_hit": 0,
                "stims_used": 0, "samples_extracted": 0, "stratagems_used": 0,
                "games_played": 0, "Clan": "Unknown Clan",
                "discord_id": None, "discord_server_id": None
            })

            all_stats = await stats_collection.find(query).to_list(None)

            for doc in all_stats:
                name = doc.get('player_name')
                if not name:
                    continue

                players[name]["melee_kills"]       += to_int(doc.get('Melee Kills'))
                players[name]["kills"]             += to_int(doc.get('Kills'))
                players[name]["deaths"]            += to_int(doc.get('Deaths'))
                players[name]["shots_fired"]       += to_int(doc.get('Shots Fired'))
                players[name]["shots_hit"]         += to_int(doc.get('Shots Hit'))
                players[name]["stims_used"]        += to_int(doc.get('Stims Used'))
                players[name]["samples_extracted"] += to_int(doc.get('Samples Extracted'))
                players[name]["stratagems_used"]   += to_int(doc.get('Stratagems Used'))
                players[name]["games_played"]      += 1

                discord_id = doc.get('discord_id')
                if discord_id and players[name].get("discord_id") is None:
                    players[name]["discord_id"] = str(discord_id)

                server_id = doc.get('discord_server_id')
                if server_id is not None:
                    players[name]["discord_server_id"] = int(server_id)
                    server_id_str = str(server_id)
                    if server_id_str in server_map:
                        players[name]["Clan"] = server_map[server_id_str]

            # Build a lookup of ship names from Alliance for (player_name, discord_server_id)
            ship_lookup = {}
            try:
                names = []
                servers_set = set()
                for pname, d in players.items():
                    names.append(pname)
                    if d.get("discord_server_id") is not None:
                        servers_set.add(int(d["discord_server_id"]))
                if names and servers_set:
                    cursor = alliance_collection.find(
                        {"player_name": {"$in": list(set(names))}, "discord_server_id": {"$in": list(servers_set)}},
                        {"player_name": 1, "discord_server_id": 1, "ship_name": 1}
                    )
                    docs = await cursor.to_list(None)
                    for doc in docs:
                        ship = doc.get("ship_name")
                        if ship:
                            try:
                                key = (doc.get("player_name"), int(doc.get("discord_server_id")))
                                ship_lookup[key] = ship
                            except Exception:
                                pass
            except Exception as e:
                logger.warning(f"Failed to build ship name lookup for leaderboard: {e}")

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
                    "stims_used": d["stims_used"],
                    "samples_extracted": d["samples_extracted"],
                    "stratagems_used": d["stratagems_used"],
                    "games_played": d["games_played"],
                    "Clan": d["Clan"],
                    "average_kills": average_kills,
                    "average_accuracy": average_accuracy,
                    "least_deaths": -d["deaths"],  # negative for sorting
                    "discord_id": d.get("discord_id"),
                    "discord_server_id": d.get("discord_server_id"),
                    "ship_name": ship_lookup.get((name, d.get("discord_server_id")))
                })

            if stat_key == "least_deaths":
                leaderboard.sort(key=lambda x: (x[stat_key], -x["games_played"]))  # fewest deaths, most games
            else:
                leaderboard.sort(key=lambda x: (-x[stat_key], -x["games_played"]))

            return leaderboard
        except Exception as e:
            logger.error(f"Error fetching leaderboard: {e}")
            return []

    async def build_leaderboard_embeds(self, leaderboard_data, title, stat_key):
        embeds = []
        batch_size = 25  # up to 25 entries per page

        if not leaderboard_data:
            return []

        num_pages = (len(leaderboard_data) + batch_size - 1) // batch_size
        for i in range(num_pages):
            batch = leaderboard_data[i*batch_size:(i+1)*batch_size]
            embed = discord.Embed(title=title, color=discord.Color.blurple())
            if num_pages > 1:
                embed.title += f" (Page {i+1}/{num_pages})"

            # Player entries
            for idx, p in enumerate(batch, start=i*batch_size + 1):
                name = (p['player_name'][:42] + "…") if len(p['player_name']) > 43 else p['player_name']

                value_lines = []
                ship = p.get('ship_name')
                if ship:
                    value_lines.append(f"**SES:** {ship}")
                value_lines.extend([
                    f"**Kills:** {p['kills']}",
                    f"**Accuracy:** {(p['shots_hit'] / p['shots_fired'] * 100 if p['shots_fired'] else 0.0):.1f}%",
                    f"**Shots Fired:** {p['shots_fired']}",
                    f"**Shots Hit:** {p['shots_hit']}",
                    f"**Deaths:** {p['deaths']}",
                    f"**Melee Kills:** {p['melee_kills']}",
                    f"**Stims Used:** {p['stims_used']}",
                ])
                value_lines.append(f"**Strats Used:** {p['stratagems_used']}")

                embed.add_field(
                    name=f"#{idx}. {name}",
                    value="\n".join(value_lines),
                    inline=True
                )

            # Clickable site link at the bottom
            embed.add_field(
                name="\u200b",
                value="[gptfleet.com](https://gptfleet.com)",
                inline=False
            )

            # Footer about MVP award
            embed.set_footer(text="Rank #1 will win the @MVP role at the end of the month.")

            embeds.append(embed)

        return embeds

async def setup(bot):
    if not hasattr(bot, 'mongo_db'):
        raise RuntimeError("LeaderboardCog requires bot.mongo_db to be initialized.")
    await bot.add_cog(LeaderboardCog(bot))





