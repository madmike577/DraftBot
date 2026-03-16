import discord
from discord import app_commands
import requests
import asyncio
import json
import os
import datetime
from collections import Counter
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
FOOTBALL_DATA_TOKEN = os.getenv('FOOTBALL_DATA_TOKEN')
BALLDONTLIE_TOKEN = os.getenv('BALLDONTLIE_TOKEN')

LEAGUES_DIR = 'leagues'
USER_AGENT = 'BracktDraftNotify/1.0'
POLL_INTERVAL = 20

os.makedirs(LEAGUES_DIR, exist_ok=True)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Admin commands — hidden from regular users via manage_guild permission
brackt = app_commands.Group(
    name="bradmin",
    description="Brackt Draft Bot admin commands",
    default_permissions=discord.Permissions(manage_guild=True)
)
tree.add_command(brackt)

# Public read commands — visible to everyone
brackt_public = app_commands.Group(
    name="brackt",
    description="Brackt Draft Bot commands"
)
tree.add_command(brackt_public)

# --- SHARED IN-MEMORY CACHE ---
# Single source of truth for the polling loop and commands that modify league state.
# Loaded on startup, kept in sync by all write operations.
leagues_cache: dict[int, dict] = {}

def update_cache(channel_id: int, league: dict):
    """Update both the in-memory cache and persist to disk."""
    leagues_cache[channel_id] = league
    save_league(channel_id, league)

# --- LEAGUE DATA MANAGEMENT ---

def league_file(channel_id: int) -> str:
    return os.path.join(LEAGUES_DIR, f'{channel_id}.json')

def load_league(channel_id: int) -> dict | None:
    path = league_file(channel_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f'Error loading league {channel_id}: {e}')
        return None

def save_league(channel_id: int, data: dict):
    path = league_file(channel_id)
    try:
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f'Error saving league {channel_id}: {e}')

def default_league(channel_id: int, admin_id: int) -> dict:
    return {
        'channel_id': channel_id,
        'admin_id': admin_id,
        'api_url': None,
        'total_rounds': 20,
        'flex_spots': 4,
        'required_sports': [],
        'players': {},
        'handles': {},
        'draft_order': [],
        'pick_history': [],
        'team_rosters': {},
        'current_pick': 1,
        'last_known_pick': 0,
        'api_available': False,
        'using_sample_data': False,
        'draft_was_paused': False,
        'draft_active': True,
        'league_name': None
    }

def is_admin(league: dict, user_id: int) -> bool:
    return league['admin_id'] == user_id

def get_num_teams(league: dict) -> int:
    return len(league['draft_order'])

def get_total_picks(league: dict) -> int:
    return get_num_teams(league) * league['total_rounds']

def league_display_name(league: dict) -> str:
    """Return the league name if set, otherwise fall back to channel ID."""
    return league.get('league_name') or f'Channel {league["channel_id"]}'

# --- DRAFT LOGIC ---

def get_team_for_pick(league: dict, pick_number: int) -> str | None:
    order = league['draft_order']
    if not order:
        return None
    n = len(order)
    pick_index = pick_number - 1
    round_number = pick_index // n
    position = pick_index % n
    if round_number % 2 == 0:
        return order[position]
    else:
        return order[n - 1 - position]

def get_next_pick_username(league: dict, pick_number: int) -> str | None:
    """Return the username for the pick AFTER pick_number. Returns None if at end of draft."""
    total = get_total_picks(league)
    next_pick = pick_number + 1
    if next_pick > total:
        return None
    return get_team_for_pick(league, next_pick)

def format_pick_number(league: dict, overall: int) -> tuple:
    n = get_num_teams(league)
    if n == 0:
        return f'Pick {overall}', 1
    round_num = ((overall - 1) // n) + 1
    pick_in_round = ((overall - 1) % n) + 1
    return f'{round_num}.{pick_in_round:02d}', round_num

def mention(league: dict, brackt_username: str) -> str:
    if not brackt_username:
        return 'Unknown'
    user_id = league['players'].get(brackt_username)
    if user_id:
        return f'<@{user_id}>'
    return f'**{league["handles"].get(brackt_username, brackt_username)}**'

def get_missing_sports(league: dict, brackt_username: str) -> list:
    roster = league['team_rosters'].get(brackt_username, [])
    drafted_sports = [p['sport'] for p in roster]
    return [s for s in league['required_sports'] if s not in drafted_sports]

def get_flex_remaining(league: dict, brackt_username: str) -> int:
    roster = league['team_rosters'].get(brackt_username, [])
    drafted_sports = [p['sport'] for p in roster]
    required_filled = sum(1 for s in league['required_sports'] if s in drafted_sports)
    flex_used = len(roster) - required_filled
    return max(0, league['flex_spots'] - flex_used)

def mode_label(league: dict) -> str:
    if league.get('api_available') and not league.get('using_sample_data'):
        return '🟢 Live API'
    return '🟡 Saved state (API unavailable)'

def is_ephemeral(display: str) -> bool:
    return display == "private"

DISPLAY_CHOICES = [
    app_commands.Choice(name="public", value="public"),
    app_commands.Choice(name="private", value="private")
]

# --- API ---

def fetch_draft_state(league: dict) -> dict | None:
    if not league.get('api_url'):
        return None
    headers = {'User-Agent': USER_AGENT}
    try:
        response = requests.get(league['api_url'], headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            print(f'API returned {response.status_code} for league {league["channel_id"]}')
            return None
    except Exception as e:
        print(f'API fetch error for league {league["channel_id"]}: {e}')
        return None

def sync_from_api(league: dict, data: dict):
    """
    Rebuild pick history and rosters from API data.
    Does NOT modify last_known_pick — caller is responsible for setting that.
    """
    league['current_pick'] = data['currentPickNumber']
    league['pick_history'] = []
    league['team_rosters'] = {t: [] for t in league['draft_order']}
    for pick in data['picks']:
        username = pick['username']
        entry = {
            'pick': pick['pickNumber'],
            'round': pick['round'],
            'team': username,
            'player': pick['participantName'],
            'sport': pick['sport']
        }
        league['pick_history'].append(entry)
        if username in league['team_rosters']:
            league['team_rosters'][username].append({
                'pick': pick['pickNumber'],
                'player': pick['participantName'],
                'sport': pick['sport']
            })
    league['api_available'] = True
    league['using_sample_data'] = False

# --- SHARED GUARDS ---

async def no_league_response(interaction: discord.Interaction):
    await interaction.response.send_message(
        '❌ No league configured in this channel. '
        'A server admin must run `/bradmin setup` first.',
        ephemeral=True
    )

async def not_league_admin_response(interaction: discord.Interaction):
    await interaction.response.send_message(
        '❌ Only the league admin can use this command. '
        'Ask the current admin to run `/bradmin admintransfer @you` if needed.',
        ephemeral=True
    )

async def draft_inactive_response(interaction: discord.Interaction):
    await interaction.response.send_message(
        '📋 The draft for this league is complete. Draft commands are disabled.',
        ephemeral=True
    )

def check_league_and_admin(interaction: discord.Interaction) -> tuple[dict | None, bool]:
    """Load league from disk and check admin. Returns (league, is_league_admin)."""
    league = load_league(interaction.channel_id)
    if not league:
        return None, False
    return league, is_admin(league, interaction.user.id)

# --- AUTOCOMPLETE ---

async def brackt_username_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> list[app_commands.Choice[str]]:
    league = load_league(interaction.channel_id)
    if not league or not league.get('draft_order'):
        return []
    choices = []
    for username in league['draft_order']:
        handle = league['handles'].get(username, username)
        display = f'{handle} ({username})'
        if current.lower() in username.lower() or current.lower() in handle.lower():
            choices.append(app_commands.Choice(name=display, value=username))
    return choices[:25]

# --- ADMIN COMMANDS ---

@brackt.command(name="setup", description="Initialize a new league in this channel")
async def setup(interaction: discord.Interaction):
    # Double-check server permission as a safety net
    if not interaction.user.guild_permissions.manage_guild and \
       not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            '❌ You need **Manage Server** or **Administrator** permission to run this.',
            ephemeral=True
        )
        return
    channel_id = interaction.channel_id
    existing = load_league(channel_id)
    if existing:
        await interaction.response.send_message(
            '⚠️ A league is already configured in this channel. '
            'Use `/bradmin adminsettings` to view current settings.',
            ephemeral=True
        )
        return
    league = default_league(channel_id, interaction.user.id)
    update_cache(channel_id, league)
    await interaction.response.send_message(
        f'✅ **League initialized!** You ({interaction.user.mention}) are the league admin.\n\n'
        f'**Recommended setup order:**\n'
        f'1️⃣ `/bradmin setapi [url]` — Connect your brackt.com draft\n'
        f'2️⃣ `/bradmin setrounds [n]` — Set total rounds (default: 20)\n'
        f'3️⃣ `/bradmin setflex [n]` — Set flex spots (default: 4)\n'
        f'4️⃣ `/bradmin addplayer [username] [@user]` — Map each player\n'
        f'5️⃣ `/bradmin setdraftorder [u1,u2,...]` — Set snake draft order\n'
        f'6️⃣ `/bradmin syncnow` — Pull live data and auto-populate sports\n'
        f'\n💡 `/bradmin addsport` is available for new drafts with no picks yet.',
        ephemeral=True
    )

@brackt.command(name="setapi", description="Set the brackt.com API URL for this league")
@app_commands.describe(url="The brackt.com draft API URL")
async def setapi(interaction: discord.Interaction, url: str):
    league, admin = check_league_and_admin(interaction)
    if not league:
        await no_league_response(interaction); return
    if not admin:
        await not_league_admin_response(interaction); return
    if not url.startswith('https://www.brackt.com/api/'):
        await interaction.response.send_message(
            '❌ URL does not look like a valid brackt.com API URL. '
            'It should start with `https://www.brackt.com/api/`',
            ephemeral=True
        )
        return
    league['api_url'] = url
    update_cache(interaction.channel_id, league)
    await interaction.response.send_message(
        '✅ API URL set. Run `/bradmin syncnow` to pull current draft data.',
        ephemeral=True
    )

@brackt.command(name="setrounds", description="Set total number of rounds")
@app_commands.describe(rounds="Total number of rounds in the draft")
async def setrounds(interaction: discord.Interaction, rounds: int):
    league, admin = check_league_and_admin(interaction)
    if not league:
        await no_league_response(interaction); return
    if not admin:
        await not_league_admin_response(interaction); return
    if rounds < 1 or rounds > 100:
        await interaction.response.send_message(
            '❌ Rounds must be between 1 and 100.', ephemeral=True
        )
        return
    league['total_rounds'] = rounds
    update_cache(interaction.channel_id, league)
    await interaction.response.send_message(
        f'✅ Total rounds set to **{rounds}**.', ephemeral=True
    )

@brackt.command(name="setflex", description="Set number of flex spots per team")
@app_commands.describe(spots="Number of flex spots")
async def setflex(interaction: discord.Interaction, spots: int):
    league, admin = check_league_and_admin(interaction)
    if not league:
        await no_league_response(interaction); return
    if not admin:
        await not_league_admin_response(interaction); return
    if spots < 0 or spots > 20:
        await interaction.response.send_message(
            '❌ Flex spots must be between 0 and 20.', ephemeral=True
        )
        return
    league['flex_spots'] = spots
    update_cache(interaction.channel_id, league)
    await interaction.response.send_message(
        f'✅ Flex spots set to **{spots}**.', ephemeral=True
    )

@brackt.command(name="addsport", description="Add a required sport to this league")
@app_commands.describe(sport="Sport name exactly as it appears on brackt.com")
async def addsport(interaction: discord.Interaction, sport: str):
    league, admin = check_league_and_admin(interaction)
    if not league:
        await no_league_response(interaction); return
    if not admin:
        await not_league_admin_response(interaction); return
    sport = sport.strip()
    if not sport:
        await interaction.response.send_message('❌ Sport name cannot be empty.', ephemeral=True)
        return
    if sport in league['required_sports']:
        await interaction.response.send_message(
            f'⚠️ **{sport}** is already in the required sports list.', ephemeral=True
        )
        return
    league['required_sports'].append(sport)
    update_cache(interaction.channel_id, league)
    await interaction.response.send_message(
        f'✅ Added **{sport}**. ({len(league["required_sports"])} required sports total)',
        ephemeral=True
    )

@brackt.command(name="removesport", description="Remove a required sport from this league")
@app_commands.describe(sport="Sport name to remove")
async def removesport(interaction: discord.Interaction, sport: str):
    league, admin = check_league_and_admin(interaction)
    if not league:
        await no_league_response(interaction); return
    if not admin:
        await not_league_admin_response(interaction); return
    if sport not in league['required_sports']:
        await interaction.response.send_message(
            f'❌ **{sport}** is not in the required sports list.', ephemeral=True
        )
        return
    league['required_sports'].remove(sport)
    update_cache(interaction.channel_id, league)
    await interaction.response.send_message(
        f'✅ Removed **{sport}**.', ephemeral=True
    )

@brackt.command(name="addplayer", description="Map a brackt.com username to a Discord user")
@app_commands.describe(
    brackt_username="The player's brackt.com username",
    discord_user="The player's Discord account"
)
async def addplayer(interaction: discord.Interaction, brackt_username: str, discord_user: discord.Member):
    league, admin = check_league_and_admin(interaction)
    if not league:
        await no_league_response(interaction); return
    if not admin:
        await not_league_admin_response(interaction); return
    brackt_username = brackt_username.strip()
    if not brackt_username:
        await interaction.response.send_message('❌ Brackt username cannot be empty.', ephemeral=True)
        return
    if discord_user.bot:
        await interaction.response.send_message(
            '❌ Cannot map a brackt username to a bot account.', ephemeral=True
        )
        return
    league['players'][brackt_username] = str(discord_user.id)
    league['handles'][brackt_username] = discord_user.display_name
    if brackt_username not in league['team_rosters']:
        league['team_rosters'][brackt_username] = []
    update_cache(interaction.channel_id, league)
    await interaction.response.send_message(
        f'✅ Mapped **{brackt_username}** → {discord_user.mention}', ephemeral=True
    )

@brackt.command(name="removeplayer", description="Remove a player mapping")
@app_commands.describe(brackt_username="The brackt.com username to remove")
async def removeplayer(interaction: discord.Interaction, brackt_username: str):
    league, admin = check_league_and_admin(interaction)
    if not league:
        await no_league_response(interaction); return
    if not admin:
        await not_league_admin_response(interaction); return
    if brackt_username not in league['players']:
        await interaction.response.send_message(
            f'❌ **{brackt_username}** not found in player list.', ephemeral=True
        )
        return
    league['players'].pop(brackt_username)
    league['handles'].pop(brackt_username, None)
    update_cache(interaction.channel_id, league)
    await interaction.response.send_message(
        f'✅ Removed **{brackt_username}**.', ephemeral=True
    )

@brackt.command(name="setdraftorder", description="Set the snake draft order (comma separated brackt usernames)")
@app_commands.describe(order="Comma separated brackt usernames in pick order. Example: jom315,arny7,Madmike")
async def setdraftorder(interaction: discord.Interaction, order: str):
    league, admin = check_league_and_admin(interaction)
    if not league:
        await no_league_response(interaction); return
    if not admin:
        await not_league_admin_response(interaction); return
    draft_order = [u.strip() for u in order.split(',') if u.strip()]
    if len(draft_order) < 2:
        await interaction.response.send_message(
            '❌ Please provide at least 2 usernames separated by commas.', ephemeral=True
        )
        return
    if len(draft_order) != len(set(draft_order)):
        await interaction.response.send_message(
            '❌ Duplicate usernames detected. Each team should appear once.', ephemeral=True
        )
        return
    unknown = [u for u in draft_order if u not in league['players']]
    for u in draft_order:
        if u not in league['team_rosters']:
            league['team_rosters'][u] = []
    league['draft_order'] = draft_order
    update_cache(interaction.channel_id, league)
    order_text = '\n'.join([f'{i+1}. {u}' for i, u in enumerate(draft_order)])
    warning = (
        f'\n\n⚠️ These usernames are not yet mapped to Discord users: '
        f'{", ".join(f"`{u}`" for u in unknown)}'
    ) if unknown else ''
    await interaction.response.send_message(
        f'✅ Draft order set ({len(draft_order)} teams):\n{order_text}{warning}',
        ephemeral=True
    )

@brackt.command(name="syncnow", description="Manually sync draft state from brackt.com API")
async def syncnow(interaction: discord.Interaction):
    league, admin = check_league_and_admin(interaction)
    if not league:
        await no_league_response(interaction); return
    if not admin:
        await not_league_admin_response(interaction); return
    if not league.get('api_url'):
        await interaction.response.send_message(
            '❌ No API URL set. Run `/bradmin setapi [url]` first.', ephemeral=True
        )
        return
    await interaction.response.defer(ephemeral=True)
    data = fetch_draft_state(league)
    if data is None:
        await interaction.followup.send(
            '❌ Could not reach the brackt.com API. Check the URL or try again later.',
            ephemeral=True
        )
        return

    # Auto-populate draft order from API if not yet set
    if not league.get('draft_order'):
        seen = []
        for pick in sorted(data['picks'], key=lambda x: x['pickNumber']):
            if pick['username'] not in seen:
                seen.append(pick['username'])
        league['draft_order'] = seen
        for u in seen:
            if u not in league['team_rosters']:
                league['team_rosters'][u] = []
        print(f'Auto-populated draft order for league {league["channel_id"]}: {seen}')

    # Auto-populate required sports from API if not yet set
    sports_populated = False
    if not league.get('required_sports'):
        seen_sports = []
        for pick in data['picks']:
            if pick['sport'] not in seen_sports:
                seen_sports.append(pick['sport'])
        league['required_sports'] = sorted(seen_sports)
        sports_populated = True
        print(f'Auto-populated {len(seen_sports)} sports for league {league["channel_id"]}')

    # Preserve last_known_pick so polling loop can detect future picks correctly
    preserved_last_known = league.get('last_known_pick', 0)
    sync_from_api(league, data)
    # On first sync (last_known is 0), set to current - 1 so next pick gets announced
    # On subsequent syncs, preserve existing last_known so no picks are skipped
    if preserved_last_known == 0:
        league['last_known_pick'] = data['currentPickNumber'] - 1
    else:
        league['last_known_pick'] = preserved_last_known

    update_cache(interaction.channel_id, league)

    sports_note = (
        f'\n📋 **{len(league["required_sports"])} required sports auto-populated** from pick history.'
        if sports_populated else ''
    )
    await interaction.followup.send(
        f'✅ Synced! **{len(league["pick_history"])} picks** loaded, '
        f'currently at pick **{league["current_pick"]}** of **{get_total_picks(league)}**.\n'
        f'On the clock: {mention(league, get_team_for_pick(league, league["current_pick"]))}'
        f'{sports_note}',
        ephemeral=True
    )

@brackt.command(name="admintransfer", description="Transfer league admin role to another user")
@app_commands.describe(new_admin="The Discord user to transfer admin to")
async def admintransfer(interaction: discord.Interaction, new_admin: discord.Member):
    league, admin = check_league_and_admin(interaction)
    if not league:
        await no_league_response(interaction); return
    if not admin:
        await not_league_admin_response(interaction); return
    if new_admin.bot:
        await interaction.response.send_message(
            '❌ Cannot transfer admin to a bot account.', ephemeral=True
        )
        return
    if new_admin.id == interaction.user.id:
        await interaction.response.send_message(
            '❌ You are already the admin.', ephemeral=True
        )
        return
    league['admin_id'] = new_admin.id
    update_cache(interaction.channel_id, league)
    await interaction.response.send_message(
        f'✅ Admin role transferred to {new_admin.mention}.', ephemeral=True
    )

@brackt.command(name="adminsettings", description="View current league configuration")
async def adminsettings(interaction: discord.Interaction):
    league, admin = check_league_and_admin(interaction)
    if not league:
        await no_league_response(interaction); return
    if not admin:
        await not_league_admin_response(interaction); return
    players_text = '\n'.join(
        [f'  {u} → <@{uid}>' for u, uid in league['players'].items()]
    ) or '  None configured'
    sports_text = '\n'.join(
        [f'  • {s}' for s in league['required_sports']]
    ) or '  None configured'
    order_text = ', '.join(league['draft_order']) or 'Not set'
    msg = (
        f'⚙️ **League Settings**\n\n'
        f'**API URL:** `{league["api_url"] or "Not set"}`\n'
        f'**Total Rounds:** {league["total_rounds"]}\n'
        f'**Flex Spots:** {league["flex_spots"]}\n'
        f'**Teams:** {get_num_teams(league)}\n'
        f'**Total Picks:** {get_total_picks(league)}\n'
        f'**Current Pick:** {league["current_pick"]}\n'
        f'**Draft Active:** {"✅ Yes" if league.get("draft_active", True) else "🔴 No (disabled)"}\n'
        f'**Status:** {mode_label(league)}\n\n'
        f'**League Name:** {league.get("league_name") or "Not set"}\n'
        f'**Draft Order:** {order_text}\n\n'
        f'**Players ({len(league["players"])}):**\n{players_text}\n\n'
        f'**Required Sports ({len(league["required_sports"])}):**\n{sports_text}'
    )
    await interaction.response.send_message(msg, ephemeral=True)

@brackt.command(name="setname", description="Set a display name for this league")
@app_commands.describe(name="The league name e.g. Diablo, Rumble, Omnifantasy")
async def setname(interaction: discord.Interaction, name: str):
    league, admin = check_league_and_admin(interaction)
    if not league:
        await no_league_response(interaction); return
    if not admin:
        await not_league_admin_response(interaction); return
    name = name.strip()
    if not name:
        await interaction.response.send_message('❌ League name cannot be empty.', ephemeral=True)
        return
    if len(name) > 32:
        await interaction.response.send_message('❌ League name must be 32 characters or fewer.', ephemeral=True)
        return
    league['league_name'] = name
    update_cache(interaction.channel_id, league)
    await interaction.response.send_message(
        f'✅ League name set to **{name}**.', ephemeral=True
    )

@brackt.command(name="draftstatus", description="Enable or disable draft commands for this league")
@app_commands.describe(status="Enable or disable draft commands")
@app_commands.choices(status=[
    app_commands.Choice(name="enable", value="enable"),
    app_commands.Choice(name="disable", value="disable"),
])
async def draftstatus(interaction: discord.Interaction, status: str):
    league, admin = check_league_and_admin(interaction)
    if not league:
        await no_league_response(interaction); return
    if not admin:
        await not_league_admin_response(interaction); return
    league['draft_active'] = (status == 'enable')
    update_cache(interaction.channel_id, league)
    state = '✅ enabled' if league['draft_active'] else '🔴 disabled'
    await interaction.response.send_message(
        f'Draft commands are now **{state}**.\n'
        f'Affected commands: `/brackt onclock`, `/brackt last5`, `/brackt status`',
        ephemeral=True
    )

@brackt.command(name="adminpick", description="Manually record a pick")
@app_commands.describe(
    player="Team or player name being picked",
    sport="Sport of the pick — must match brackt.com exactly",
    brackt_username="Start typing a team name or brackt username (leave blank for current pick)"
)
@app_commands.autocomplete(brackt_username=brackt_username_autocomplete)
async def adminpick(interaction: discord.Interaction, player: str, sport: str, brackt_username: str = None):
    league, admin = check_league_and_admin(interaction)
    if not league:
        await no_league_response(interaction); return
    if not admin:
        await not_league_admin_response(interaction); return
    if not league['draft_order']:
        await interaction.response.send_message(
            '❌ Draft order not set. Use `/bradmin setdraftorder` first.', ephemeral=True
        )
        return

    player = player.strip()
    sport = sport.strip()

    if not player or not sport:
        await interaction.response.send_message(
            '❌ Player and sport cannot be empty.', ephemeral=True
        )
        return

    # Validate flex picks
    if league['required_sports'] and sport not in league['required_sports']:
        target_team = brackt_username or get_team_for_pick(league, league['current_pick'])
        remaining_flex = get_flex_remaining(league, target_team)
        if remaining_flex <= 0:
            await interaction.response.send_message(
                f'❌ **{sport}** is not a required sport and this team has no flex spots remaining.',
                ephemeral=True
            )
            return

    team = brackt_username if brackt_username else get_team_for_pick(league, league['current_pick'])
    if not team:
        await interaction.response.send_message(
            '❌ Could not determine team for this pick.', ephemeral=True
        )
        return
    if brackt_username and brackt_username not in league['draft_order']:
        await interaction.response.send_message(
            f'❌ **{brackt_username}** is not in the draft order.', ephemeral=True
        )
        return
    if team not in league['team_rosters']:
        league['team_rosters'][team] = []

    formatted, _ = format_pick_number(league, league['current_pick'])
    pick_entry = {
        'pick': league['current_pick'],
        'round': ((league['current_pick'] - 1) // get_num_teams(league)) + 1,
        'team': team,
        'player': player,
        'sport': sport
    }
    league['pick_history'].append(pick_entry)
    league['team_rosters'][team].append({
        'pick': league['current_pick'],
        'player': player,
        'sport': sport
    })

    league['last_known_pick'] = league['current_pick'] - 1
    league['current_pick'] += 1
    next_team = get_team_for_pick(league, league['current_pick'])
    on_deck_team = get_team_for_pick(league, league['current_pick'] + 1)
    on_deck = f'\n📋 **On Deck:** {mention(league, on_deck_team)}' if on_deck_team else ''

    # Update cache so polling loop won't double-announce this pick
    update_cache(interaction.channel_id, league)

    channel = client.get_channel(interaction.channel_id)
    await channel.send(
        f'━━━━━━━━━━━━━━━━━━━━━━\n'
        f'✅ **Pick {formatted}** — {mention(league, team)}\n'
        f'**{player}** · {sport}\n'
        f'━━━━━━━━━━━━━━━━━━━━━━\n'
        f'🕐 **On the Clock:** {mention(league, next_team)}'
        f'{on_deck}'
    )
    await interaction.response.send_message(
        f'✅ Pick recorded: **{player}** ({sport}) for '
        f'**{league["handles"].get(team, team)}**',
        ephemeral=True
    )

@brackt.command(name="nbaids", description="Fetch and log all balldontlie NBA team IDs for verification")
async def nbaids(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_guild and \
       not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ Admin only.', ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    try:
        resp = requests.get(
            f'{BDL_BASE}/teams',
            headers=bdl_headers(),
            params={'per_page': 35},
            timeout=10
        )
        if resp.status_code != 200:
            await interaction.followup.send(f'❌ API error {resp.status_code}', ephemeral=True)
            return
        teams = resp.json().get('data', [])
        lines = ['**balldontlie NBA Team IDs:**\n```']
        for t in sorted(teams, key=lambda x: x['full_name']):
            marker = ' ← OUR TEAMS' if t['full_name'] in NBA_TEAM_IDS else ''
            lines.append(f'{t["id"]:3d}  {t["full_name"]}{marker}')
        lines.append('```')
        # Also log to console for easy copy-paste
        print('=== BDL TEAM IDS ===')
        for t in sorted(teams, key=lambda x: x['id']):
            print(f'  {t["id"]:3d}  {t["full_name"]}')
        print('===================')
        await interaction.followup.send('\n'.join(lines), ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f'❌ Error: {e}', ephemeral=True)

# --- UCL FIXTURE DATA ---

UCL_COMPETITION_ID = 'CL'

# Maps brackt.com club names to football-data.org club names
UCL_NAME_MAP = {
    'Arsenal': 'Arsenal FC',
    'Bayern Munich': 'FC Bayern München',
    'Barcelona': 'FC Barcelona',
    'Paris Saint-Germain': 'Paris Saint-Germain FC',
    'Manchester City': 'Manchester City FC',
    'Liverpool': 'Liverpool FC',
    'Chelsea': 'Chelsea FC',
    'Atlético Madrid': 'Club Atlético de Madrid',
    'Newcastle United': 'Newcastle United FC',
    'Tottenham Hotspur': 'Tottenham Hotspur FC',
    'Real Madrid': 'Real Madrid CF',
    'Galatasaray': 'Galatasaray SK',
    'Atalanta': 'Atalanta BC',
    'Bayer Leverkusen': 'Bayer 04 Leverkusen',
    'Bodø/Glimt': 'FK Bodø/Glimt',
    'Sporting CP': 'Sporting Clube de Portugal',
}
# Reverse map: API name → brackt name
UCL_REVERSE_MAP = {v: k for k, v in UCL_NAME_MAP.items()}

def fetch_ucl_fixtures() -> list | None:
    """
    Fetch UCL knockout matches from football-data.org.
    Automatically detects the current active stage so no manual updates
    are needed as the tournament progresses each round or season.
    """
    if not FOOTBALL_DATA_TOKEN:
        return None
    try:
        response = requests.get(
            f'https://api.football-data.org/v4/competitions/{UCL_COMPETITION_ID}/matches',
            headers={'X-Auth-Token': FOOTBALL_DATA_TOKEN},
            timeout=10
        )
        if response.status_code != 200:
            print(f'football-data.org returned {response.status_code}')
            return None
        matches = response.json().get('matches', [])

        # Knockout stage order — used to find the current active round
        KNOCKOUT_STAGE_ORDER = [
            'LAST_16', 'QUARTER_FINALS', 'SEMI_FINALS', 'FINAL'
        ]
        knockout_stages = set(KNOCKOUT_STAGE_ORDER)

        # Group matches by stage, only considering knockout rounds
        by_stage: dict[str, list] = {}
        for m in matches:
            stage = m.get('stage', '')
            if stage in knockout_stages:
                by_stage.setdefault(stage, []).append(m)

        # Current stage = earliest knockout stage that isn't fully finished
        current_stage = None
        for stage in KNOCKOUT_STAGE_ORDER:
            stage_matches = by_stage.get(stage, [])
            if not stage_matches:
                continue
            if any(m.get('status') != 'FINISHED' for m in stage_matches):
                current_stage = stage
                break

        if not current_stage:
            # All knockout stages finished — return Final matches
            for stage in reversed(KNOCKOUT_STAGE_ORDER):
                if stage in by_stage:
                    current_stage = stage
                    break

        if not current_stage:
            return []

        print(f'UCL current stage detected: {current_stage}')
        # Tag each match with the detected stage so callers can adapt formatting
        stage_matches = by_stage[current_stage]
        for m in stage_matches:
            m['_detected_stage'] = current_stage
        return stage_matches

    except Exception as e:
        print(f'UCL fixture fetch error: {e}')
        return None

def ucl_pick_owner(league: dict, brackt_name: str) -> str | None:
    """Return the display handle of the manager who owns a UCL club."""
    for p in league['pick_history']:
        if p['sport'] == 'UEFA Champions League' and p['player'] == brackt_name:
            return league['handles'].get(p['team'], p['team'])
    return None

def match_score(match: dict, team_key: str):
    """Extract full-time score for 'home' or 'away' from a match dict. Returns None if not finished."""
    if not match or match.get('status') != 'FINISHED':
        return None
    s = match.get('score', {}).get('fullTime', {})
    return s.get('home') if team_key == 'home' else s.get('away')

def build_ucl_matchups(league: dict, matches: list) -> list:
    """
    Group UCL matches into two-leg ties and compute aggregate scores.
    Returns a list of tie dicts sorted by next relevant date.
    """
    # Set of API club names that were drafted
    drafted = {
        UCL_NAME_MAP.get(p['player'], p['player'])
        for p in league['pick_history']
        if p['sport'] == 'UEFA Champions League'
    }

    # Group matches into ties keyed by frozenset of the two club API names
    ties: dict = {}
    for m in matches:
        home = m['homeTeam']['name']
        away = m['awayTeam']['name']
        key = frozenset([home, away])
        if key not in ties:
            ties[key] = []
        ties[key].append(m)

    result = []
    for key, legs in ties.items():
        legs = sorted(legs, key=lambda x: x['utcDate'])
        home_api = legs[0]['homeTeam']['name']
        away_api = legs[0]['awayTeam']['name']
        home_brackt = UCL_REVERSE_MAP.get(home_api, home_api)
        away_brackt = UCL_REVERSE_MAP.get(away_api, away_api)

        # Only include ties where at least one club was drafted
        if home_api not in drafted and away_api not in drafted:
            continue

        home_owner = ucl_pick_owner(league, home_brackt)
        away_owner = ucl_pick_owner(league, away_brackt)

        leg1 = legs[0] if len(legs) > 0 else None
        leg2 = legs[1] if len(legs) > 1 else None
        is_final = leg1 and leg1.get('_detected_stage') == 'FINAL'

        # Leg 1: home/away from leg 1 perspective
        l1_home = match_score(leg1, 'home')
        l1_away = match_score(leg1, 'away')
        l1_played = l1_home is not None

        # Leg 2 swaps home/away clubs relative to leg 1
        l2_home = match_score(leg2, 'home')  # leg1 away club scores in leg2
        l2_away = match_score(leg2, 'away')  # leg1 home club scores in leg2
        l2_played = l2_home is not None

        # Aggregate from leg1 home club perspective
        agg_home = (l1_home or 0) + (l2_away or 0)
        agg_away = (l1_away or 0) + (l2_home or 0)

        # Next relevant date for sorting
        if leg2 and leg2['status'] != 'FINISHED':
            next_date = leg2['utcDate']
        elif leg1 and leg1['status'] != 'FINISHED':
            next_date = leg1['utcDate']
        else:
            next_date = leg2['utcDate'] if leg2 else leg1['utcDate']

        result.append({
            'home_brackt': home_brackt,
            'away_brackt': away_brackt,
            'home_owner': home_owner,
            'away_owner': away_owner,
            'leg1': leg1,
            'leg2': leg2,
            'l1_home': l1_home,
            'l1_away': l1_away,
            'l2_home': l2_home,
            'l2_away': l2_away,
            'l1_played': l1_played,
            'l2_played': l2_played,
            'agg_home': agg_home,
            'agg_away': agg_away,
            'next_date': next_date,
            'is_final': is_final,
        })

    return sorted(result, key=lambda x: x['next_date'])

def format_ucl_tie(t: dict) -> str:
    """Format a single UCL two-leg tie (or Final) into a Discord message block."""
    home = t['home_brackt']
    away = t['away_brackt']
    home_o = f" ({t['home_owner']})" if t['home_owner'] else ''
    away_o = f" ({t['away_owner']})" if t['away_owner'] else ''
    is_final = t.get('is_final', False)

    if is_final:
        # Single match — no aggregate, no legs
        if t['l1_played']:
            # Final is done
            h, a = t['l1_home'], t['l1_away']
            if h > a:
                return f'🏆 **{home}{home_o}** are Champions! Beat **{away}{away_o}** {h}–{a}'
            elif a > h:
                return f'🏆 **{away}{away_o}** are Champions! Beat **{home}{home_o}** {a}–{h}'
            else:
                return f'🏆 **{home}{home_o}** vs **{away}{away_o}** — {h}–{h} (decided by pens)'
        else:
            # Final upcoming
            leg1_ts = int(datetime.datetime.fromisoformat(
                t['leg1']['utcDate'].replace('Z', '+00:00')).timestamp()) if t['leg1'] else None
            date_str = f'<t:{leg1_ts}:F>' if leg1_ts else 'TBD'
            return (
                f'🏆 **UCL Final:** **{home}{home_o}** vs **{away}{away_o}**\n'
                f'   {date_str}'
            )

    if t['l2_played']:
        # Both legs done — show winner
        agg_home = t['agg_home']
        agg_away = t['agg_away']
        if agg_home > agg_away:
            winner, loser = home, away
            winner_o, loser_o = home_o, away_o
            agg_w, agg_l = agg_home, agg_away
        elif agg_away > agg_home:
            winner, loser = away, home
            winner_o, loser_o = away_o, home_o
            agg_w, agg_l = agg_away, agg_home
        else:
            # Level on aggregate — went to extra time/penalties
            return (
                f'✅ **{home}{home_o}** vs **{away}{away_o}** — '
                f'{agg_home}–{agg_away} agg (decided by extra time/pens)'
            )
        return (
            f'✅ **{winner}{winner_o}** beat **{loser}{loser_o}** '
            f'{agg_w}–{agg_l} on aggregate'
        )

    elif t['l1_played']:
        # Leg 1 done, leg 2 upcoming
        leg2_ts = int(datetime.datetime.fromisoformat(
            t['leg2']['utcDate'].replace('Z', '+00:00')).timestamp()) if t['leg2'] else None
        date_str = f'<t:{leg2_ts}:F>' if leg2_ts else 'TBD'
        if t['l1_home'] > t['l1_away']:
            lead_str = f'{home} leads {t["l1_home"]}–{t["l1_away"]} from leg 1'
        elif t['l1_away'] > t['l1_home']:
            lead_str = f'{away} leads {t["l1_away"]}–{t["l1_home"]} from leg 1'
        else:
            lead_str = f'Level {t["l1_home"]}–{t["l1_away"]} from leg 1'
        return (
            f'⏳ **{home}{home_o}** vs **{away}{away_o}**\n'
            f'   Leg 2: {date_str} · {lead_str}'
        )
    else:
        # Neither leg played
        leg1_ts = int(datetime.datetime.fromisoformat(
            t['leg1']['utcDate'].replace('Z', '+00:00')).timestamp()) if t['leg1'] else None
        date_str = f'<t:{leg1_ts}:F>' if leg1_ts else 'TBD'
        return (
            f'🔜 **{home}{home_o}** vs **{away}{away_o}**\n'
            f'   Leg 1: {date_str}'
        )

# --- NBA FIXTURE DATA ---

BDL_BASE = 'https://api.balldontlie.io/v1'
NBA_SEASON = 2025

# Play-in tournament window — update each season
# Games dated within this range that are tagged postseason=true are play-in games
NBA_PLAYIN_START = datetime.date(2026, 4, 14)
NBA_PLAYIN_END   = datetime.date(2026, 4, 17)

# Game IDs for NBA Cup (In-Season Tournament) finals — not counted in regular season W/L record.
# Add the new final's game ID each season.
NBA_CUP_GAME_IDS = {
    20377171,  # 2025-26 NBA Cup Final: Knicks vs Spurs, Dec 16 2025
}  # 2025 = 2025-26 season

# Maps brackt.com NBA team names to balldontlie full_name
NBA_NAME_MAP = {
    'Boston Celtics':          'Boston Celtics',
    'Charlotte Hornets':       'Charlotte Hornets',
    'Cleveland Cavaliers':     'Cleveland Cavaliers',
    'Denver Nuggets':          'Denver Nuggets',
    'Detroit Pistons':         'Detroit Pistons',
    'Golden State Warriors':   'Golden State Warriors',
    'Houston Rockets':         'Houston Rockets',
    'LA Lakers':               'Los Angeles Lakers',
    'Miami Heat':              'Miami Heat',
    'Minnesota Timberwolves':  'Minnesota Timberwolves',
    'New York Knicks':         'New York Knicks',
    'Oklahoma City Thunder':   'Oklahoma City Thunder',
    'Orlando Magic':           'Orlando Magic',
    'Philadelphia 76ers':      'Philadelphia 76ers',
    'Phoenix Suns':            'Phoenix Suns',
    'San Antonio Spurs':       'San Antonio Spurs',
    'Toronto Raptors':         'Toronto Raptors',
}

# Stable balldontlie team IDs
NBA_TEAM_IDS = {
    'Boston Celtics': 2,
    'Charlotte Hornets': 4,
    'Cleveland Cavaliers': 6,
    'Denver Nuggets': 7,
    'Detroit Pistons': 8,
    'Golden State Warriors': 10,
    'Houston Rockets': 11,
    'Los Angeles Lakers': 14,
    'Miami Heat': 16,
    'Minnesota Timberwolves': 18,
    'New York Knicks': 20,
    'Oklahoma City Thunder': 21,
    'Orlando Magic': 22,
    'Philadelphia 76ers': 23,
    'Phoenix Suns': 24,
    'San Antonio Spurs': 27,
    'Toronto Raptors': 28,
}

def bdl_headers() -> dict:
    return {'Authorization': BALLDONTLIE_TOKEN or ''}

def brackt_to_bdl_name(brackt_name: str) -> str:
    return NBA_NAME_MAP.get(brackt_name, brackt_name)

def bdl_name_to_team_id(bdl_name: str) -> int | None:
    return NBA_TEAM_IDS.get(bdl_name)

def is_game_live(status: str) -> bool:
    if not status or status == 'Final':
        return False
    try:
        datetime.datetime.fromisoformat(status.replace('Z', '+00:00'))
        return False
    except ValueError:
        pass
    return True

def bdl_get(params: dict) -> dict | None:
    resp = requests.get(f'{BDL_BASE}/games', headers=bdl_headers(), params=params, timeout=10)
    if resp.status_code == 429:
        print(f'BDL rate limit hit')
        return None
    if resp.status_code != 200:
        print(f'BDL error {resp.status_code}')
        return None
    return resp.json()

def fetch_nba_team_data(team_id: int) -> dict | None:
    """
    Fetch everything needed for nextmatch in exactly 2 API calls:
      Call 1 — completed regular season games (record)
      Call 2 — today and upcoming games (live status + next game)
    Returns dict with keys: wins, losses, live_game, next_game, or None on failure.
    """
    team_id = int(team_id)
    today = datetime.date.today()
    yesterday = (today - datetime.timedelta(days=1)).isoformat()
    today_str = today.isoformat()

    # --- Call 1: record from completed games up to yesterday ---
    wins = 0
    losses = 0
    seen_ids = set()
    cursor = None
    while True:
        params = {
            'team_ids[]': team_id,
            'postseason': 'false',
            'start_date': f'{NBA_SEASON}-10-01',
            'end_date': yesterday,
            'per_page': 100,
        }
        if cursor:
            params['cursor'] = cursor
        data = bdl_get(params)
        if data is None:
            return None
        for g in data['data']:
            if g['status'] != 'Final':
                continue
            if g['id'] in NBA_CUP_GAME_IDS:
                continue
            if g['id'] in seen_ids:
                continue
            seen_ids.add(g['id'])
            home_id = int(g['home_team']['id'])
            if home_id == team_id:
                if g['home_team_score'] > g['visitor_team_score']:
                    wins += 1
                else:
                    losses += 1
            else:
                if g['visitor_team_score'] > g['home_team_score']:
                    wins += 1
                else:
                    losses += 1
        cursor = data.get('meta', {}).get('next_cursor')
        if not cursor:
            break

    # --- Call 2: today and upcoming games (live + next game) ---
    data2 = bdl_get({
        'team_ids[]': team_id,
        'postseason': 'false',
        'start_date': today_str,
        'per_page': 10,
    })
    live_game = None
    next_game = None
    if data2:
        for g in data2['data']:
            if is_game_live(g.get('status', '')):
                live_game = g
                break
        upcoming = [g for g in data2['data'] if g['status'] != 'Final']
        if upcoming:
            upcoming.sort(key=lambda g: g.get('datetime') or g.get('date') or '')
            next_game = upcoming[0]

    return {'wins': wins, 'losses': losses, 'live_game': live_game, 'next_game': next_game}

def fetch_nba_postseason_games() -> list | None:
    """Fetch all postseason games. Used to detect whether playoffs have started."""
    try:
        data = bdl_get({'seasons[]': NBA_SEASON, 'postseason': 'true', 'per_page': 100})
        if data is None:
            return None
        return data.get('data', [])
    except Exception as e:
        print(f'fetch_nba_postseason_games error: {e}')
        return None

def format_nba_datetime(game: dict) -> str:
    """Return a Discord local timestamp string for a game, or a plain date fallback."""
    dt_str = game.get('datetime') or game.get('date')
    if not dt_str:
        return 'TBD'
    try:
        if 'T' in dt_str:
            dt = datetime.datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            return f'<t:{int(dt.timestamp())}:F>'
        else:
            return dt_str
    except Exception:
        return dt_str

def format_nba_game_line(game: dict, team_id: int) -> str:
    """Format a single NBA game as 'vs/@ Opponent — <timestamp or live score>'."""
    home = game['home_team']
    visitor = game['visitor_team']
    team_id = int(team_id)
    if int(home['id']) == team_id:
        opponent = visitor['full_name']
        location = 'vs'
        team_score = game.get('home_team_score', 0)
        opp_score = game.get('visitor_team_score', 0)
    else:
        opponent = home['full_name']
        location = '@'
        team_score = game.get('visitor_team_score', 0)
        opp_score = game.get('home_team_score', 0)
    status = game.get('status', '')
    # Live game — show current score and period
    if is_game_live(status):
        score_str = f'{team_score}–{opp_score}' if team_score or opp_score else ''
        score_part = f' ({score_str})' if score_str else ''
        return f'{location} {opponent}{score_part} · {status}'
    return f'{location} {opponent} — {format_nba_datetime(game)}'

def game_is_playin(game: dict) -> bool:
    """Return True if a postseason game falls within the play-in tournament window."""
    date_str = game.get('date') or (game.get('datetime') or '')[:10]
    if not date_str:
        return False
    try:
        game_date = datetime.date.fromisoformat(date_str)
        return NBA_PLAYIN_START <= game_date <= NBA_PLAYIN_END
    except ValueError:
        return False

def build_nba_series(games: list, team_id: int) -> dict | None:
    """
    Given a list of postseason games for a team, determine current series status.
    Returns a dict with opponent, wins, losses, next_game, is_eliminated.
    Returns None if no games found.
    """
    if not games:
        return None

    # Find the opponent in the most recent/current series
    opponent_counts = Counter()
    for g in games:
        if g['home_team']['id'] == team_id:
            opp = g['visitor_team']['full_name']
        else:
            opp = g['home_team']['full_name']
        opponent_counts[opp] += 1

    # Current opponent = most recent game's opponent
    games_sorted = sorted(games, key=lambda g: g.get('datetime') or g.get('date') or '')
    current_opp = None
    if games_sorted[-1]['home_team']['id'] == team_id:
        current_opp = games_sorted[-1]['visitor_team']['full_name']
    else:
        current_opp = games_sorted[-1]['home_team']['full_name']

    series_games = [g for g in games if
        g['home_team']['full_name'] == current_opp or
        g['visitor_team']['full_name'] == current_opp
    ]

    team_wins = 0
    opp_wins = 0
    for g in series_games:
        if g['status'] != 'Final':
            continue
        if g['home_team']['id'] == team_id:
            if g['home_team_score'] > g['visitor_team_score']:
                team_wins += 1
            else:
                opp_wins += 1
        else:
            if g['visitor_team_score'] > g['home_team_score']:
                team_wins += 1
            else:
                opp_wins += 1

    is_eliminated = opp_wins == 4
    series_over = team_wins == 4 or opp_wins == 4

    next_game = None
    if not series_over:
        upcoming = [g for g in series_games if g['status'] != 'Final']
        if upcoming:
            upcoming.sort(key=lambda g: g.get('datetime') or g.get('date') or '')
            next_game = upcoming[0]

    # Series label
    if team_wins > opp_wins:
        if team_wins == 4:
            series_label = f'Won series 4–{opp_wins}'
        else:
            series_label = f'Lead series {team_wins}–{opp_wins}'
    elif opp_wins > team_wins:
        if opp_wins == 4:
            series_label = f'Lost series {team_wins}–4'
        else:
            series_label = f'Trail series {team_wins}–{opp_wins}'
    else:
        series_label = f'Series tied {team_wins}–{opp_wins}'

    return {
        'opponent': current_opp,
        'team_wins': team_wins,
        'opp_wins': opp_wins,
        'series_label': series_label,
        'next_game': next_game,
        'is_eliminated': is_eliminated,
        'series_over': series_over,
    }


# --- F1 FIXTURE DATA ---

OPENF1_BASE = 'https://api.openf1.org/v1'
F1_SEASON = 2026

# Races cancelled mid-season — excluded from schedule and race count.
# Add meeting_name strings exactly as they appear in OpenF1 data.
F1_CANCELLED_RACES = {
    'Bahrain Grand Prix',       # Cancelled due to Middle East conflict
    'Saudi Arabian Grand Prix', # Cancelled due to Middle East conflict
}

# Maps brackt.com driver names to 2026 F1 driver numbers (update each season)
# Driver numbers are stable within a season
F1_DRIVER_NUMBERS = {
    'Max Verstappen':        3,
    'Lando Norris':          1,
    'Charles Leclerc':      16,
    'Lewis Hamilton':       44,
    'George Russell':       63,
    'Oscar Piastri':        81,
    'Carlos Sainz':         55,
    'Fernando Alonso':      14,
    'Pierre Gasly':         10,
    'Esteban Ocon':         31,
    'Lance Stroll':         18,
    'Alex Albon':           23,
    'Liam Lawson':          30,
    'Isack Hadjar':          6,
    'Andrea Kimi Antonelli':12,
    'Oliver Bearman':       87,
    'Arvid Lindblad':       41,
    'Gabriel Bortoleto':     5,
    'Nico Hülkenberg':      27,
    'Franco Colapinto':     43,
    'Sergio Perez':         11,
    'Valtteri Bottas':      77,
}

def f1_driver_number(brackt_name: str) -> int | None:
    """Return the 2026 driver number for a brackt.com driver name."""
    return F1_DRIVER_NUMBERS.get(brackt_name)

def openf1_get(endpoint: str, params: dict = None) -> list | None:
    """GET request to OpenF1 API. Returns list of results or None on error."""
    try:
        resp = requests.get(
            f'{OPENF1_BASE}/{endpoint}',
            params=params or {},
            timeout=10
        )
        if resp.status_code == 429:
            print(f'OpenF1 rate limit hit: {endpoint}')
            return None
        if resp.status_code != 200:
            print(f'OpenF1 error {resp.status_code}: {endpoint}')
            return None
        return resp.json()
    except Exception as e:
        print(f'OpenF1 fetch error ({endpoint}): {e}')
        return None

def fetch_f1_meetings() -> list | None:
    """
    Fetch all F1 race meetings for the current season, sorted by date.
    Excludes cancelled races and pre-season testing.
    """
    meetings = openf1_get('meetings', {'year': F1_SEASON})
    if meetings is None:
        return None
    races = [
        m for m in meetings
        if 'Grand Prix' in m.get('meeting_name', '')
        and m.get('meeting_name') not in F1_CANCELLED_RACES
    ]
    races.sort(key=lambda m: m.get('date_start', ''))
    return races

def fetch_f1_race_session_time(meeting_key: int) -> str | None:
    """
    Fetch the exact race start time for a meeting from the Sessions endpoint.
    Returns a Discord timestamp string or None on failure.
    One API call — only use for nextmatch where precision matters.
    """
    sessions = openf1_get('sessions', {
        'meeting_key': meeting_key,
        'session_type': 'Race',
    })
    if not sessions:
        return None
    race = sessions[0]
    date_str = race.get('date_start', '')
    if not date_str:
        return None
    try:
        dt = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return f'<t:{int(dt.timestamp())}:F>'
    except ValueError:
        return None

def meeting_race_date_ts(meeting: dict) -> str:
    """
    Return a Discord date-only timestamp for a meeting's race day,
    derived from date_end (Sunday) without an extra API call.
    Used by /schedule for the next 3 GPs list.
    """
    date_str = meeting.get('date_end', '') or meeting.get('date_start', '')
    if not date_str:
        return 'TBD'
    try:
        dt = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return f'<t:{int(dt.timestamp())}:D>'  # :D = date only e.g. "March 22, 2026"
    except ValueError:
        return 'TBD'

def fetch_f1_standings() -> list | None:
    """
    Fetch current driver championship standings using the latest race session.
    Returns list sorted by position, empty list if season hasn't started, or None on error.
    """
    results = openf1_get('championship_drivers', {'session_key': 'latest'})
    if results is None:
        return None
    return sorted(results, key=lambda x: x.get('position_current', 99))


# --- NCAA TOURNAMENT DATA ---

NCAA_BASE = 'https://site.api.espn.com/apis/site/v2/sports/basketball'

# ESPN league slugs per gender
ESPN_LEAGUE = {
    'men':   'mens-college-basketball',
    'women': 'womens-college-basketball',
}

# ESPN notes headline → bracket round label
# ESPN uses strings like "Men's Basketball Championship - 1st Round"
ESPN_ROUND_MAP = {
    'first four':    'First Four',
    '1st round':     'First Round',
    'first round':   'First Round',
    '2nd round':     'Second Round',
    'second round':  'Second Round',
    'sweet 16':      'Sweet 16',
    'sweet sixteen': 'Sweet 16',
    'elite eight':   'Elite Eight',
    'elite 8':       'Elite Eight',
    'final four':    'Final Four',
    'national championship': 'Championship',
    'championship':  'Championship',
}

def espn_parse_round(notes: list) -> tuple[str, str]:
    """
    Extract bracket round and region from ESPN competition notes.
    Returns (round_label, region) e.g. ('First Round', 'East').
    """
    for note in notes:
        headline = note.get('headline', '').lower()
        round_label = ''
        for key, label in ESPN_ROUND_MAP.items():
            if key in headline:
                round_label = label
                break
        if not round_label:
            continue
        # Extract region — appears as "East Region", "South Region", etc.
        region = ''
        for r in ('east', 'south', 'west', 'midwest'):
            if r in headline:
                region = r.capitalize()
                break
        return round_label, region
    return '', ''

def espn_normalize_game(event: dict) -> dict | None:
    """
    Convert an ESPN scoreboard event into our normalized game dict shape.
    Returns None if not a tournament game or missing data.
    """
    competitions = event.get('competitions', [])
    if not competitions:
        return None
    comp = competitions[0]

    notes = comp.get('notes', [])
    bracket_round, region = espn_parse_round(notes)
    if not bracket_round or bracket_round == 'First Four':
        return None

    competitors = comp.get('competitors', [])
    if len(competitors) < 2:
        return None

    # ESPN labels home/away with homeAway field
    home_c = next((c for c in competitors if c.get('homeAway') == 'home'), competitors[0])
    away_c = next((c for c in competitors if c.get('homeAway') == 'away'), competitors[1])

    def parse_competitor(c: dict) -> dict:
        team = c.get('team', {})
        seed = str(c.get('curatedRank', {}).get('current', '') or '')
        if not seed or seed == '99':
            seed = ''
        score = c.get('score', '')
        winner = c.get('winner', False)
        name = team.get('shortDisplayName', team.get('displayName', '?'))
        return {'short': name, 'seed': seed, 'score': score, 'winner': winner}

    home_parsed = parse_competitor(home_c)
    away_parsed = parse_competitor(away_c)

    # Skip games where either team is TBD (seed 99 or name TBD)
    if home_parsed['short'] == 'TBD' or away_parsed['short'] == 'TBD':
        return None

    status = comp.get('status', {})
    status_type = status.get('type', {})
    state_name = status_type.get('name', '').lower()

    if 'final' in state_name:
        game_state = 'final'
    elif 'progress' in state_name or 'halftime' in state_name:
        game_state = 'live'
    else:
        game_state = 'pre'

    # Clock and period for live games
    period = status.get('period', '')
    clock = status.get('displayClock', '')
    period_str = f'{period}H' if period else ''  # ESPN uses period numbers

    # Start time as epoch
    date_str = event.get('date', '')
    epoch = ''
    if date_str:
        try:
            dt = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            epoch = str(int(dt.timestamp()))
        except ValueError:
            pass

    return {
        'away': away_parsed,
        'home': home_parsed,
        'bracketRound': bracket_round,
        'region': region,
        'gameState': game_state,
        'startTimeEpoch': epoch,
        'currentPeriod': period_str,
        'contestClock': clock,
    }

def fetch_ncaa_scoreboard(gender: str, date: datetime.date) -> list | None:
    """
    Fetch NCAA tournament games for a given date via ESPN API.
    Returns list of normalized game dicts or None on error.
    """
    league = ESPN_LEAGUE.get(gender, 'mens-college-basketball')
    date_str = date.strftime('%Y%m%d')
    url = f'{NCAA_BASE}/{league}/scoreboard'
    try:
        resp = requests.get(
            url,
            params={'groups': '100', 'limit': '200', 'dates': date_str, 'seasontype': '3'},
            headers={'User-Agent': USER_AGENT},
            timeout=10
        )
        if resp.status_code != 200:
            print(f'ESPN NCAA error {resp.status_code} ({gender} {date})')
            return None
        events = resp.json().get('events', [])
        games = []
        for event in events:
            g = espn_normalize_game(event)
            if g:
                games.append(g)
        return games
    except Exception as e:
        print(f'ESPN NCAA scoreboard error ({gender} {date}): {e}')
        return None

# Round labels: NCAA API value -> display label
# First Four is the 68->64 play-in. Excluded from display since those teams
# are rarely drafted and create noise before the main bracket.
NCAA_ROUND_LABELS = {
    'First Four':    'First Four',
    'First Round':   'Round of 64',
    'Second Round':  'Round of 32',
    'Sweet 16':      'Sweet Sixteen',
    'Elite Eight':   'Elite Eight',
    'Final Four':    'Final Four',
    'Championship':  'Championship',
}

# Rounds where we show ALL games (field small enough, owned teams may face each other)
NCAA_SHOW_ALL_ROUNDS = {'Sweet Sixteen', 'Elite Eight', 'Final Four', 'Championship'}

# Brackt name -> NCAA API short name, only where they differ
NCAA_NAME_MAP = {
    # Brackt name          → ESPN shortDisplayName
    'Ohio St.':            'Ohio State',   # ESPN: full state name
    'Michigan St.':        'Michigan St',  # ESPN: no trailing period
    'Iowa St.':            'Iowa State',   # ESPN: full state name
    "St. John's":          "St John's",    # ESPN: no period after St
    'Connecticut (UConn)': 'UConn',
    'Connecticut':         'UConn',
}

def normalize_ncaa_name(brackt_name: str) -> str:
    return NCAA_NAME_MAP.get(brackt_name, brackt_name)

def ncaa_names_match(api_name: str, normalized_brackt: str) -> bool:
    """Exact case-insensitive match between ESPN team name and normalized brackt name."""
    return api_name.strip().lower() == normalized_brackt.strip().lower()

def fetch_ncaa_tournament_window(gender: str, days_ahead: int = 14) -> list:
    """
    Fetch tournament games across the next days_ahead days, sorted by tip time.
    Uses 14 days by default so pre-tournament calls still find upcoming Round of 64 games.
    """
    all_games = []
    today = datetime.date.today()
    for i in range(days_ahead):
        day = today + datetime.timedelta(days=i)
        games = fetch_ncaa_scoreboard(gender, day)
        if games:
            all_games.extend(games)
    all_games.sort(key=lambda g: int(g.get('startTimeEpoch', 0) or 0))
    return all_games

def ncaa_team_names(game: dict) -> tuple:
    """Return (away_short, away_seed, home_short, home_seed)."""
    away = game.get('away', {})
    home = game.get('home', {})
    return (
        away.get('short', '?'),
        str(away.get('seed', '') or ''),
        home.get('short', '?'),
        str(home.get('seed', '') or ''),
    )

def find_ncaa_team_game(games: list, brackt_name: str) -> dict | None:
    """Find the most relevant game for a team using exact name matching."""
    normalized = normalize_ncaa_name(brackt_name)
    team_games = []
    for g in games:
        away, _, home, _ = ncaa_team_names(g)
        if ncaa_names_match(away, normalized) or ncaa_names_match(home, normalized):
            team_games.append(g)
    if not team_games:
        return None
    for g in team_games:
        if g.get('gameState') != 'final':
            return g
    return team_games[-1]

def ncaa_epoch_to_ts(epoch) -> str:
    try:
        return f'<t:{int(epoch)}:F>'
    except (ValueError, TypeError):
        return 'TBD'

def ncaa_get_owner(api_name: str, team_owners: dict) -> str:
    """Look up owner handle for an API team name using exact matching."""
    for brackt_lower, handle in team_owners.items():
        if ncaa_names_match(api_name, brackt_lower):
            return handle
    return ''

def ncaa_format_game_line(g: dict, team_owners: dict) -> str:
    """Format a single game line for /schedule output."""
    away_name, away_seed, home_name, home_seed = ncaa_team_names(g)
    away_owner = ncaa_get_owner(away_name, team_owners)
    home_owner = ncaa_get_owner(home_name, team_owners)

    def fmt_side(name, seed, owner):
        seed_str = f'({seed}) ' if seed else ''
        owner_str = f' ⬅ {owner}' if owner else ''
        return f'{seed_str}**{name}**{owner_str}'

    away_str = fmt_side(away_name, away_seed, away_owner)
    home_str = fmt_side(home_name, home_seed, home_owner)
    state = g.get('gameState', '')

    if state == 'final':
        a_score = g.get('away', {}).get('score', '')
        h_score = g.get('home', {}).get('score', '')
        a_won = g.get('away', {}).get('winner', False)
        if away_owner and not home_owner:
            result = '✅' if a_won else '❌'
        elif home_owner and not away_owner:
            result = '✅' if not a_won else '❌'
        else:
            result = '🏁'
        return f'{result} {away_str}  vs  {home_str}  Final {a_score}-{h_score}'
    elif state == 'live':
        a_score = g.get('away', {}).get('score', '')
        h_score = g.get('home', {}).get('score', '')
        period = g.get('currentPeriod', '')
        clock = g.get('contestClock', '')
        live_str = f'{period} {clock}'.strip() or 'LIVE'
        return f'🔴 {away_str}  vs  {home_str}  {a_score}-{h_score} ({live_str})'
    else:
        ts = ncaa_epoch_to_ts(g.get('startTimeEpoch'))
        return f'🏀 {away_str}  vs  {home_str}  {ts}' 
# --- PUBLIC READ COMMANDS ---

@brackt_public.command(name="onclock", description="Show who is currently on the clock")
@app_commands.describe(display="Show publicly or privately (default: public)")
@app_commands.choices(display=DISPLAY_CHOICES)
async def onclock(interaction: discord.Interaction, display: str = "public"):
    league = load_league(interaction.channel_id)
    if not league:
        await no_league_response(interaction); return
    if not league.get('draft_active', True):
        await draft_inactive_response(interaction); return
    if not league['draft_order']:
        await interaction.response.send_message('❌ Draft not configured yet.', ephemeral=True); return
    pick_num = league['current_pick']
    formatted, _ = format_pick_number(league, pick_num)
    username = get_team_for_pick(league, pick_num)
    after_username = get_next_pick_username(league, pick_num)
    up_next = f'\nUp next: {mention(league, after_username)}' if after_username else ''
    msg = (
        f'🕐 **Pick {formatted} ({pick_num}):** {mention(league, username)} is on the clock!'
        f'{up_next}'
    )
    await interaction.response.send_message(msg, ephemeral=is_ephemeral(display))

@brackt_public.command(name="last5", description="Show the last 5 picks")
@app_commands.describe(display="Show publicly or privately (default: public)")
@app_commands.choices(display=DISPLAY_CHOICES)
async def last5(interaction: discord.Interaction, display: str = "public"):
    league = load_league(interaction.channel_id)
    if not league:
        await no_league_response(interaction); return
    if not league.get('draft_active', True):
        await draft_inactive_response(interaction); return
    if not league['pick_history']:
        await interaction.response.send_message(
            '📋 No picks have been made yet.', ephemeral=is_ephemeral(display)
        ); return
    recent = league['pick_history'][-5:]
    text = '📋 **Last 5 Picks**\n\n'
    for p in recent:
        formatted, _ = format_pick_number(league, p["pick"])
        handle = league['handles'].get(p["team"], p["team"])
        text += f'Pick {formatted} ({p["pick"]}): **{handle}** — **{p["player"]}** ({p["sport"]})\n'
    await interaction.response.send_message(text, ephemeral=is_ephemeral(display))

@brackt_public.command(name="team", description="Show all picks made by a specific team")
@app_commands.describe(
    brackt_username="Start typing a team name or brackt username",
    display="Show publicly or privately (default: public)"
)
@app_commands.autocomplete(brackt_username=brackt_username_autocomplete)
@app_commands.choices(display=DISPLAY_CHOICES)
async def team_command(interaction: discord.Interaction, brackt_username: str, display: str = "public"):
    league = load_league(interaction.channel_id)
    if not league:
        await no_league_response(interaction); return
    if brackt_username not in league['team_rosters']:
        known = ', '.join(f'`{u}`' for u in league['draft_order']) or 'None configured'
        await interaction.response.send_message(
            f'❌ Unknown username: `{brackt_username}`\nKnown teams: {known}', ephemeral=True
        ); return
    roster = league['team_rosters'].get(brackt_username, [])
    handle = league['handles'].get(brackt_username, brackt_username)
    if not roster:
        await interaction.response.send_message(
            f'📋 No picks recorded for **{handle}** yet.', ephemeral=is_ephemeral(display)
        ); return
    text = f'📋 **{handle}\'s Picks ({len(roster)}/{league["total_rounds"]})**\n\n'
    for p in roster:
        _, round_num = format_pick_number(league, p["pick"])
        text += f'Round {round_num}: **{p["player"]}** ({p["sport"]})\n'
    await interaction.response.send_message(text, ephemeral=is_ephemeral(display))

@brackt_public.command(name="mysports", description="Show missing sports and flex spots for a team")
@app_commands.describe(
    brackt_username="Start typing a team name or brackt username (leave blank for your own)",
    display="Show publicly or privately (default: public)"
)
@app_commands.autocomplete(brackt_username=brackt_username_autocomplete)
@app_commands.choices(display=DISPLAY_CHOICES)
async def mysports(interaction: discord.Interaction, brackt_username: str = None, display: str = "public"):
    league = load_league(interaction.channel_id)
    if not league:
        await no_league_response(interaction); return
    if not league['required_sports']:
        await interaction.response.send_message(
            '❌ No required sports configured yet.', ephemeral=True
        ); return
    if brackt_username is None:
        sender_id = str(interaction.user.id)
        brackt_username = next(
            (u for u, uid in league['players'].items() if uid == sender_id), None
        )
        if brackt_username is None:
            await interaction.response.send_message(
                '❌ Could not find your team. Try `/brackt mysports [brackt username]`',
                ephemeral=True
            ); return
    if brackt_username not in league['team_rosters']:
        await interaction.response.send_message(
            f'❌ Unknown username: `{brackt_username}`', ephemeral=True
        ); return
    missing = get_missing_sports(league, brackt_username)
    flex_left = get_flex_remaining(league, brackt_username)
    total_picks = len(league['team_rosters'].get(brackt_username, []))
    handle = league['handles'].get(brackt_username, brackt_username)
    missing_text = '✅ All sports covered!' if not missing else '\n'.join(f'  • {s}' for s in missing)
    msg = (
        f'📊 **{handle}\'s Roster ({total_picks}/{league["total_rounds"]} picks)**\n\n'
        f'**Missing Sports ({len(missing)}):**\n{missing_text}\n\n'
        f'**Flex Spots Remaining:** {flex_left} of {league["flex_spots"]}'
    )
    await interaction.response.send_message(msg, ephemeral=is_ephemeral(display))

@brackt_public.command(name="status", description="Show current draft round, pick number, and who is on the clock")
@app_commands.describe(display="Show publicly or privately (default: public)")
@app_commands.choices(display=DISPLAY_CHOICES)
async def status(interaction: discord.Interaction, display: str = "public"):
    league = load_league(interaction.channel_id)
    if not league:
        await no_league_response(interaction); return
    if not league.get('draft_active', True):
        await draft_inactive_response(interaction); return
    if not league['draft_order']:
        await interaction.response.send_message('❌ Draft not configured yet.', ephemeral=True); return
    pick_num = league['current_pick']
    total_picks = get_total_picks(league)
    _, round_num = format_pick_number(league, pick_num)
    username = get_team_for_pick(league, pick_num)
    msg = (
        f'📋 **Draft Status — {league_display_name(league)}** ({mode_label(league)})\n'
        f'Round: {round_num} of {league["total_rounds"]}\n'
        f'Current Pick: {pick_num} of {total_picks}\n'
        f'On the Clock: {mention(league, username)}'
    )
    await interaction.response.send_message(msg, ephemeral=is_ephemeral(display))

async def sport_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> list[app_commands.Choice[str]]:
    league = load_league(interaction.channel_id)
    if not league or not league.get('required_sports'):
        return []
    return [
        app_commands.Choice(name=s, value=s)
        for s in league['required_sports']
        if current.lower() in s.lower()
    ][:25]

@brackt_public.command(name="sport", description="Show all drafted picks for a specific sport")
@app_commands.describe(
    sport="Select a sport",
    display="Show publicly or privately (default: private)"
)
@app_commands.autocomplete(sport=sport_autocomplete)
@app_commands.choices(display=DISPLAY_CHOICES)
async def sport_command(interaction: discord.Interaction, sport: str, display: str = "private"):
    league = load_league(interaction.channel_id)
    if not league:
        await no_league_response(interaction); return
    if not league.get('pick_history'):
        await interaction.response.send_message(
            '📋 No picks recorded yet.', ephemeral=True
        ); return

    # Filter picks by sport, sorted by overall pick number
    sport_picks = sorted(
        [p for p in league['pick_history'] if p['sport'].lower() == sport.lower()],
        key=lambda x: x['pick']
    )

    if not sport_picks:
        available = ', '.join(f'`{s}`' for s in league['required_sports'])
        await interaction.response.send_message(
            f'❌ No picks found for **{sport}**.\nAvailable sports: {available}',
            ephemeral=True
        ); return

    lines = []
    for i, p in enumerate(sport_picks, 1):
        handle = league['handles'].get(p['team'], p['team'])
        lines.append(f'{i}. **{p["player"]}** — {handle} ({p["pick"]})')

    text = f'🏅 **{sport}** — {len(sport_picks)} pick{"s" if len(sport_picks) > 1 else ""}\n\n'
    text += '\n'.join(lines)

    await interaction.response.send_message(text, ephemeral=is_ephemeral(display))

async def schedule_sport_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> list[app_commands.Choice[str]]:
    league = load_league(interaction.channel_id)
    if not league or not league.get('required_sports'):
        return []
    return [
        app_commands.Choice(name=s, value=s)
        for s in league['required_sports']
        if current.lower() in s.lower()
    ][:25]

# Sports with live fixture support implemented
SCHEDULE_SUPPORTED_SPORTS = {
    'UEFA Champions League',
    'NBA',
    'Formula 1',
    'NCAAM Basketball',
    'NCAAW Basketball',
    "NCAA Basketball - Men's",
    "NCAA Basketball - Women's",
}

@brackt_public.command(name="schedule", description="Show upcoming fixtures and results for a sport")
@app_commands.describe(
    sport="Select a sport",
    display="Show publicly or privately (default: private)"
)
@app_commands.autocomplete(sport=schedule_sport_autocomplete)
@app_commands.choices(display=DISPLAY_CHOICES)
async def schedule_command(interaction: discord.Interaction, sport: str, display: str = "private"):
    league = load_league(interaction.channel_id)
    if not league:
        await no_league_response(interaction); return

    if sport not in SCHEDULE_SUPPORTED_SPORTS:
        await interaction.response.send_message(
            f'🚧 Schedule support for **{sport}** is coming soon!',
            ephemeral=True
        ); return

    if sport == 'UEFA Champions League':
        if not any(p['sport'] == 'UEFA Champions League' for p in league.get('pick_history', [])):
            await interaction.response.send_message(
                '❌ No UEFA Champions League picks found in this league.', ephemeral=True
            ); return
        await interaction.response.defer(ephemeral=is_ephemeral(display))
        matches = fetch_ucl_fixtures()
        if matches is None:
            await interaction.followup.send(
                '❌ Could not reach the football data API. Try again later.',
                ephemeral=True
            ); return
        ties = build_ucl_matchups(league, matches)
        if not ties:
            await interaction.followup.send(
                '❌ No UCL fixtures found involving drafted clubs.',
                ephemeral=True
            ); return
        lines = [f'🏆 **UEFA Champions League — Round of 16** · {league_display_name(league)}\n']
        for t in ties:
            lines.append(format_ucl_tie(t))
        await interaction.followup.send('\n'.join(lines), ephemeral=is_ephemeral(display))

    elif sport == 'NBA':
        if not any(p['sport'] == 'NBA' for p in league.get('pick_history', [])):
            await interaction.response.send_message(
                '❌ No NBA picks found in this league.', ephemeral=True
            ); return
        await interaction.response.defer(ephemeral=is_ephemeral(display))

        postseason_games = fetch_nba_postseason_games()
        if postseason_games is None:
            await interaction.followup.send(
                '❌ Could not reach the NBA data API. Try again later.', ephemeral=True
            ); return

        playoffs_started = len(postseason_games) > 0

        if not playoffs_started:
            # Detect earliest postseason date dynamically
            # Try fetching a broader window — if none found, show "not yet" message
            # with a note to check back closer to April
            lines = [
                f'🏀 **NBA** · {league_display_name(league)}\n',
                '🏆 **Playoffs haven\'t started yet.**\n',
                '**Play-In Tournament** tips off mid-April across 3 games per conference:',
                '• #7 hosts #8 → winner earns the 7 seed',
                '• #9 hosts #10 → loser is eliminated',
                '• Loser of 7/8 game hosts winner of 9/10 → winner earns the 8 seed\n',
                '**First round of playoffs** begins shortly after the play-in concludes.\n',
                'Use `/brackt nextmatch NBA` to see your team\'s next regular season game.',
            ]
            await interaction.followup.send('\n'.join(lines), ephemeral=is_ephemeral(display))
            return

        # Playoffs are live — show series status for all drafted NBA teams
        drafted_nba = [
            p['player'] for p in league['pick_history']
            if p['sport'] == 'NBA'
        ]
        if not drafted_nba:
            await interaction.followup.send(
                '❌ No NBA picks found in this league.', ephemeral=True
            ); return

        lines = [f'🏀 **NBA Playoffs** · {league_display_name(league)}\n']
        for brackt_name in drafted_nba:
            bdl_name = brackt_to_bdl_name(brackt_name)
            team_id = bdl_name_to_team_id(bdl_name)
            if not team_id:
                continue
            team_games = [
                g for g in postseason_games
                if g['home_team']['id'] == team_id or g['visitor_team']['id'] == team_id
            ]
            if not team_games:
                lines.append(f'**{brackt_name}** — ❌ Eliminated (did not qualify)')
                continue
            series = build_nba_series(team_games, team_id)
            if not series:
                lines.append(f'**{brackt_name}** — No series data available')
                continue
            if series['is_eliminated']:
                lines.append(f'**{brackt_name}** — ❌ Eliminated · vs {series["opponent"]} ({series["series_label"]})')
            elif series['series_over']:
                lines.append(f'**{brackt_name}** — ✅ Advanced · vs {series["opponent"]} ({series["series_label"]})')
            else:
                next_str = format_nba_game_line(series['next_game'], team_id) if series['next_game'] else 'TBD'
                lines.append(
                    f'**{brackt_name}** — vs {series["opponent"]} · {series["series_label"]}\n'
                    f'   Next: {next_str}'
                )

        await interaction.followup.send('\n'.join(lines), ephemeral=is_ephemeral(display))

    elif sport == 'Formula 1':
        if not any(p['sport'] == 'Formula 1' for p in league.get('pick_history', [])):
            await interaction.response.send_message(
                '❌ No Formula 1 picks found in this league.', ephemeral=True
            ); return
        await interaction.response.defer(ephemeral=is_ephemeral(display))

        meetings = fetch_f1_meetings()
        standings = fetch_f1_standings()
        if meetings is None or standings is None:
            await interaction.followup.send(
                '❌ Could not reach the F1 data API. Try again later.', ephemeral=True
            ); return

        today = datetime.date.today().isoformat()
        upcoming = [m for m in meetings if m.get('date_end', m.get('date_start', '')) >= today]
        completed = [m for m in meetings if m.get('date_end', m.get('date_start', '')) < today]
        races_remaining = len(upcoming)

        # Next 3 upcoming races — date only, no extra API calls
        next_races = upcoming[:3]
        race_lines = []
        for m in next_races:
            name = m.get('meeting_name', 'Unknown GP')
            ts = meeting_race_date_ts(m)
            race_lines.append(f'• **{name}** — {ts}')

        # Build standings lookup: driver_number → {position, points}
        standings_map = {
            s['driver_number']: s for s in standings
        }
        # Reverse map: driver_number → brackt name
        number_to_brackt = {v: k for k, v in F1_DRIVER_NUMBERS.items()}

        # Map driver_number → owner handle
        driver_number_to_owner = {}
        for p in league['pick_history']:
            if p['sport'] == 'Formula 1' and p['player'] in F1_DRIVER_NUMBERS:
                num = F1_DRIVER_NUMBERS[p['player']]
                handle = league['handles'].get(p['team'], p['team'])
                driver_number_to_owner[num] = handle

        if standings:
            standing_lines = []
            for s in standings[:10]:
                num = s['driver_number']
                pos = s.get('position_current', '?')
                pts = int(s.get('points_current', 0))
                name = number_to_brackt.get(num, f'#{num}')
                owner = driver_number_to_owner.get(num)
                marker = f' ⬅ {owner}' if owner else ''
                standing_lines.append(f'`P{pos:>2}` **{name}** — {pts} pts{marker}')
            standings_block = ['\n**Driver Championship (Top 10):**', *standing_lines]
        else:
            standings_block = ['\n*Standings not yet available — season may not have started.*']

        lines = [
            f'🏎️ **Formula 1** · {league_display_name(league)}',
            f'**{races_remaining} races remaining**\n',
            '**Next 3 GPs:**',
            *race_lines,
            *standings_block,
        ]
        await interaction.followup.send('\n'.join(lines), ephemeral=is_ephemeral(display))

    elif sport in ('NCAAM Basketball', "NCAA Basketball - Men's", 'NCAAW Basketball', "NCAA Basketball - Women's"):
        gender = 'men' if sport in ('NCAAM Basketball', "NCAA Basketball - Men's") else 'women'
        pick_sport = 'NCAAM Basketball' if gender == 'men' else 'NCAAW Basketball'
        emoji = '🏀'
        sport_label = "NCAA Men's Basketball" if gender == 'men' else "NCAA Women's Basketball"

        if not any(p['sport'] == pick_sport for p in league.get('pick_history', [])):
            await interaction.response.send_message(
                f'❌ No {sport_label} picks found in this league.', ephemeral=True
            ); return

        await interaction.response.defer(ephemeral=is_ephemeral(display))

        games = fetch_ncaa_tournament_window(gender, days_ahead=14)

        if not games:
            await interaction.followup.send(
                f'{emoji} **{sport_label}** · {league_display_name(league)}\n'
                '📋 No tournament games found in the next 14 days. '
                'Games may not be available in the data source yet — check back closer to tip-off.',
                ephemeral=is_ephemeral(display)
            ); return

        # Detect current round — first non-final game's round
        current_round = None
        for g in games:
            if g.get('gameState') != 'final':
                current_round = NCAA_ROUND_LABELS.get(g.get('bracketRound', ''), g.get('bracketRound', ''))
                break
        if not current_round:
            current_round = NCAA_ROUND_LABELS.get(games[-1].get('bracketRound', ''), 'Tournament')

        show_all = current_round in NCAA_SHOW_ALL_ROUNDS

        # Build owner lookup: normalized_name_lower → handle
        team_owners: dict[str, str] = {}
        for p in league['pick_history']:
            if p['sport'] == pick_sport:
                norm = normalize_ncaa_name(p['player'])
                handle = league['handles'].get(p['team'], p['team'])
                team_owners[norm.lower()] = handle

        # Group matching games by region in bracket order
        region_order = ['East', 'South', 'West', 'Midwest', '']
        by_region: dict[str, list] = {r: [] for r in region_order}

        for g in games:
            round_label = NCAA_ROUND_LABELS.get(g.get('bracketRound', ''), g.get('bracketRound', ''))
            if round_label != current_round:
                continue
            away_name, away_seed, home_name, home_seed = ncaa_team_names(g)
            away_owner = ncaa_get_owner(away_name, team_owners)
            home_owner = ncaa_get_owner(home_name, team_owners)
            if not show_all and not away_owner and not home_owner:
                continue
            region = g.get('region', '')
            if region not in by_region:
                region = ''
            by_region[region].append(g)

        lines = [f'{emoji} **{sport_label}** · {league_display_name(league)}']
        lines.append(f'📍 **{current_round}**')

        shown = 0
        for region in region_order:
            region_games = by_region.get(region, [])
            if not region_games:
                continue
            if region:
                lines.append(f'\n**{region}**')
            for g in region_games:
                lines.append(ncaa_format_game_line(g, team_owners))
                shown += 1

        if shown == 0:
            lines.append('\nNo games involving drafted teams found.')

        await interaction.followup.send('\n'.join(lines), ephemeral=is_ephemeral(display))

@brackt_public.command(name="nextmatch", description="Show your next upcoming match for a sport")
@app_commands.describe(sport="Select a sport with fixture support")
@app_commands.autocomplete(sport=schedule_sport_autocomplete)
async def nextmatch_command(interaction: discord.Interaction, sport: str):
    league = load_league(interaction.channel_id)
    if not league:
        await no_league_response(interaction); return

    if sport not in SCHEDULE_SUPPORTED_SPORTS:
        await interaction.response.send_message(
            f'🚧 Schedule support for **{sport}** is coming soon!',
            ephemeral=True
        ); return

    if sport == 'UEFA Champions League':
        if not any(p['sport'] == 'UEFA Champions League' for p in league.get('pick_history', [])):
            await interaction.response.send_message(
                '❌ No UEFA Champions League picks found in this league.', ephemeral=True
            ); return

        sender_id = str(interaction.user.id)
        user_teams = [u for u, uid in league['players'].items() if uid == sender_id]
        if not user_teams:
            await interaction.response.send_message(
                '❌ Your Discord account is not mapped to any team in this league.',
                ephemeral=True
            ); return

        user_ucl_picks = [
            p['player'] for p in league['pick_history']
            if p['sport'] == 'UEFA Champions League' and p['team'] in user_teams
        ]
        if not user_ucl_picks:
            await interaction.response.send_message(
                '❌ You have no UEFA Champions League picks in this league.',
                ephemeral=True
            ); return

        await interaction.response.defer(ephemeral=True)
        matches = fetch_ucl_fixtures()
        if matches is None:
            await interaction.followup.send(
                '❌ Could not reach the football data API. Try again later.',
                ephemeral=True
            ); return

        ties = build_ucl_matchups(league, matches)
        user_api_names = {UCL_NAME_MAP.get(p, p) for p in user_ucl_picks}

        relevant = []
        for t in ties:
            home_api = UCL_NAME_MAP.get(t['home_brackt'], t['home_brackt'])
            away_api = UCL_NAME_MAP.get(t['away_brackt'], t['away_brackt'])
            if home_api in user_api_names or away_api in user_api_names:
                relevant.append(t)

        if not relevant:
            await interaction.followup.send(
                '✅ All your UCL teams have finished their fixtures.',
                ephemeral=True
            ); return

        lines = [f'📅 **Your next UCL match{"es" if len(relevant) > 1 else ""}:**\n']
        for t in relevant:
            lines.append(format_ucl_tie(t))
        await interaction.followup.send('\n'.join(lines), ephemeral=True)

    elif sport == 'NBA':
        if not any(p['sport'] == 'NBA' for p in league.get('pick_history', [])):
            await interaction.response.send_message(
                '❌ No NBA picks found in this league.', ephemeral=True
            ); return

        sender_id = str(interaction.user.id)
        user_teams = [u for u, uid in league['players'].items() if uid == sender_id]
        if not user_teams:
            await interaction.response.send_message(
                '❌ Your Discord account is not mapped to any team in this league.',
                ephemeral=True
            ); return

        user_nba_picks = [
            p['player'] for p in league['pick_history']
            if p['sport'] == 'NBA' and p['team'] in user_teams
        ]
        if not user_nba_picks:
            await interaction.response.send_message(
                '❌ You have no NBA picks in this league.', ephemeral=True
            ); return

        await interaction.response.defer(ephemeral=True)

        # 1 call to check postseason status
        postseason_games = fetch_nba_postseason_games()
        if postseason_games is None:
            await interaction.followup.send(
                '❌ Could not reach the NBA data API. Try again later.', ephemeral=True
            ); return

        playoffs_started = len(postseason_games) > 0
        lines = [f'📅 **Your NBA team{"s" if len(user_nba_picks) > 1 else ""}:**\n']

        for brackt_name in user_nba_picks:
            bdl_name = brackt_to_bdl_name(brackt_name)
            team_id = bdl_name_to_team_id(bdl_name)
            if not team_id:
                lines.append(f'**{brackt_name}** — ❌ Team not found in data')
                continue

            if playoffs_started:
                team_data = fetch_nba_team_data(team_id)
                record_str = f'{team_data["wins"]}–{team_data["losses"]}' if team_data else 'N/A'
                team_post_games = [
                    g for g in postseason_games
                    if int(g['home_team']['id']) == team_id or int(g['visitor_team']['id']) == team_id
                ]

                # Split into play-in and main bracket games by date
                playin_games = [g for g in team_post_games if game_is_playin(g)]
                bracket_games = [g for g in team_post_games if not game_is_playin(g)]

                if not team_post_games:
                    # Postseason started but no games yet — too early to tell
                    lines.append(f'**{brackt_name}** ({record_str}) — ⏳ Awaiting playoff assignment')
                    continue

                if playin_games and not bracket_games:
                    # Team is in play-in only
                    upcoming = [g for g in playin_games if g['status'] != 'Final']
                    completed = [g for g in playin_games if g['status'] == 'Final']
                    if upcoming:
                        next_str = format_nba_game_line(upcoming[0], team_id)
                        lines.append(f'**{brackt_name}** ({record_str}) — 🎟️ Play-In: {next_str}')
                    elif completed:
                        # All play-in games done and no bracket games — eliminated
                        lines.append(f'**{brackt_name}** ({record_str}) — ❌ Eliminated in Play-In')
                    else:
                        lines.append(f'**{brackt_name}** ({record_str}) — 🎟️ Play-In pending')
                    continue

                # Main bracket (includes teams that came through play-in)
                series_games = bracket_games if bracket_games else team_post_games
                series = build_nba_series(series_games, team_id)
                if not series:
                    lines.append(f'**{brackt_name}** ({record_str}) — No series data')
                    continue
                if series['is_eliminated']:
                    lines.append(
                        f'**{brackt_name}** ({record_str}) — ❌ Eliminated\n'
                        f'   vs {series["opponent"]} · {series["series_label"]}'
                    )
                elif series['series_over']:
                    lines.append(
                        f'**{brackt_name}** ({record_str}) — ✅ Advanced\n'
                        f'   vs {series["opponent"]} · {series["series_label"]}'
                    )
                else:
                    next_str = format_nba_game_line(series['next_game'], team_id) if series['next_game'] else 'TBD'
                    lines.append(
                        f'**{brackt_name}** ({record_str}) — 🏀 In Playoffs\n'
                        f'   vs {series["opponent"]} · {series["series_label"]}\n'
                        f'   Next: {next_str}'
                    )
            else:
                # Regular season: 2 calls total via fetch_nba_team_data
                team_data = fetch_nba_team_data(team_id)
                if team_data is None:
                    lines.append(f'**{brackt_name}** — ❌ Could not fetch data (rate limit?)')
                    continue
                record_str = f'{team_data["wins"]}–{team_data["losses"]}'
                if team_data['live_game']:
                    live_str = format_nba_game_line(team_data['live_game'], team_id)
                    lines.append(f'**{brackt_name}** ({record_str}) — 🔴 LIVE: {live_str}')
                elif team_data['next_game']:
                    next_str = format_nba_game_line(team_data['next_game'], team_id)
                    lines.append(f'**{brackt_name}** ({record_str}) — Next: {next_str}')
                else:
                    lines.append(f'**{brackt_name}** ({record_str}) — No upcoming games found')

        await interaction.followup.send('\n'.join(lines), ephemeral=True)

    elif sport == 'Formula 1':
        if not any(p['sport'] == 'Formula 1' for p in league.get('pick_history', [])):
            await interaction.response.send_message(
                '❌ No Formula 1 picks found in this league.', ephemeral=True
            ); return

        sender_id = str(interaction.user.id)
        user_teams = [u for u, uid in league['players'].items() if uid == sender_id]
        if not user_teams:
            await interaction.response.send_message(
                '❌ Your Discord account is not mapped to any team in this league.',
                ephemeral=True
            ); return

        user_f1_picks = [
            p['player'] for p in league['pick_history']
            if p['sport'] == 'Formula 1' and p['team'] in user_teams
        ]
        if not user_f1_picks:
            await interaction.response.send_message(
                '❌ You have no Formula 1 picks in this league.', ephemeral=True
            ); return

        await interaction.response.defer(ephemeral=True)

        meetings = fetch_f1_meetings()
        standings = fetch_f1_standings()
        if meetings is None or standings is None:
            await interaction.followup.send(
                '❌ Could not reach the F1 data API. Try again later.', ephemeral=True
            ); return

        # Find next upcoming race
        today = datetime.date.today().isoformat()
        upcoming = [m for m in meetings if m.get('date_end', m.get('date_start', '')) >= today]
        next_race = upcoming[0] if upcoming else None

        # Build standings lookup
        standings_map = {s['driver_number']: s for s in standings}

        lines = [f'🏎️ **Your F1 driver{"s" if len(user_f1_picks) > 1 else ""}:**\n']

        if next_race:
            name = next_race.get('meeting_name', 'Unknown GP')
            meeting_key = next_race.get('meeting_key')
            # Fetch exact race start time — 1 extra API call but worth it for nextmatch
            race_ts = fetch_f1_race_session_time(meeting_key) if meeting_key else None
            if race_ts:
                lines.append(f'📅 **Next Race:** {name} — {race_ts}\n')
            else:
                # Fallback to date_end approximation
                ts = meeting_race_date_ts(next_race)
                lines.append(f'📅 **Next Race:** {name} — {ts}\n')
        else:
            lines.append('📅 **Next Race:** Season complete\n')

        for driver_name in user_f1_picks:
            driver_num = f1_driver_number(driver_name)
            if not driver_num:
                lines.append(f'**{driver_name}** — ❌ Driver not found in data')
                continue
            if not standings:
                lines.append(f'**{driver_name}** — Standings not yet available')
                continue
            standing = standings_map.get(driver_num)
            if not standing:
                lines.append(f'**{driver_name}** — No standings data yet')
                continue
            pos = standing.get('position_current', '?')
            pts = int(standing.get('points_current', 0))
            lines.append(f'**{driver_name}** — P{pos} · {pts} pts')

        await interaction.followup.send('\n'.join(lines), ephemeral=True)

    elif sport in ('NCAAM Basketball', "NCAA Basketball - Men's", 'NCAAW Basketball', "NCAA Basketball - Women's"):
        gender = 'men' if sport in ('NCAAM Basketball', "NCAA Basketball - Men's") else 'women'
        pick_sport = 'NCAAM Basketball' if gender == 'men' else 'NCAAW Basketball'
        emoji = '🏀'
        sport_label = "NCAA Men's Basketball" if gender == 'men' else "NCAA Women's Basketball"

        if not any(p['sport'] == pick_sport for p in league.get('pick_history', [])):
            await interaction.response.send_message(
                f'❌ No {sport_label} picks found in this league.', ephemeral=True
            ); return

        sender_id = str(interaction.user.id)
        user_teams = [u for u, uid in league['players'].items() if uid == sender_id]
        if not user_teams:
            await interaction.response.send_message(
                '❌ Your Discord account is not mapped to any team in this league.',
                ephemeral=True
            ); return

        user_picks = [
            p['player'] for p in league['pick_history']
            if p['sport'] == pick_sport and p['team'] in user_teams
        ]
        if not user_picks:
            await interaction.response.send_message(
                f'❌ You have no {sport_label} picks in this league.', ephemeral=True
            ); return

        await interaction.response.defer(ephemeral=True)

        games = fetch_ncaa_tournament_window(gender, days_ahead=14)

        lines = [f'{emoji} **Your {sport_label} team{"s" if len(user_picks) > 1 else ""}:**\n']

        for brackt_name in user_picks:
            normalized = normalize_ncaa_name(brackt_name)
            game = find_ncaa_team_game(games, brackt_name)

            if not game:
                # No upcoming game — check past 3 days for elimination/advancement
                past_games = []
                today = datetime.date.today()
                for i in range(1, 4):
                    day = today - datetime.timedelta(days=i)
                    dg = fetch_ncaa_scoreboard(gender, day)
                    if dg:
                        past_games.extend(dg)
                past_game = find_ncaa_team_game(past_games, brackt_name)
                if past_game and past_game.get('gameState') == 'final':
                    away_name, _, home_name, _ = ncaa_team_names(past_game)
                    my_away = ncaa_names_match(away_name, normalized)
                    won = (my_away and past_game.get('away', {}).get('winner')) or \
                          (not my_away and past_game.get('home', {}).get('winner'))
                    round_label = NCAA_ROUND_LABELS.get(past_game.get('bracketRound', ''), past_game.get('bracketRound', ''))
                    if won:
                        lines.append(f'**{brackt_name}** — ✅ Advanced from {round_label}, awaiting next opponent')
                    else:
                        lines.append(f'**{brackt_name}** — ❌ Eliminated in {round_label}')
                else:
                    lines.append(f'**{brackt_name}** — No upcoming games found (data may not be available yet)')
                continue

            round_raw = game.get('bracketRound', '')
            round_label = NCAA_ROUND_LABELS.get(round_raw, round_raw)
            away_name, away_seed, home_name, home_seed = ncaa_team_names(game)
            state = game.get('gameState', '')

            # Identify which side is our team using exact matching
            my_away = ncaa_names_match(away_name, normalized)
            my_seed = away_seed if my_away else home_seed
            opp_name = home_name if my_away else away_name
            opp_seed = home_seed if my_away else away_seed

            seed_str = f'({my_seed}) ' if my_seed else ''
            opp_str = f'({opp_seed}) {opp_name}' if opp_seed else opp_name

            if state == 'final':
                a_score = game.get('away', {}).get('score', '')
                h_score = game.get('home', {}).get('score', '')
                won = (my_away and game.get('away', {}).get('winner')) or \
                      (not my_away and game.get('home', {}).get('winner'))
                my_score = a_score if my_away else h_score
                their_score = h_score if my_away else a_score
                result = '✅ Won' if won else '❌ Lost'
                lines.append(
                    f'{seed_str}**{brackt_name}** — {result} · {round_label}\n'
                    f'   vs {opp_str} — Final {my_score}–{their_score}'
                )
            elif state == 'live':
                a_score = game.get('away', {}).get('score', '')
                h_score = game.get('home', {}).get('score', '')
                my_score = a_score if my_away else h_score
                opp_score = h_score if my_away else a_score
                period = game.get('currentPeriod', '')
                clock = game.get('contestClock', '')
                live_str = f'{period} {clock}'.strip() or 'LIVE'
                lines.append(
                    f'{seed_str}**{brackt_name}** — 🔴 LIVE · {round_label}\n'
                    f'   vs {opp_str} — {my_score}–{opp_score} ({live_str})'
                )
            else:
                ts = ncaa_epoch_to_ts(game.get('startTimeEpoch'))
                lines.append(
                    f'{seed_str}**{brackt_name}** — {round_label}\n'
                    f'   vs {opp_str} — {ts}'
                )

        await interaction.followup.send('\n'.join(lines), ephemeral=True)

@brackt_public.command(name="help", description="Show all available draft commands")
async def help_command(interaction: discord.Interaction):
    league = load_league(interaction.channel_id)
    mode = mode_label(league) if league else '⚪ Not configured'
    name = league_display_name(league) if league else 'Brackt Draft Bot'
    msg = (
        f'📖 **{name}** ({mode})\n\n'
        '**Commands:**\n'
        '`/brackt onclock` — Show who is on the clock\n'
        '`/brackt last5` — Show the last 5 picks\n'
        '`/brackt team [username]` — Show a team\'s picks\n'
        '`/brackt mysports [username]` — Show missing sports and flex spots\n'
        '`/brackt sport [sport]` — Show all picks for a specific sport\n'
        '`/brackt schedule [sport]` — Show upcoming fixtures and results\n'
        '`/brackt nextmatch [sport]` — Show your next upcoming match\n'
        '`/brackt status` — Show current draft state\n'
        '`/brackt help` — Show this message\n\n'
        'All commands support a `display` option: **public** (default) or **private**\n\n'
        '⚙️ *Server managers can access admin commands via `/bradmin`*'
    )
    await interaction.response.send_message(msg, ephemeral=True)

# --- POLLING LOOP ---

async def poll_all_leagues():
    await client.wait_until_ready()
    print(f'Polling all leagues every {POLL_INTERVAL} seconds...')

    while not client.is_closed():
        # Pick up any newly created league files not yet in cache
        for filename in os.listdir(LEAGUES_DIR):
            if filename.endswith('.json'):
                channel_id = int(filename.replace('.json', ''))
                if channel_id not in leagues_cache:
                    league = load_league(channel_id)
                    if league:
                        update_cache(channel_id, league)
                        print(f'New league {channel_id} loaded into cache')

        for channel_id, league in list(leagues_cache.items()):
            try:
                if not league.get('api_url') or not league.get('draft_order'):
                    continue

                channel = client.get_channel(channel_id)
                if not channel:
                    continue

                data = fetch_draft_state(league)
                if data is None:
                    # API went down — mark unavailable but keep saved state intact
                    if league.get('api_available'):
                        league['api_available'] = False
                        league['using_sample_data'] = True
                        update_cache(channel_id, league)
                    continue

                # currentPickNumber is the NEXT pick to be made.
                # last_completed = currentPickNumber - 1 = last pick that was actually made.
                last_completed = data['currentPickNumber'] - 1
                last_known = league.get('last_known_pick', 0)

                # First poll after startup — sync silently without announcing
                if last_known == 0:
                    sync_from_api(league, data)
                    league['last_known_pick'] = last_completed
                    update_cache(channel_id, league)
                    continue

                # Detect rollback — last_completed < last_known means picks were undone
                if last_completed < last_known:
                    picks_rolled_back = last_known - last_completed
                    current_username = get_team_for_pick(league, last_completed + 1)
                    on_deck_username = get_team_for_pick(league, last_completed + 2)
                    total = get_total_picks(league)
                    formatted, _ = format_pick_number(league, last_completed + 1)
                    on_deck = (
                        f'\n📋 **On Deck:** {mention(league, on_deck_username)}'
                        if on_deck_username and last_completed + 2 <= total else ''
                    )
                    await channel.send(
                        f'⏪ **Draft Rolled Back {picks_rolled_back} pick{"s" if picks_rolled_back > 1 else ""}**\n'
                        f'━━━━━━━━━━━━━━━━━━━━━━\n'
                        f'Returning to Pick {formatted}\n'
                        f'━━━━━━━━━━━━━━━━━━━━━━\n'
                        f'🕐 **On the Clock:** {mention(league, current_username)}'
                        f'{on_deck}'
                    )
                    sync_from_api(league, data)

                # Detect new picks — last_completed > last_known means picks were made
                elif last_completed > last_known:
                    new_picks = [p for p in data['picks'] if p['pickNumber'] > last_known]

                    # API timing guard — currentPickNumber advanced but picks not in array yet
                    # Skip sync and retry next poll cycle
                    if not new_picks:
                        continue

                    sorted_new_picks = sorted(new_picks, key=lambda x: x['pickNumber'])
                    last_pick_num = sorted_new_picks[-1]['pickNumber']

                    for pick in sorted_new_picks:
                        username = pick['username']
                        player = pick['participantName']
                        sport = pick['sport']
                        pick_num = pick['pickNumber']
                        formatted, _ = format_pick_number(league, pick_num)

                        # On the Clock = pick_num + 1, On Deck = pick_num + 2
                        next_username = get_team_for_pick(league, pick_num + 1)
                        on_deck_username = get_team_for_pick(league, pick_num + 2)
                        total = get_total_picks(league)
                        on_deck = (
                            f'\n📋 **On Deck:** {mention(league, on_deck_username)}'
                            if on_deck_username and pick_num + 2 <= total else ''
                        )

                        is_last_pick = data['isDraftComplete'] and pick_num == last_pick_num
                        if is_last_pick:
                            await channel.send(
                                f'━━━━━━━━━━━━━━━━━━━━━━\n'
                                f'✅ **Pick {formatted}** — {mention(league, username)}\n'
                                f'**{player}** · {sport}\n'
                                f'━━━━━━━━━━━━━━━━━━━━━━\n'
                                f'🏆 **The draft is complete!**\n'
                                f'All **{total} picks** have been made. Good luck everyone!'
                            )
                        else:
                            await channel.send(
                                f'━━━━━━━━━━━━━━━━━━━━━━\n'
                                f'✅ **Pick {formatted}** — {mention(league, username)}\n'
                                f'**{player}** · {sport}\n'
                                f'━━━━━━━━━━━━━━━━━━━━━━\n'
                                f'🕐 **On the Clock:** {mention(league, next_username)}'
                                f'{on_deck}'
                            )

                    # Sync rosters and pick history only when new picks were announced
                    sync_from_api(league, data)

                # Always update last_known_pick and pause state after a successful poll
                is_paused = data.get('isPaused', False)
                was_paused = league.get('draft_was_paused', False)
                if is_paused and not was_paused:
                    await channel.send('⏸️ **The draft has been paused.**')
                elif not is_paused and was_paused:
                    await channel.send('▶️ **The draft has resumed!**')

                league['last_known_pick'] = last_completed
                league['draft_was_paused'] = is_paused
                update_cache(channel_id, league)

            except discord.Forbidden:
                print(f'League {channel_id}: Missing channel permissions — skipping')
                continue
            except Exception as e:
                print(f'Error polling league {channel_id}: {e}')
                continue

        await asyncio.sleep(POLL_INTERVAL)

# --- STARTUP ---

@client.event
async def on_ready():
    print(f'Bot is online as {client.user}')

    for filename in os.listdir(LEAGUES_DIR):
        if not filename.endswith('.json'):
            continue
        try:
            channel_id = int(filename.replace('.json', ''))
            league = load_league(channel_id)
            if not league or not league.get('api_url'):
                print(f'League {channel_id} skipped — no API URL configured')
                # Still load into cache so commands work even without API
                if league:
                    leagues_cache[channel_id] = league
                continue

            # Preserve last_known_pick from disk before syncing
            saved_last_known = league.get('last_known_pick', 0)

            data = fetch_draft_state(league)
            if data:
                sync_from_api(league, data)
                last_completed = data['currentPickNumber'] - 1
                # If saved_last_known is valid and <= last_completed, restore it
                # so polling loop announces picks made while bot was offline.
                # If it was 0 or somehow ahead, use last_completed as safe default.
                if 0 < saved_last_known <= last_completed:
                    league['last_known_pick'] = saved_last_known
                else:
                    league['last_known_pick'] = last_completed
                print(f'League {channel_id} synced at pick {league["current_pick"]}, resuming from pick {league["last_known_pick"]}')
            else:
                print(f'League {channel_id} API unavailable — using saved state')

            update_cache(channel_id, league)

        except Exception as e:
            print(f'Error initializing league {filename}: {e}')

    await tree.sync()
    print('Slash commands synced!')
    asyncio.ensure_future(poll_all_leagues())

client.run(TOKEN)
