import pytest
from cogs import leaderboard_cog


@pytest.mark.asyncio
async def test_leaderboard_embed_has_promotion_date():
    # Create a cog instance without running __init__ (avoids task loops)
    cog = leaderboard_cog.LeaderboardCog.__new__(leaderboard_cog.LeaderboardCog)
    # Minimal leaderboard data for one player
    leaderboard_data = [{
        "player_name": "Tester",
        "kills": 10,
        "shots_fired": 100,
        "shots_hit": 50,
        "deaths": 1,
        "melee_kills": 2,
        "stims_used": 3,
        "stratagems_used": 4,
        "games_played": 1,
        "discord_id": None,
        "discord_server_id": None,
        "ship_name": None,
    }]
    embeds = await leaderboard_cog.LeaderboardCog.build_leaderboard_embeds(
        cog,
        leaderboard_data,
        title="Test Leaderboard",
        stat_key="kills",
    )
    assert embeds, "No embeds were generated"
    # Check that at least one field is the Promotion Date field
    has_promo = any(any(f.name == "Promotion Date" for f in e.fields) for e in embeds)
    assert has_promo, "Promotion Date field missing from leaderboard embed"
