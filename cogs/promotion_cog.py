import discord
from discord.ext import commands
import logging
from config import cadet_role_id, cadet_chat_id, class_a_role_id, welcome_channel_id
from database import get_mongo_client

class PromotionCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Detect role changes and handle promotions."""
        try:
            if before.roles != after.roles:
                added_roles = set(after.roles) - set(before.roles)
                for role in added_roles:
                    await self.handle_role_assignment(after, role)
        except Exception as e:
            logging.error(f"Error handling role update: {e}")

    async def handle_role_assignment(self, member, role):
        """Handles promotions when a specific role is assigned."""
        try:
            # Use variables directly from database.py
            if role.id == cadet_role_id:
                cadet_chat = self.bot.get_channel(cadet_chat_id)
                if cadet_chat:
                    await cadet_chat.send(
                        f"Welcome {member.mention} to the Officer Academy for GPT Fleet: Class #13! ✨ Your road to clan leadership begins here."
                    )
                    logging.info(f"Sent welcome message for {member.display_name} in the cadet chat.")

            if role.id == class_a_role_id:
                completed_missions = await self.fetch_completed_missions(member.id)
                if completed_missions is not None:
                    welcome_channel = self.bot.get_channel(welcome_channel_id)
                    if welcome_channel:
                        await welcome_channel.send(
                            f"🎉 Congratulations {member.mention}! You have achieved **Class A Citizen** status by completing {completed_missions} missions! 🎉"
                        )
                        logging.info(f"Announced promotion for {member.display_name} in the welcome channel.")

        except Exception as e:
            logging.error(f"Error handling role assignment for {member.display_name}: {e}")

    async def fetch_completed_missions(self, user_id):
        """Fetch the number of completed missions for a user."""
        try:
            mongo_client = await get_mongo_client()
            db = mongo_client['GPTHellbot']
            stats_collection = db['User_Stats']

            user_stats = await stats_collection.find_one({"user_id": str(user_id)})
            return user_stats.get('Completed_Missions', 0) if user_stats else None
        except Exception as e:
            logging.error(f"Error fetching completed missions for user {user_id}: {e}")
            return None

async def setup(bot):
    await bot.add_cog(PromotionCog(bot))
