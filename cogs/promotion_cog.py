from discord.ext import commands
import logging
from config import class_a_role_id, welcome_channel_id
from database import get_mongo_client

class PromotionCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Detect role changes and handle promotions."""
        try:
            logging.info(f"on_member_update triggered for {after.display_name}")
            if before.roles != after.roles:
                added_roles = set(after.roles) - set(before.roles)
                for role in added_roles:
                    await self.handle_role_assignment(after, role)
        except Exception as e:
            logging.error(f"Error handling role update: {e}")

    async def handle_role_assignment(self, member, role):
        """Handles promotions when a specific role is assigned."""
        try:
            logging.info(f"handle_role_assignment triggered for {member.display_name} with role ID: {role.id}")

            if role.id == class_a_role_id:
                completed_missions = await self.get_completed_missions(member)
                logging.info(f"Fetched completed missions for {member.display_name}: {completed_missions}")
                if completed_missions is not None:
                    welcome_channel = self.bot.get_channel(welcome_channel_id)
                    if welcome_channel:
                        await welcome_channel.send(
                            f"🎉 Congratulations {member.mention}! You have achieved **Class A Citizen** status by completing {completed_missions} missions! 🎉"

                        )
                        logging.info(f"Announced promotion for {member.display_name} in the welcome channel.")

        except Exception as e:
            logging.error(f"Error handling role assignment for {member.display_name}: {e}")

    async def get_completed_missions(self, member):
        """Fetch the number of completed missions for a user."""
        try:
            mongo_client = await get_mongo_client()
            db = mongo_client['GPTHellbot']
            stats_collection = db['User_Stats']
            count = await stats_collection.count_documents({
                "$or": [
                    {"discord_id": str(member.id)},
                    {"discord_id": member.id},
                ]
            })
            return count
        except Exception as e:
            logging.error(f"Error fetching completed missions: {e}")
            return 0

async def setup(bot):
    await bot.add_cog(PromotionCog(bot))
