"""
sports/f1.py — Formula 1 fixture data and command handlers.
"""

import datetime
import requests
import discord

from config import OPENF1_BASE, F1_SEASON, F1_CANCELLED_RACES, F1_DRIVER_NUMBERS
from league import league_display_name, is_ephemeral
from sports.base import SportHandler


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def openf1_get(endpoint: str, params: dict = None) -> list | None:
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
    sessions = openf1_get('sessions', {
        'meeting_key':  meeting_key,
        'session_type': 'Race',
    })
    if not sessions:
        return None
    date_str = sessions[0].get('date_start', '')
    if not date_str:
        return None
    try:
        dt = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return f'<t:{int(dt.timestamp())}:F>'
    except ValueError:
        return None

def meeting_race_date_ts(meeting: dict) -> str:
    date_str = meeting.get('date_end', '') or meeting.get('date_start', '')
    if not date_str:
        return 'TBD'
    try:
        dt = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return f'<t:{int(dt.timestamp())}:D>'
    except ValueError:
        return 'TBD'

def fetch_f1_standings() -> list | None:
    results = openf1_get('championship_drivers', {'session_key': 'latest'})
    if results is None:
        return None
    return sorted(results, key=lambda x: x.get('position_current', 99))

def f1_driver_number(brackt_name: str) -> int | None:
    return F1_DRIVER_NUMBERS.get(brackt_name)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class F1Handler(SportHandler):
    sport_names = ['Formula 1']

    async def schedule(self, interaction: discord.Interaction, league: dict, display: str) -> None:
        if not any(p['sport'] == 'Formula 1' for p in league.get('pick_history', [])):
            await interaction.response.send_message(
                '❌ No Formula 1 picks found in this league.', ephemeral=True
            ); return

        await interaction.response.defer(ephemeral=is_ephemeral(display))
        meetings  = fetch_f1_meetings()
        standings = fetch_f1_standings()
        if meetings is None or standings is None:
            await interaction.followup.send(
                '❌ Could not reach the F1 data API. Try again later.', ephemeral=True
            ); return

        today     = datetime.date.today().isoformat()
        upcoming  = [m for m in meetings if m.get('date_end', m.get('date_start', '')) >= today]
        races_remaining = len(upcoming)

        next_races = upcoming[:3]
        race_lines = []
        for m in next_races:
            name = m.get('meeting_name', 'Unknown GP')
            ts   = meeting_race_date_ts(m)
            race_lines.append(f'• **{name}** — {ts}')

        standings_map          = {s['driver_number']: s for s in standings}
        number_to_brackt       = {v: k for k, v in F1_DRIVER_NUMBERS.items()}
        driver_number_to_owner = {}
        for p in league['pick_history']:
            if p['sport'] == 'Formula 1' and p['player'] in F1_DRIVER_NUMBERS:
                num    = F1_DRIVER_NUMBERS[p['player']]
                handle = league['handles'].get(p['team'], p['team'])
                driver_number_to_owner[num] = handle

        if standings:
            standing_lines = []
            for s in standings[:10]:
                num    = s['driver_number']
                pos    = s.get('position_current', '?')
                pts    = int(s.get('points_current', 0))
                name   = number_to_brackt.get(num, f'#{num}')
                owner  = driver_number_to_owner.get(num)
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

    async def nextmatch(self, interaction: discord.Interaction, league: dict) -> None:
        if not any(p['sport'] == 'Formula 1' for p in league.get('pick_history', [])):
            await interaction.response.send_message(
                '❌ No Formula 1 picks found in this league.', ephemeral=True
            ); return

        sender_id  = str(interaction.user.id)
        user_teams = [u for u, uid in league['players'].items() if uid == sender_id]
        if not user_teams:
            await interaction.response.send_message(
                '❌ Your Discord account is not mapped to any team in this league.', ephemeral=True
            ); return

        user_picks = [p['player'] for p in league['pick_history']
                      if p['sport'] == 'Formula 1' and p['team'] in user_teams]
        if not user_picks:
            await interaction.response.send_message(
                '❌ You have no Formula 1 picks in this league.', ephemeral=True
            ); return

        await interaction.response.defer(ephemeral=True)
        meetings  = fetch_f1_meetings()
        standings = fetch_f1_standings()
        if meetings is None or standings is None:
            await interaction.followup.send(
                '❌ Could not reach the F1 data API. Try again later.', ephemeral=True
            ); return

        today      = datetime.date.today().isoformat()
        upcoming   = [m for m in meetings if m.get('date_end', m.get('date_start', '')) >= today]
        next_race  = upcoming[0] if upcoming else None
        standings_map = {s['driver_number']: s for s in standings}

        lines = [f'🏎️ **Your F1 driver{"s" if len(user_picks) > 1 else ""}:**\n']

        if next_race:
            name        = next_race.get('meeting_name', 'Unknown GP')
            meeting_key = next_race.get('meeting_key')
            race_ts     = fetch_f1_race_session_time(meeting_key) if meeting_key else None
            ts          = race_ts or meeting_race_date_ts(next_race)
            lines.append(f'📅 **Next Race:** {name} — {ts}\n')
        else:
            lines.append('📅 **Next Race:** Season complete\n')

        for driver_name in user_picks:
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


handler = F1Handler()
