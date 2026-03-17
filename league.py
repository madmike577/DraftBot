"""
league.py — League data model, cache, draft logic, and shared Discord utilities.
Imported by all cogs and sport modules.
"""

import json
import os
import discord
from discord import app_commands
import requests

from config import LEAGUES_DIR, USER_AGENT, DISPLAY_CHOICES

os.makedirs(LEAGUES_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# In-memory cache — single source of truth for the polling loop
# ---------------------------------------------------------------------------
leagues_cache: dict[int, dict] = {}

def update_cache(channel_id: int, league: dict):
    """Update both the in-memory cache and persist to disk atomically."""
    leagues_cache[channel_id] = league
    save_league(channel_id, league)

# ---------------------------------------------------------------------------
# Disk I/O
# ---------------------------------------------------------------------------

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
        'channel_id':      channel_id,
        'admin_id':        admin_id,
        'api_url':         None,
        'total_rounds':    20,
        'flex_spots':      4,
        'required_sports': [],
        'players':         {},
        'handles':         {},
        'draft_order':     [],
        'pick_history':    [],
        'team_rosters':    {},
        'current_pick':    1,
        'last_known_pick': 0,
        'api_available':   False,
        'using_sample_data': False,
        'draft_was_paused':  False,
        'draft_active':    True,
        'league_name':     None,
    }

# ---------------------------------------------------------------------------
# League helpers
# ---------------------------------------------------------------------------

def is_admin(league: dict, user_id: int) -> bool:
    return league['admin_id'] == user_id

def get_num_teams(league: dict) -> int:
    return len(league['draft_order'])

def get_total_picks(league: dict) -> int:
    return get_num_teams(league) * league['total_rounds']

def league_display_name(league: dict) -> str:
    return league.get('league_name') or f'Channel {league["channel_id"]}'

def mode_label(league: dict) -> str:
    if league.get('api_available') and not league.get('using_sample_data'):
        return '🟢 Live API'
    return '🟡 Saved state (API unavailable)'

def is_ephemeral(display: str) -> bool:
    return display == 'private'

# ---------------------------------------------------------------------------
# Draft logic
# ---------------------------------------------------------------------------

def get_team_for_pick(league: dict, pick_number: int) -> str | None:
    order = league['draft_order']
    if not order:
        return None
    n = len(order)
    pick_index  = pick_number - 1
    round_number = pick_index // n
    position    = pick_index % n
    if round_number % 2 == 0:
        return order[position]
    else:
        return order[n - 1 - position]

def get_next_pick_username(league: dict, pick_number: int) -> str | None:
    total = get_total_picks(league)
    next_pick = pick_number + 1
    if next_pick > total:
        return None
    return get_team_for_pick(league, next_pick)

def format_pick_number(league: dict, overall: int) -> tuple:
    n = get_num_teams(league)
    if n == 0:
        return f'Pick {overall}', 1
    round_num     = ((overall - 1) // n) + 1
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

# ---------------------------------------------------------------------------
# brackt.com API
# ---------------------------------------------------------------------------

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
    league['current_pick']  = data['currentPickNumber']
    league['pick_history']  = []
    league['team_rosters']  = {t: [] for t in league['draft_order']}
    for pick in data['picks']:
        username = pick['username']
        entry = {
            'pick':   pick['pickNumber'],
            'round':  pick['round'],
            'team':   username,
            'player': pick['participantName'],
            'sport':  pick['sport'],
        }
        league['pick_history'].append(entry)
        if username in league['team_rosters']:
            league['team_rosters'][username].append({
                'pick':   pick['pickNumber'],
                'player': pick['participantName'],
                'sport':  pick['sport'],
            })
    league['api_available']    = True
    league['using_sample_data'] = False

# ---------------------------------------------------------------------------
# Shared Discord response helpers
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Shared autocomplete
# ---------------------------------------------------------------------------

async def brackt_username_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> list[app_commands.Choice[str]]:
    league = load_league(interaction.channel_id)
    if not league or not league.get('draft_order'):
        return []
    choices = []
    for username in league['draft_order']:
        handle  = league['handles'].get(username, username)
        display = f'{handle} ({username})'
        if current.lower() in username.lower() or current.lower() in handle.lower():
            choices.append(app_commands.Choice(name=display, value=username))
    return choices[:25]
