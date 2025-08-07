# utils.py

import logging

# Configure logging
logger = logging.getLogger(__name__)

async def send_ephemeral(interaction, content):
    """Send an ephemeral message to the user."""
    try:
        await interaction.followup.send(content=content, ephemeral=True)
    except Exception as e:
        logger.error(f"Error sending ephemeral message: {e}")

async def log_to_monitor_channel(bot, message: str, level: int = logging.INFO):
    """Send a log message to the configured monitor channel, and also log locally."""
    try:
        # Lazy import to avoid hard failing when config env vars are not set during tests
        from config import monitor_channel_id
        logger.log(level, message)
        channel = bot.get_channel(monitor_channel_id)
        if channel is not None:
            await channel.send(message)
        else:
            logger.warning(f"Monitor channel with ID {monitor_channel_id} not found.")
    except Exception as e:
        logger.error(f"Failed to send log to monitor channel: {e}")
