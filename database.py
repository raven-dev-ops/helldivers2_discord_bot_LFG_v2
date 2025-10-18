import logging
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument
from typing import List, Dict, Any, Tuple, Optional
from config import (
    MONGODB_URI, DATABASE_NAME,
    REGISTRATION_COLLECTION, STATS_COLLECTION,
    SERVER_LISTING_COLLECTION
)
from rapidfuzz import fuzz
from datetime import datetime
from pymongo.errors import OperationFailure
import re

logger = logging.getLogger(__name__)

# MongoDB Client and Database
client = None  # Global client variable
_db = None     # Global db variable
registration_collection = None
stats_collection = None
server_listing_collection = None


def normalize_name(name: str) -> str:
    """
    Aggressive normalization for fuzzy player name matching:
    - Lowercase
    - Remove anything in <>
    - Remove leading/trailing numbers/underscores
    - Remove non-alphanumeric chars (keep only a-z, 0-9)
    """
    name = str(name).lower()
    # Remove anything in angle brackets, e.g. <#000>
    name = re.sub(r"<.*?>", "", name)
    # Remove leading/trailing numbers and underscores
    name = re.sub(r'^[\d_]+|[\d_]+$', '', name)
    # Remove all non-alphanumeric characters
    name = re.sub(r'[^a-z0-9]', '', name)
    return name

################################################
# MONGO CLIENT AND INDEX MANAGEMENT
################################################

async def get_mongo_client() -> AsyncIOMotorClient:
    """
    Initializes and returns the MongoDB client and binds collections.
    """
    global client, _db, registration_collection, stats_collection, server_listing_collection
    if client is None:
        client = AsyncIOMotorClient(MONGODB_URI)
        _db = client[DATABASE_NAME]
        registration_collection = _db[REGISTRATION_COLLECTION]
        stats_collection = _db[STATS_COLLECTION]
        server_listing_collection = _db[SERVER_LISTING_COLLECTION]
        logger.info("MongoDB client and collections initialized.")
    return client

async def create_indexes():
    """
    Ensures necessary indexes are created on startup.
    """
    try:
        await get_mongo_client()

        # Enforce numeric typing for discord identifiers while allowing legacy docs
        try:
            validator_command = {
                "collMod": REGISTRATION_COLLECTION,
                "validator": {
                    "$jsonSchema": {
                        "bsonType": "object",
                        "required": ["discord_id", "discord_server_id"],
                        "properties": {
                            "discord_id": {"bsonType": ["long", "int"]},
                            "discord_server_id": {"bsonType": ["long", "int"]}
                        }
                    }
                },
                "validationLevel": "moderate",
                "validationAction": "error"
            }
            await _db.command(validator_command)
            logger.info("Alliance collection validator ensured.")
        except OperationFailure as oe:
            if oe.code == 26:  # NamespaceNotFound
                logger.info("Alliance collection missing; creating before applying validator.")
                await _db.create_collection(REGISTRATION_COLLECTION)
                await _db.command(validator_command)
                logger.info("Alliance collection validator applied after collection creation.")
            else:
                logger.warning(f"Could not apply Alliance collection validator: {oe}")
        except Exception as e:
            logger.warning(f"Unexpected error applying Alliance validator: {e}")

        # Stats collection: index useful fields we actually query/sort on
        await _db[STATS_COLLECTION].create_index("player_name")
        await _db[STATS_COLLECTION].create_index("submitted_at")
        await _db[STATS_COLLECTION].create_index("submitted_by_discord_id")
        await _db[STATS_COLLECTION].create_index("discord_id")
        await _db[STATS_COLLECTION].create_index("discord_server_id")
        await _db[STATS_COLLECTION].create_index("mission_id")

        # Registration & server listing
        await _db[REGISTRATION_COLLECTION].create_index("player_name")
        await _db[REGISTRATION_COLLECTION].create_index("discord_id")
        await _db[REGISTRATION_COLLECTION].create_index("discord_server_id")
        await _db[REGISTRATION_COLLECTION].create_index(
            [("discord_id", 1), ("discord_server_id", 1)],
            name="uix_discord_user_server",
            unique=True
        )
        await _db[SERVER_LISTING_COLLECTION].create_index("discord_server_id")

        logger.info("MongoDB indexes created/ensured.")
    except Exception as e:
        logger.error(f"Error creating MongoDB indexes: {e}")

################################################
# SERVER LISTING LOOKUPS
################################################

async def get_server_listing_by_id(discord_server_id: int) -> Optional[Dict[str, Any]]:
    """
    Returns the Server_Listing doc for the given guild ID, or None if not found.
    """
    try:
        await get_mongo_client()
        doc = await server_listing_collection.find_one({"discord_server_id": discord_server_id})
        if doc:
            logger.debug(f"Fetched Server_Listing for guild {discord_server_id}: {doc}")
        return doc
    except Exception as e:
        logger.error(f"Error fetching Server_Listing for ID {discord_server_id}: {e}")
        return None

################################################
# PLAYER REGISTRATION
################################################

async def get_registered_users() -> List[Dict[str, Any]]:
    """
    Fetch all users in the Alliance registration collection.
    """
    try:
        await get_mongo_client()
        docs = await registration_collection.find(
            {},
            {"player_name": 1, "discord_id": 1, "discord_server_id": 1, "_id": 0}
        ).to_list(length=None)
        logger.info(f"Retrieved {len(docs)} registered users.")
        return docs
    except Exception as e:
        logger.error(f"Error fetching registered users: {e}")
        return []

async def get_registered_user_by_discord_id(discord_id: int) -> Optional[Dict[str, Any]]:
    """
    Find a user in the Alliance collection by their discord_id.
    """
    try:
        await get_mongo_client()
        doc = await registration_collection.find_one(
            {"discord_id": discord_id},
            {"player_name": 1, "_id": 0}
        )
        if doc:
            logger.info(f"Found registered user for discord_id {discord_id}: {doc.get('player_name','Unknown')}")
        else:
            logger.warning(f"No registered user found for discord_id {discord_id}")
        return doc
    except Exception as e:
        logger.error(f"Error fetching user for discord_id {discord_id}: {e}")
        return None

async def upsert_registered_user(discord_id: int, discord_server_id: int, player_name: str) -> bool:
    """
    Create or update a registration entry in the Alliance collection.
    Ensures (discord_id, discord_server_id) unique pair and sets the player_name.
    """
    try:
        await get_mongo_client()
        filt = {"discord_id": int(discord_id), "discord_server_id": int(discord_server_id)}
        update = {"$set": {"player_name": str(player_name)}}
        await registration_collection.update_one(filt, update, upsert=True)
        logger.info(f"Upserted registration for discord_id={discord_id} in server {discord_server_id} as '{player_name}'.")
        return True
    except Exception as e:
        logger.error(f"Failed to upsert registration for discord_id={discord_id}, server={discord_server_id}: {e}")
        return False

################################################
# FUZZY MATCHING (LENGTH-AWARE + RATIO)
################################################

def find_best_match(
    ocr_name: str,
    registered_names: List[str],
    threshold: int = 80,  # Stricter threshold
    min_len: int = 3
) -> Tuple[Optional[str], Optional[float]]:
    """
    Fuzzy match `ocr_name` against the list of `registered_names` (normalized).
    Only considers matches within ±3 length AND with length ratio between 0.75 and 1.25.
    Uses both partial_ratio and token_sort_ratio. No substring fallback.
    """
    if not ocr_name or not registered_names:
        return None, None

    ocr_name_norm = normalize_name(ocr_name.strip())
    logger.debug(f"Attempting to find best match for OCR name '{ocr_name}' (normalized '{ocr_name_norm}')")

    norm_name_map = {normalize_name(n): n for n in registered_names}
    norm_db_names = []
    for n in norm_name_map.keys():
        abs_len_diff = abs(len(n) - len(ocr_name_norm))
        length_ratio = len(n) / len(ocr_name_norm) if len(ocr_name_norm) > 0 else 1.0
        # Accept if within ±3 chars AND ratio between 0.75–1.25
        if abs_len_diff <= 3 and 0.75 <= length_ratio <= 1.25:
            norm_db_names.append(n)

    # Exact match (normalized)
    for n in norm_db_names:
        if ocr_name_norm == n:
            logger.info(f"Exact match: '{ocr_name}' == '{norm_name_map[n]}'")
            return norm_name_map[n], 100.0

    # For very short names, only allow exact match
    if len(ocr_name_norm) < min_len:
        logger.info(f"Name '{ocr_name}' too short for fuzzy matching.")
        return None, None

    # Fuzzy matching using both partial_ratio and token_sort_ratio
    candidates = []
    for n in norm_db_names:
        pr_score = fuzz.partial_ratio(ocr_name_norm, n)
        ts_score = fuzz.token_sort_ratio(ocr_name_norm, n)
        max_score = max(pr_score, ts_score)
        candidates.append((n, max_score))

    matches = [(norm_name_map[m[0]], m[1]) for m in candidates if m[1] >= threshold]
    if matches:
        matches.sort(key=lambda x: -x[1])
        logger.info(f"Fuzzy match for '{ocr_name}': '{matches[0][0]}' with score {matches[0][1]}")
        return matches[0][0], matches[0][1]

    logger.info(f"No good fuzzy match found for '{ocr_name}'.")
    return None, None

################################################
# STATS INSERTION
################################################

async def _get_next_mission_id() -> int:
    """
    Returns the next sequential mission_id, seeded to start at 7100719.
    Robust against transient update conflicts; falls back to max()+1 if needed.
    """
    await get_mongo_client()
    counters = _db['Counters']
    seed_value = 7100718  # so the first increment becomes 7100719

    # Up to 3 attempts for a clean atomic increment
    for attempt in range(3):
        try:
            # Ensure seed doc exists (no conflict with $inc)
            await counters.update_one({"_id": "mission_id"}, {"$setOnInsert": {"seq": seed_value}}, upsert=True)
            # Atomically increment and return new value
            counter_doc = await counters.find_one_and_update(
                {"_id": "mission_id"},
                {"$inc": {"seq": 1}},
                return_document=ReturnDocument.AFTER,
            )
            mission_id = int(counter_doc.get("seq", seed_value + 1)) if counter_doc else seed_value + 1
            # Enforce minimum starting value
            if mission_id < (seed_value + 1):
                counter_doc = await counters.find_one_and_update(
                    {"_id": "mission_id"},
                    {"$max": {"seq": seed_value + 1}},
                    return_document=ReturnDocument.AFTER,
                )
                mission_id = int(counter_doc.get("seq", seed_value + 1)) if counter_doc else seed_value + 1
            return mission_id
        except Exception as e:
            logger.warning(f"Attempt {attempt+1}/3 to increment mission counter failed: {e}")

    # Fallback: derive from existing stats (last mission_id) + 1
    try:
        doc = await stats_collection.find({}, {"mission_id": 1}).sort("mission_id", -1).limit(1).to_list(length=1)
        last = int(doc[0]["mission_id"]) if doc else seed_value
        mission_id = max(last, seed_value) + 1
        # Try to push counter up to the derived mission_id to keep things in sync
        try:
            await counters.update_one({"_id": "mission_id"}, {"$max": {"seq": mission_id}}, upsert=True)
        except Exception:
            pass
        logger.info(f"Derived next mission_id={mission_id} from stats fallback.")
        return mission_id
    except Exception as e:
        logger.error(f"Failed to derive mission id from stats fallback: {e}")
        # As an absolute last resort, return the seed+1 to keep sequence valid
        return seed_value + 1


async def insert_player_data(
    players_data: List[Dict[str, Any]],
    submitted_by: str,
    submitter_discord_id: int | None = None,
    submitter_server_id: int | None = None,
):
    """
    Insert each player's stats data into the stats_collection.
    Assigns an auto-incrementing mission_id shared by all players in this submission.
    Returns the mission_id used.
    """
    await get_mongo_client()
    # Get next sequential mission id (robust)
    mission_id = await _get_next_mission_id()

    for player in players_data:
        doc = {
            "player_name": player.get("player_name", "Unknown"),
            "Kills": player.get("Kills", "N/A"),
            "Accuracy": player.get("Accuracy", "N/A"),
            "Shots Fired": player.get("Shots Fired", "N/A"),
            "Shots Hit": player.get("Shots Hit", "N/A"),
            "Deaths": player.get("Deaths", "N/A"),
            "Melee Kills": player.get("Melee Kills", "N/A"),
            # NEW FIELDS
            "Stims Used": player.get("Stims Used", "N/A"),
            "Samples Extracted": player.get("Samples Extracted", "N/A"),
            "Stratagems Used": player.get("Stratagems Used", "N/A"),

            "discord_id": str(player.get("discord_id")) if player.get("discord_id") is not None else None,
            "discord_server_id": player.get("discord_server_id", None),
            "clan_name": player.get("clan_name", "N/A"),
            "submitted_by": submitted_by,
            "submitted_by_discord_id": int(submitter_discord_id) if submitter_discord_id is not None else None,
            "submitted_by_server_id": int(submitter_server_id) if submitter_server_id is not None else None,
            "submitted_at": datetime.utcnow(),
            "mission_id": mission_id,
        }
        try:
            await stats_collection.insert_one(doc)
            logger.info(f"Inserted player data for {doc['player_name']} (mission #{mission_id}), submitted by {submitted_by}.")
        except Exception as e:
            logger.error(f"Failed to insert player data for {doc.get('player_name','Unknown')}: {e}")
    return mission_id

################################################
# MISSION QUERIES/UPDATES
################################################

async def get_mission_docs(mission_id: int) -> List[Dict[str, Any]]:
    try:
        await get_mongo_client()
        docs = await stats_collection.find({"mission_id": int(mission_id)}).to_list(None)
        return docs
    except Exception as e:
        logger.error(f"Error fetching mission #{mission_id}: {e}")
        return []

async def update_mission_player_fields(mission_id: int, player_name: str, updates: Dict[str, Any]) -> bool:
    """
    Update one player's fields for a mission. Recomputes Accuracy if shots changed.
    """
    try:
        await get_mongo_client()
        doc = await stats_collection.find_one({"mission_id": int(mission_id), "player_name": player_name})
        if not doc:
            return False
        # Normalize numeric fields
        def to_int(v, default=0):
            try:
                return int(float(v))
            except Exception:
                return default
        sf = to_int(updates.get("Shots Fired", doc.get("Shots Fired", 0)), 0)
        sh = to_int(updates.get("Shots Hit", doc.get("Shots Hit", 0)), 0)
        if sh > sf:
            sh = sf
        # Recompute accuracy
        acc = (sh / sf * 100) if sf > 0 else 0
        updates = dict(updates)
        updates["Shots Fired"] = sf
        updates["Shots Hit"] = sh
        updates["Accuracy"] = f"{min(acc, 100.0):.1f}%"
        await stats_collection.update_one({"_id": doc["_id"]}, {"$set": updates})
        return True
    except Exception as e:
        logger.error(f"Error updating mission #{mission_id} for player {player_name}: {e}")
        return False

async def count_user_missions(discord_id: int) -> int:
    """Count missions completed by a specific Discord user."""
    try:
        await get_mongo_client()
        return await stats_collection.count_documents({
            "$or": [
                {"discord_id": str(discord_id)},
                {"discord_id": discord_id},
            ]
        })
    except Exception as e:
        logger.error(f"Error counting missions for user {discord_id}: {e}")
        return 0

################################################
# CLAN NAME LOOKUP
################################################

async def get_clan_name_by_discord_server_id(discord_server_id: Any) -> str:
    """
    Look up 'discord_server_name' from 'Server_Listing' by discord_server_id.
    """
    if not discord_server_id:
        return "N/A"
    try:
        await get_mongo_client()
        int_server_id = int(discord_server_id)
        doc = await server_listing_collection.find_one({"discord_server_id": int_server_id})
        if doc and "discord_server_name" in doc:
            return doc["discord_server_name"]
        return "N/A"
    except Exception as e:
        logger.error(f"Error fetching clan name for server_id {discord_server_id}: {e}")
        return "N/A"
