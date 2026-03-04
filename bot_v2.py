import discord
from discord import app_commands
import requests
import asyncio
import json
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

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
        'draft_was_paused': False
    }

def is_admin(league: dict, user_id: int) -> bool:
    return league['admin_id'] == user_id

def get_num_teams(league: dict) -> int:
    return len(league['draft_order'])

def get_total_picks(league: dict) -> int:
    return get_num_teams(league) * league['total_rounds']

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
        f'**Status:** {mode_label(league)}\n\n'
        f'**Draft Order:** {order_text}\n\n'
        f'**Players ({len(league["players"])}):**\n{players_text}\n\n'
        f'**Required Sports ({len(league["required_sports"])}):**\n{sports_text}'
    )
    await interaction.response.send_message(msg, ephemeral=True)

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

# --- PUBLIC READ COMMANDS ---

@brackt_public.command(name="onclock", description="Show who is currently on the clock")
@app_commands.describe(display="Show publicly or privately (default: public)")
@app_commands.choices(display=DISPLAY_CHOICES)
async def onclock(interaction: discord.Interaction, display: str = "public"):
    league = load_league(interaction.channel_id)
    if not league:
        await no_league_response(interaction); return
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
    if not league['draft_order']:
        await interaction.response.send_message('❌ Draft not configured yet.', ephemeral=True); return
    pick_num = league['current_pick']
    total_picks = get_total_picks(league)
    _, round_num = format_pick_number(league, pick_num)
    username = get_team_for_pick(league, pick_num)
    msg = (
        f'📋 **Draft Status** ({mode_label(league)})\n'
        f'Round: {round_num} of {league["total_rounds"]}\n'
        f'Current Pick: {pick_num} of {total_picks}\n'
        f'On the Clock: {mention(league, username)}'
    )
    await interaction.response.send_message(msg, ephemeral=is_ephemeral(display))

@brackt_public.command(name="help", description="Show all available draft commands")
async def help_command(interaction: discord.Interaction):
    league = load_league(interaction.channel_id)
    mode = mode_label(league) if league else '⚪ Not configured'
    msg = (
        f'📖 **Brackt Draft Bot** ({mode})\n\n'
        '**Commands:**\n'
        '`/brackt onclock` — Show who is on the clock\n'
        '`/brackt last5` — Show the last 5 picks\n'
        '`/brackt team [username]` — Show a team\'s picks\n'
        '`/brackt mysports [username]` — Show missing sports and flex spots\n'
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

                    for pick in sorted(new_picks, key=lambda x: x['pickNumber']):
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

                        if data['isDraftComplete'] and pick_num == last_completed:
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