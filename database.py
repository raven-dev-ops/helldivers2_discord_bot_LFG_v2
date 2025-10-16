import logging
from motor.motor_asyncio import AsyncIOMotorClient
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
        await _db[STATS_COLLECTION].create_index("discord_id")
        await _db[STATS_COLLECTION].create_index("discord_server_id")

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

async def insert_player_data(players_data: List[Dict[str, Any]], submitted_by: str):
    """
    Insert each player's stats data into the stats_collection.
    """
    await get_mongo_client()
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
            "submitted_at": datetime.utcnow()
        }
        try:
            await stats_collection.insert_one(doc)
            logger.info(f"Inserted player data for {doc['player_name']}, submitted by {submitted_by}.")
        except Exception as e:
            logger.error(f"Failed to insert player data for {doc.get('player_name','Unknown')}: {e}")

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
