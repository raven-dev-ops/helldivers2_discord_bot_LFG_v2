import pytest
from cogs import leaderboard_cog

class DummyRole:
    def __init__(self, role_id):
        self.id = role_id

class DummyMember:
    def __init__(self, member_id):
        self.id = member_id
        self.roles = []
    async def add_roles(self, role, reason=None):
        self.roles.append(role)

class DummyGuild:
    def __init__(self, guild_id, member, role):
        self.id = guild_id
        self._member = member
        self._role = role
    def get_member(self, member_id):
        return self._member if member_id == self._member.id else None
    def get_role(self, role_id):
        return self._role if role_id == self._role.id else None

class DummyBot:
    def __init__(self, guild):
        self._guild = guild
    def get_guild(self, guild_id):
        return self._guild if guild_id == self._guild.id else None

@pytest.mark.asyncio
async def test_promote_class_a_citizens_assigns_role():
    role_id = 999
    leaderboard_cog.class_a_role_id = role_id
    member = DummyMember(1)
    role = DummyRole(role_id)
    guild = DummyGuild(42, member, role)
    bot = DummyBot(guild)
    cog = leaderboard_cog.LeaderboardCog.__new__(leaderboard_cog.LeaderboardCog)
    cog.bot = bot
    data = [{"discord_id": "1", "discord_server_id": 42, "games_played": 3}]
    await leaderboard_cog.LeaderboardCog.promote_class_a_citizens(cog, data)
    assert role in member.roles
