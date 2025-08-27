# config.py

from dotenv import load_dotenv
import os
import logging

# Load environment variables from the .env file
load_dotenv()

# Basic Bot/DB Configuration (unchanged)
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
MONGODB_URI = os.getenv('MONGODB_URI')
DATABASE_NAME = 'GPTHellbot'

# Configure structured logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Environment variable loader with validation
def load_env_var(var_name, required=True):
    value = os.getenv(var_name)
    if required and (value is None or value.strip() == ""):
        raise ValueError(f"Required environment variable '{var_name}' is not set")
    return value

# Mongo Collections
REGISTRATION_COLLECTION = 'Alliance'
STATS_COLLECTION = 'User_Stats'
SERVER_LISTING_COLLECTION = 'Server_Listing'

# OCR & Image-Processing Configs
TARGET_WIDTH = int(os.getenv('TARGET_WIDTH', '1920'))
TARGET_HEIGHT = int(os.getenv('TARGET_HEIGHT', '1080'))
PLAYER_OFFSET = int(os.getenv('PLAYER_OFFSET', '460'))
NUM_PLAYERS = int(os.getenv('NUM_PLAYERS', '4'))
ALLOWED_EXTENSIONS = ('.png', '.jpg', '.jpeg')
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

# OCR Matching
MATCH_SCORE_THRESHOLD = int(os.getenv('MATCH_SCORE_THRESHOLD', '50'))  # Lower = more tolerant

# Load environment variables
mongo_uri = os.getenv('MONGODB_URI')  # Optional here; main.py enforces
discord_token = os.getenv('DISCORD_TOKEN')  # Optional here; main.py enforces

# Optional IDs: provide safe defaults to avoid import-time failures.
# Components that need them should validate at runtime.
def _get_int_env(var_name: str, default: int | None = None) -> int | None:
    raw = os.getenv(var_name)
    if raw is None or raw.strip() == "":
        if default is None:
            logging.warning(f"Environment variable '{var_name}' is not set; defaulting to None.")
            return None
        logging.warning(f"Environment variable '{var_name}' is not set; defaulting to {default}.")
        return default
    try:
        return int(raw)
    except ValueError:
        logging.warning(f"Environment variable '{var_name}' has non-integer value '{raw}'; defaulting to {default}.")
        return default

class_b_role_id = _get_int_env('CLASS_B_ROLE_ID')
welcome_channel_id = _get_int_env('WELCOME_CHANNEL_ID')
monitor_channel_id = _get_int_env('MONITOR_CHANNEL_ID')
leaderboard_channel_id = _get_int_env('LEADERBOARD_CHANNEL_ID')
kia_channel_id = _get_int_env('KIA_CHANNEL_ID')
channel_id = _get_int_env('BOT_CHANNEL_ID')
class_a_role_id = _get_int_env('CLASS_A_ROLE_ID')
guild_id = _get_int_env('GUILD_ID')
sos_network_id = _get_int_env('SOS_NETWORK_ID')

# Notes:
# Some cogs (e.g., Extract) fetch server-specific IDs from the database,
# while other cogs still rely on environment variables above. This mixed
# approach is intentional for now and will be unified in a later refactor.

