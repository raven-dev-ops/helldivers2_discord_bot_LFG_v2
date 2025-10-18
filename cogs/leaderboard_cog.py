import os
import logging
import discord
from discord.ext import commands, tasks
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from config import class_b_role_id
try:
    # Python <3.9 may not define this; catch broadly
    from zoneinfo import ZoneInfoNotFoundError  # type: ignore
except Exception:  # pragma: no cover
    ZoneInfoNotFoundError = Exception  # Fallback type
from config import (
    class_a_role_id,
    gpt_achievement_medal_role_id,
    gpt_commendation_medal_role_id,
    gpt_bronze_star_medal_role_id,
    gpt_silver_star_medal_role_id,
    gpt_medal_of_honor_role_id,
    mvp_role_id,
)

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
        # Run a one-shot initial refresh shortly after startup so the
        # leaderboard updates immediately on deploy/restart, instead of
        # waiting for the hourly task tick.
        try:
            asyncio.create_task(self._initial_refresh())
        except Exception:
            pass

    async def _initial_refresh(self):
        try:
            await self.bot.wait_until_ready()
            await asyncio.sleep(2)
            await self._run_leaderboard_update(force=True)
        except Exception as e:
            logger.warning(f"Initial leaderboard refresh failed: {e}")

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
            # On the last day of the month, award submitter medals based on past 28 days
            try:
                await self.maybe_award_submitter_medals(now)
            except Exception as e:
                logger.warning(f"Submitter medal awarding skipped due to error: {e}")
            try:
                await self.maybe_award_mvp(now, leaderboard_data)
            except Exception as e:
                logger.warning(f"MVP awarding skipped due to error: {e}")
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
                logger.info(f"Posted {len(new_ids)} leaderboard message(s) in {guild.name}#{getattr(channel, 'name', '?')} ({getattr(channel, 'id', '?')}).")

                # Pinning not required per request; no action here.


    async def ensure_leaderboard_channel(self, guild: discord.Guild):
        # Try to get channel by stored ID first, then by name
        channel = None
        server_listing = None
        category = None
        # Prefer configured Class B role ID; fallback to name (no creation)
        class_b = None
        try:
            if class_b_role_id is not None:
                class_b = guild.get_role(int(class_b_role_id))
        except Exception:
            class_b = None
        if class_b is None:
            class_b = discord.utils.get(guild.roles, name="Class B Citizens")
        try:
            if hasattr(self.bot, 'mongo_db'):
                server_listing = self.bot.mongo_db['Server_Listing']
                doc = await server_listing.find_one({"discord_server_id": guild.id}, {"leaderboard_channel_id": 1, "category_id": 1})
                lb_id = (doc or {}).get("leaderboard_channel_id")
                cat_id = (doc or {}).get("category_id")
                if cat_id:
                    cat_obj = guild.get_channel(int(cat_id))
                    if isinstance(cat_obj, discord.CategoryChannel):
                        category = cat_obj
                if lb_id:
                    ch = guild.get_channel(int(lb_id))
                    if isinstance(ch, discord.TextChannel):
                        channel = ch
        except Exception:
            pass

        if category is None:
            # Fallback category by known names
            for name in ("GPT CLAN HUB", CATEGORY_NAME):
                category = discord.utils.get(guild.categories, name=name)
                if category:
                    break

        if channel is None:
            channel = next((c for c in guild.text_channels if c.name in ALTERNATE_LEADERBOARD_NAMES), None)

        # Build overwrites: only Class B can view; Class B cannot send or react; bot can post/manage
        overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
        if class_b:
            overwrites[class_b] = discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=False,
                add_reactions=False,
            )
        overwrites[guild.me] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, embed_links=True, attach_files=True, manage_messages=True
        )

        # Create if missing
        if not channel and guild.me.guild_permissions.manage_channels:
            channel = await guild.create_text_channel(
                LEADERBOARD_CHANNEL_NAME, category=category, overwrites=overwrites)
            # Persist channel id
            try:
                if server_listing is not None:
                    await server_listing.update_one(
                        {"discord_server_id": guild.id},
                        {"$set": {"leaderboard_channel_id": int(channel.id)}},
                        upsert=True
                    )
            except Exception:
                pass
        elif channel:
            changed = False
            # Normalize name
            if channel.name != LEADERBOARD_CHANNEL_NAME and guild.me.guild_permissions.manage_channels:
                try:
                    await channel.edit(name=LEADERBOARD_CHANNEL_NAME, reason="Normalize leaderboard channel name")
                    changed = True
                except Exception:
                    pass
            # Ensure visibility and readonly for Class B, and bot perms
            try:
                await channel.set_permissions(guild.default_role, view_channel=False)
                if class_b:
                    await channel.set_permissions(
                        class_b,
                        view_channel=True,
                        read_message_history=True,
                        send_messages=False,
                        add_reactions=False,
                    )
                await channel.set_permissions(guild.me, view_channel=True, send_messages=True, embed_links=True, attach_files=True, manage_messages=True)
                if category and channel.category != category and guild.me.guild_permissions.manage_channels:
                    await channel.edit(category=category)
                changed = True
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
            server_listing_collection = db['Server_Listing']

            # Date range for month
            start_of_month = datetime(year, month, 1)
            end_of_month = datetime(year + (1 if month == 12 else 0), (1 if month == 12 else month + 1), 1)

            query = {"submitted_at": {"$gte": start_of_month, "$lt": end_of_month}}

            def to_int(v, default=0):
                try:
                    return int(v) if v not in (None, "") else default
                except Exception:
                    try:
                        return int(float(v))
                    except Exception:
                        return default

            # Prepare lookups to resolve/repair discord_id by player_name where possible
            all_stats = await stats_collection.find(query).to_list(None)
            if not all_stats:
                return []

            # Collect names and candidate discord IDs from stats
            name_set = set()
            stats_did_ints = set()
            for doc in all_stats:
                n = doc.get('player_name')
                if isinstance(n, str) and n.strip():
                    name_set.add(n.strip())
                did = doc.get('discord_id')
                try:
                    if did not in (None, ""):
                        stats_did_ints.add(int(did))
                except Exception:
                    pass

            # Fetch Alliance profiles by discord_id (valid id set)
            profiles_by_did: dict[str, list[dict]] = {}
            valid_dids: set[str] = set()
            if stats_did_ints:
                cur = alliance_collection.find(
                    {"discord_id": {"$in": list(stats_did_ints)}},
                    {"discord_id": 1, "player_name": 1, "discord_server_id": 1, "ship_name": 1, "server_name": 1}
                )
                for d in await cur.to_list(None):
                    try:
                        k = str(int(d.get("discord_id")))
                        profiles_by_did.setdefault(k, []).append(d)
                        valid_dids.add(k)
                    except Exception:
                        pass

            # Fetch Alliance profiles by player_name to repair missing/invalid ids
            profiles_by_name: dict[str, list[dict]] = {}
            if name_set:
                cur2 = alliance_collection.find(
                    {"player_name": {"$in": list(name_set)}},
                    {"discord_id": 1, "player_name": 1, "discord_server_id": 1, "ship_name": 1, "server_name": 1}
                )
                for d in await cur2.to_list(None):
                    nm = d.get("player_name")
                    if isinstance(nm, str) and nm.strip():
                        profiles_by_name.setdefault(nm.strip(), []).append(d)

            # Server name map for clan display when no Alliance profile is found
            server_name_map = {}
            try:
                sdocs = await server_listing_collection.find({}, {"discord_server_id": 1, "discord_server_name": 1}).to_list(None)
                for sd in sdocs:
                    try:
                        server_name_map[int(sd.get("discord_server_id"))] = sd.get("discord_server_name") or "Unknown Clan"
                    except Exception:
                        pass
            except Exception:
                pass

            # Aggregate by effective Discord ID (repaired from name when possible)
            players = defaultdict(lambda: {
                "melee_kills": 0, "kills": 0, "deaths": 0,
                "shots_fired": 0, "shots_hit": 0,
                "stims_used": 0, "samples_extracted": 0, "stratagems_used": 0,
                "games_played": 0,
                "server_counts": defaultdict(int),  # guild id -> games
                "name_counts": defaultdict(int),    # observed names for this key
            })

            def resolve_effective_did(doc: dict) -> str | None:
                # If stats discord_id is present and exists in Alliance, use it
                did = doc.get('discord_id')
                try:
                    if did not in (None, ""):
                        s = str(int(did))
                        if s in valid_dids:
                            return s
                except Exception:
                    pass
                # Else try to map by exact player_name, prefer same server match
                nm = doc.get('player_name')
                cand = profiles_by_name.get(nm) if isinstance(nm, str) else None
                if cand:
                    if len(cand) == 1:
                        try:
                            return str(int(cand[0].get("discord_id")))
                        except Exception:
                            return None
                    srv = doc.get('discord_server_id')
                    for c in cand:
                        try:
                            if srv is not None and int(c.get("discord_server_id")) == int(srv):
                                return str(int(c.get("discord_id")))
                        except Exception:
                            continue
                    # fallback to first candidate
                    try:
                        return str(int(cand[0].get("discord_id")))
                    except Exception:
                        return None
                return None

            for doc in all_stats:
                did_key = resolve_effective_did(doc)
                if not did_key:
                    # Still keep track of name-only entries under a pseudo key
                    nm = doc.get('player_name') or "Unknown"
                    did_key = f"name::{str(nm).strip()}"

                players[did_key]["melee_kills"]       += to_int(doc.get('Melee Kills'))
                players[did_key]["kills"]             += to_int(doc.get('Kills'))
                players[did_key]["deaths"]            += to_int(doc.get('Deaths'))
                players[did_key]["shots_fired"]       += to_int(doc.get('Shots Fired'))
                players[did_key]["shots_hit"]         += to_int(doc.get('Shots Hit'))
                players[did_key]["stims_used"]        += to_int(doc.get('Stims Used'))
                players[did_key]["samples_extracted"] += to_int(doc.get('Samples Extracted'))
                players[did_key]["stratagems_used"]   += to_int(doc.get('Stratagems Used'))
                players[did_key]["games_played"]      += 1

                # Track observed names for later fallback naming
                nm = doc.get('player_name')
                if isinstance(nm, str) and nm.strip():
                    players[did_key]["name_counts"][nm.strip()] += 1

                server_id = doc.get('discord_server_id')
                if server_id is not None:
                    try:
                        sid = int(server_id)
                        players[did_key]["server_counts"][sid] += 1
                    except Exception:
                        pass

            if not players:
                return []

            # Determine a primary server per Discord ID (the guild with most games this month)
            primary_server_for = {}
            for did_key, agg in players.items():
                if agg["server_counts"]:
                    # Pick the server with the highest games count; tie-breaker: lowest guild id
                    primary = sorted(agg["server_counts"].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
                    primary_server_for[did_key] = primary
                else:
                    primary_server_for[did_key] = None

            # Profiles were already fetched into profiles_by_did; reuse
            profiles = profiles_by_did

            def choose_profile(did_key: str):
                choices = profiles.get(did_key) or []
                if not choices:
                    return None
                primary_sid = primary_server_for.get(did_key)
                if primary_sid is not None:
                    for c in choices:
                        try:
                            if int(c.get("discord_server_id")) == int(primary_sid):
                                return c
                        except Exception:
                            pass
                return choices[0]

            leaderboard = []
            for did_key, agg in players.items():
                average_kills = (agg["kills"] / agg["games_played"]) if agg["games_played"] else 0.0
                average_accuracy = (agg["shots_hit"] / agg["shots_fired"] * 100) if agg["shots_fired"] > 0 else 0.0
                is_name_key = did_key.startswith("name::")
                prof = None if is_name_key else choose_profile(did_key)
                if prof is not None:
                    player_name = prof.get("player_name") or f"User {did_key}"
                else:
                    # Fallback to the most common observed name for this key
                    name_counts = players[did_key]["name_counts"]
                    if name_counts:
                        player_name = sorted(name_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
                    else:
                        player_name = did_key.replace("name::", "User ")
                ship_name = (prof.get("ship_name") if prof else None)
                discord_server_id = None
                try:
                    discord_server_id = int(prof.get("discord_server_id")) if prof and prof.get("discord_server_id") is not None else primary_server_for.get(did_key)
                except Exception:
                    discord_server_id = primary_server_for.get(did_key)

                leaderboard.append({
                    "player_name": player_name,
                    "melee_kills": agg["melee_kills"],
                    "kills": agg["kills"],
                    "deaths": agg["deaths"],
                    "shots_fired": agg["shots_fired"],
                    "shots_hit": agg["shots_hit"],
                    "stims_used": agg["stims_used"],
                    "samples_extracted": agg["samples_extracted"],
                    "stratagems_used": agg["stratagems_used"],
                    "games_played": agg["games_played"],
                    "Clan": (prof.get("server_name") if prof and prof.get("server_name") else (server_name_map.get(discord_server_id) if discord_server_id in server_name_map else "Unknown Clan")),
                    "average_kills": average_kills,
                    "average_accuracy": average_accuracy,
                    "least_deaths": -agg["deaths"],  # negative for sorting
                    "discord_id": None if is_name_key else did_key,
                    "discord_server_id": discord_server_id,
                    "ship_name": ship_name,
                })

            if stat_key == "least_deaths":
                leaderboard.sort(key=lambda x: (x[stat_key], -x["games_played"]))
            else:
                leaderboard.sort(key=lambda x: (-x[stat_key], -x["games_played"]))

            return leaderboard
        except Exception as e:
            logger.error(f"Error fetching leaderboard: {e}")
            return []

    async def build_leaderboard_embeds(self, leaderboard_data, title, stat_key):
        embeds = []
        # We add 2 static fields per embed (site link + promotion date),
        # so cap player fields at 23 to satisfy Discord's 25-field max.
        batch_size = 23

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

            # Promotion date at the very bottom
            try:
                # Compute the promotion/awards date (last day of current month in Chicago time)
                try:
                    tz = ZoneInfo("America/Chicago")
                except Exception:
                    tz = None
                now = datetime.now(tz) if tz else datetime.utcnow()
                if now.month == 12:
                    last = datetime(now.year + 1, 1, 1, tzinfo=tz) - timedelta(days=1)
                else:
                    last = datetime(now.year, now.month + 1, 1, tzinfo=tz) - timedelta(days=1)
                promo_str = last.strftime("Promotions awarded on %B %d, %Y")
                embed.add_field(name="Promotion Date", value=promo_str, inline=False)
            except Exception:
                pass

            # Footer about MVP award
            embed.set_footer(text="Rank #1 will win the @MVP role at the end of the month.")

            embeds.append(embed)

        return embeds

    async def maybe_award_submitter_medals(self, now_dt: datetime):
        """On the last day of the month, count submissions in the last 28 days by submitter and award roles.
        Uses stats.submitted_by_discord_id to attribute submissions. Idempotent per month per guild.
        """
        try:
            # Determine if it's the last day of the month (in America/Chicago for consistency with UI)
            try:
                tz = ZoneInfo("America/Chicago")
                now = now_dt.astimezone(tz)
            except Exception:
                now = now_dt
            if (now + timedelta(days=1)).month == now.month:
                return  # Not last day

            mongo = self.bot.mongo_db
            stats = mongo['User_Stats']
            server_listing = mongo['Server_Listing']

            yyyymm = now.strftime("%Y-%m")
            # For each guild, check if we already ran for this month
            guild_docs = await server_listing.find({}, {"discord_server_id": 1, "submitter_awarded_month": 1, "monitor_channel_id": 1}).to_list(None)
            guild_info = {int(d["discord_server_id"]): d for d in guild_docs if d.get("discord_server_id") is not None}

            # Time window: last 28 days
            window_start = (now_dt - timedelta(days=28)).replace(tzinfo=None)

            # Aggregate distinct missions by submitter per guild
            pipeline = [
                {"$match": {"submitted_at": {"$gte": window_start}, "submitted_by_discord_id": {"$ne": None}}},
                {"$group": {
                    "_id": "$mission_id",
                    "submitted_by_discord_id": {"$first": "$submitted_by_discord_id"},
                    "guild_id": {"$first": "$submitted_by_server_id"},
                }},
                {"$group": {
                    "_id": {"submitter": "$submitted_by_discord_id", "guild": "$guild_id"},
                    "missions": {"$sum": 1}
                }}
            ]
            results = await stats.aggregate(pipeline).to_list(None)

            # Per-guild role map and announcements
            for r in results:
                sub_id = r["_id"].get("submitter")
                guild_id = r["_id"].get("guild")
                count = int(r.get("missions", 0))
                if not sub_id or not guild_id:
                    continue
                guild_id = int(guild_id)
                doc = guild_info.get(guild_id)
                if doc and doc.get("submitter_awarded_month") == yyyymm:
                    # Already awarded this month for this guild; skip
                    continue

                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue
                member = guild.get_member(int(sub_id))
                if not member:
                    try:
                        member = await guild.fetch_member(int(sub_id))
                    except Exception:
                        member = None
                if not member:
                    continue

                # Determine which roles to assign based on tiers
                tier_roles = []
                if class_a_role_id is not None and count >= 5:
                    role = guild.get_role(int(class_a_role_id))
                    if role and role not in member.roles:
                        tier_roles.append(role)
                if gpt_achievement_medal_role_id is not None and count >= 10:
                    role = guild.get_role(int(gpt_achievement_medal_role_id))
                    if role and role not in member.roles:
                        tier_roles.append(role)
                if gpt_commendation_medal_role_id is not None and count >= 25:
                    role = guild.get_role(int(gpt_commendation_medal_role_id))
                    if role and role not in member.roles:
                        tier_roles.append(role)
                if gpt_bronze_star_medal_role_id is not None and count >= 50:
                    role = guild.get_role(int(gpt_bronze_star_medal_role_id))
                    if role and role not in member.roles:
                        tier_roles.append(role)
                if gpt_silver_star_medal_role_id is not None and count >= 100:
                    role = guild.get_role(int(gpt_silver_star_medal_role_id))
                    if role and role not in member.roles:
                        tier_roles.append(role)
                if gpt_medal_of_honor_role_id is not None and count >= 150:
                    role = guild.get_role(int(gpt_medal_of_honor_role_id))
                    if role and role not in member.roles:
                        tier_roles.append(role)

                if not tier_roles:
                    continue
                try:
                    await member.add_roles(*tier_roles, reason=f"Submitter awards for {count} missions in last 28 days")
                except Exception as e:
                    logger.warning(f"Failed to add award roles to {member} in {guild.name}: {e}")
                    continue

                # Announce in monitor channel if configured; else in leaderboard channel
                channel = None
                try:
                    mon_id = (doc or {}).get("monitor_channel_id")
                    if mon_id:
                        tmp = guild.get_channel(int(mon_id))
                        if isinstance(tmp, discord.TextChannel):
                            channel = tmp
                except Exception:
                    pass
                if channel is None:
                    channel = await self.ensure_leaderboard_channel(guild)

                if channel:
                    role_mentions = ", ".join([r.mention for r in tier_roles])
                    msg = (
                        f"Congrats {member.mention}! You earned {role_mentions} for submitting {count} mission(s) "
                        f"in the last 28 days. Awards are granted on the last day of each month."
                    )
                    try:
                        await channel.send(msg)
                    except Exception:
                        pass

                # Mark awarded for this month for the guild
                try:
                    await server_listing.update_one(
                        {"discord_server_id": guild_id},
                        {"$set": {"submitter_awarded_month": yyyymm, "submitter_awarded_at": datetime.utcnow()}},
                        upsert=True,
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"maybe_award_submitter_medals failed: {e}")

    async def maybe_award_mvp(self, now_dt: datetime, leaderboard_data: list[dict]):
        """On the last day of the month, award MVP to rank #1 per guild based on the leaderboard.
        Removes the MVP role from previous holder(s) in that guild.
        Idempotent per month per guild via Server_Listing.mvp_awarded_month.
        """
        try:
            if mvp_role_id is None:
                return
            # Check last day (America/Chicago)
            try:
                tz = ZoneInfo("America/Chicago")
                now = now_dt.astimezone(tz)
            except Exception:
                now = now_dt
            if (now + timedelta(days=1)).month == now.month:
                return  # Not last day

            mongo = self.bot.mongo_db
            server_listing = mongo['Server_Listing']
            yyyymm = now.strftime("%Y-%m")
            docs = await server_listing.find({}, {"discord_server_id": 1, "mvp_awarded_month": 1, "monitor_channel_id": 1}).to_list(None)
            awarded_map = {int(d["discord_server_id"]): d for d in docs if d.get("discord_server_id") is not None}

            # For each guild, find the first (highest ranked) entry belonging to that guild
            for guild in self.bot.guilds:
                prior = awarded_map.get(guild.id)
                if prior and prior.get("mvp_awarded_month") == yyyymm:
                    continue  # Already awarded this month

                # Find top-ranked entry for this guild in the already-sorted leaderboard_data
                top_entry = next((e for e in leaderboard_data if int(e.get("discord_server_id") or 0) == guild.id and e.get("discord_id")), None)
                if not top_entry:
                    continue
                try:
                    top_member_id = int(top_entry["discord_id"]) if isinstance(top_entry["discord_id"], str) else int(top_entry["discord_id"])
                except Exception:
                    continue
                member = guild.get_member(top_member_id)
                if not member:
                    try:
                        member = await guild.fetch_member(top_member_id)
                    except Exception:
                        member = None
                if not member:
                    continue

                # Resolve MVP role (prefer ID, fallback by name)
                role = guild.get_role(int(mvp_role_id)) if mvp_role_id is not None else None
                if role is None:
                    role = discord.utils.get(guild.roles, name="MVP")
                if role is None:
                    continue

                # Remove from previous holders in this guild (all role.members except the new member)
                try:
                    to_remove = [m for m in getattr(role, 'members', []) if m.id != member.id]
                    if to_remove:
                        await asyncio.gather(*[m.remove_roles(role, reason="MVP rotated on promotion day") for m in to_remove])
                except Exception:
                    pass

                # Assign to top member if not already
                if role not in member.roles:
                    try:
                        await member.add_roles(role, reason="MVP awarded for rank #1 on leaderboard")
                    except Exception:
                        continue

                # Announce
                channel = None
                try:
                    mon_id = (prior or {}).get("monitor_channel_id")
                    if mon_id:
                        tmp = guild.get_channel(int(mon_id))
                        if isinstance(tmp, discord.TextChannel):
                            channel = tmp
                except Exception:
                    pass
                if channel is None:
                    channel = await self.ensure_leaderboard_channel(guild)
                if channel:
                    try:
                        await channel.send(f"All hail {member.mention}, the new {role.mention} for {now.strftime('%B %Y')}!")
                    except Exception:
                        pass

                # Mark awarded for this month
                try:
                    await server_listing.update_one(
                        {"discord_server_id": guild.id},
                        {"$set": {"mvp_awarded_month": yyyymm, "mvp_awarded_at": datetime.utcnow()}},
                        upsert=True,
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"maybe_award_mvp failed: {e}")

async def setup(bot):
    if not hasattr(bot, 'mongo_db'):
        raise RuntimeError("LeaderboardCog requires bot.mongo_db to be initialized.")
    await bot.add_cog(LeaderboardCog(bot))





