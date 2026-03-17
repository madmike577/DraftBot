"""
sports/nba.py — NBA fixture data and command handlers.
"""

import datetime
import requests
import discord
from collections import Counter

from config import (
    BDL_BASE, NBA_SEASON, NBA_PLAYIN_START, NBA_PLAYIN_END,
    NBA_CUP_GAME_IDS, NBA_NAME_MAP, NBA_TEAM_IDS, BALLDONTLIE_TOKEN,
)
from league import league_display_name, is_ephemeral
from sports.base import SportHandler


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

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
        print('BDL rate limit hit')
        return None
    if resp.status_code != 200:
        print(f'BDL error {resp.status_code}')
        return None
    return resp.json()

def fetch_nba_team_data(team_id: int) -> dict | None:
    team_id   = int(team_id)
    today     = datetime.date.today()
    yesterday = (today - datetime.timedelta(days=1)).isoformat()
    today_str = today.isoformat()

    wins, losses = 0, 0
    seen_ids = set()
    cursor   = None
    while True:
        params = {
            'team_ids[]':  team_id,
            'postseason':  'false',
            'start_date':  f'{NBA_SEASON}-10-01',
            'end_date':    yesterday,
            'per_page':    100,
        }
        if cursor:
            params['cursor'] = cursor
        data = bdl_get(params)
        if data is None:
            return None
        for g in data['data']:
            if g['status'] != 'Final':
                continue
            if g['id'] in NBA_CUP_GAME_IDS or g['id'] in seen_ids:
                continue
            seen_ids.add(g['id'])
            home_id = int(g['home_team']['id'])
            if home_id == team_id:
                wins += 1 if g['home_team_score'] > g['visitor_team_score'] else 0
                losses += 1 if g['home_team_score'] < g['visitor_team_score'] else 0
            else:
                wins += 1 if g['visitor_team_score'] > g['home_team_score'] else 0
                losses += 1 if g['visitor_team_score'] < g['home_team_score'] else 0
        cursor = data.get('meta', {}).get('next_cursor')
        if not cursor:
            break

    data2      = bdl_get({'team_ids[]': team_id, 'postseason': 'false',
                           'start_date': today_str, 'per_page': 10})
    live_game  = None
    next_game  = None
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
    try:
        data = bdl_get({'seasons[]': NBA_SEASON, 'postseason': 'true', 'per_page': 100})
        if data is None:
            return None
        return data.get('data', [])
    except Exception as e:
        print(f'fetch_nba_postseason_games error: {e}')
        return None

def format_nba_datetime(game: dict) -> str:
    dt_str = game.get('datetime') or game.get('date')
    if not dt_str:
        return 'TBD'
    try:
        if 'T' in dt_str:
            dt = datetime.datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            return f'<t:{int(dt.timestamp())}:F>'
        return dt_str
    except Exception:
        return dt_str

def format_nba_game_line(game: dict, team_id: int) -> str:
    home    = game['home_team']
    visitor = game['visitor_team']
    team_id = int(team_id)
    if int(home['id']) == team_id:
        opponent   = visitor['full_name']
        location   = 'vs'
        team_score = game.get('home_team_score', 0)
        opp_score  = game.get('visitor_team_score', 0)
    else:
        opponent   = home['full_name']
        location   = '@'
        team_score = game.get('visitor_team_score', 0)
        opp_score  = game.get('home_team_score', 0)
    status = game.get('status', '')
    if is_game_live(status):
        score_str  = f'{team_score}–{opp_score}' if team_score or opp_score else ''
        score_part = f' ({score_str})' if score_str else ''
        return f'{location} {opponent}{score_part} · {status}'
    return f'{location} {opponent} — {format_nba_datetime(game)}'

def game_is_playin(game: dict) -> bool:
    date_str = game.get('date') or (game.get('datetime') or '')[:10]
    if not date_str:
        return False
    try:
        game_date = datetime.date.fromisoformat(date_str)
        return NBA_PLAYIN_START <= game_date <= NBA_PLAYIN_END
    except ValueError:
        return False

def build_nba_series(games: list, team_id: int) -> dict | None:
    if not games:
        return None
    games_sorted = sorted(games, key=lambda g: g.get('datetime') or g.get('date') or '')
    last = games_sorted[-1]
    current_opp = (last['visitor_team']['full_name']
                   if last['home_team']['id'] == team_id
                   else last['home_team']['full_name'])

    series_games = [g for g in games if
        g['home_team']['full_name'] == current_opp or
        g['visitor_team']['full_name'] == current_opp]

    team_wins = opp_wins = 0
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
    series_over   = team_wins == 4 or opp_wins == 4

    next_game = None
    if not series_over:
        upcoming = [g for g in series_games if g['status'] != 'Final']
        if upcoming:
            upcoming.sort(key=lambda g: g.get('datetime') or g.get('date') or '')
            next_game = upcoming[0]

    if team_wins > opp_wins:
        series_label = f'Won series 4–{opp_wins}' if team_wins == 4 else f'Lead series {team_wins}–{opp_wins}'
    elif opp_wins > team_wins:
        series_label = f'Lost series {team_wins}–4' if opp_wins == 4 else f'Trail series {team_wins}–{opp_wins}'
    else:
        series_label = f'Series tied {team_wins}–{opp_wins}'

    return {
        'opponent':     current_opp,
        'team_wins':    team_wins,
        'opp_wins':     opp_wins,
        'series_label': series_label,
        'next_game':    next_game,
        'is_eliminated': is_eliminated,
        'series_over':  series_over,
    }


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class NBAHandler(SportHandler):
    sport_names = ['NBA']

    async def schedule(self, interaction: discord.Interaction, league: dict, display: str) -> None:
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

        if not postseason_games:
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

        drafted_nba = [p['player'] for p in league['pick_history'] if p['sport'] == 'NBA']
        lines = [f'🏀 **NBA Playoffs** · {league_display_name(league)}\n']
        for brackt_name in drafted_nba:
            bdl_name  = brackt_to_bdl_name(brackt_name)
            team_id   = bdl_name_to_team_id(bdl_name)
            if not team_id:
                continue
            team_games = [g for g in postseason_games
                          if g['home_team']['id'] == team_id or g['visitor_team']['id'] == team_id]
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

    async def nextmatch(self, interaction: discord.Interaction, league: dict) -> None:
        if not any(p['sport'] == 'NBA' for p in league.get('pick_history', [])):
            await interaction.response.send_message(
                '❌ No NBA picks found in this league.', ephemeral=True
            ); return

        sender_id   = str(interaction.user.id)
        user_teams  = [u for u, uid in league['players'].items() if uid == sender_id]
        if not user_teams:
            await interaction.response.send_message(
                '❌ Your Discord account is not mapped to any team in this league.', ephemeral=True
            ); return

        user_picks = [p['player'] for p in league['pick_history']
                      if p['sport'] == 'NBA' and p['team'] in user_teams]
        if not user_picks:
            await interaction.response.send_message(
                '❌ You have no NBA picks in this league.', ephemeral=True
            ); return

        await interaction.response.defer(ephemeral=True)
        postseason_games = fetch_nba_postseason_games()
        if postseason_games is None:
            await interaction.followup.send(
                '❌ Could not reach the NBA data API. Try again later.', ephemeral=True
            ); return

        playoffs_started = len(postseason_games) > 0
        lines = [f'📅 **Your NBA team{"s" if len(user_picks) > 1 else ""}:**\n']

        for brackt_name in user_picks:
            bdl_name = brackt_to_bdl_name(brackt_name)
            team_id  = bdl_name_to_team_id(bdl_name)
            if not team_id:
                lines.append(f'**{brackt_name}** — ❌ Team not found in data')
                continue

            if playoffs_started:
                team_data  = fetch_nba_team_data(team_id)
                record_str = f'{team_data["wins"]}–{team_data["losses"]}' if team_data else 'N/A'
                team_post  = [g for g in postseason_games
                              if int(g['home_team']['id']) == team_id
                              or int(g['visitor_team']['id']) == team_id]
                playin_games  = [g for g in team_post if game_is_playin(g)]
                bracket_games = [g for g in team_post if not game_is_playin(g)]

                if not team_post:
                    lines.append(f'**{brackt_name}** ({record_str}) — ⏳ Awaiting playoff assignment')
                    continue

                if playin_games and not bracket_games:
                    upcoming  = [g for g in playin_games if g['status'] != 'Final']
                    completed = [g for g in playin_games if g['status'] == 'Final']
                    if upcoming:
                        next_str = format_nba_game_line(upcoming[0], team_id)
                        lines.append(f'**{brackt_name}** ({record_str}) — 🎟️ Play-In: {next_str}')
                    elif completed:
                        lines.append(f'**{brackt_name}** ({record_str}) — ❌ Eliminated in Play-In')
                    else:
                        lines.append(f'**{brackt_name}** ({record_str}) — 🎟️ Play-In pending')
                    continue

                series_games = bracket_games if bracket_games else team_post
                series = build_nba_series(series_games, team_id)
                if not series:
                    lines.append(f'**{brackt_name}** ({record_str}) — No series data')
                    continue
                if series['is_eliminated']:
                    lines.append(f'**{brackt_name}** ({record_str}) — ❌ Eliminated\n'
                                 f'   vs {series["opponent"]} · {series["series_label"]}')
                elif series['series_over']:
                    lines.append(f'**{brackt_name}** ({record_str}) — ✅ Advanced\n'
                                 f'   vs {series["opponent"]} · {series["series_label"]}')
                else:
                    next_str = format_nba_game_line(series['next_game'], team_id) if series['next_game'] else 'TBD'
                    lines.append(f'**{brackt_name}** ({record_str}) — 🏀 In Playoffs\n'
                                 f'   vs {series["opponent"]} · {series["series_label"]}\n'
                                 f'   Next: {next_str}')
            else:
                team_data = fetch_nba_team_data(team_id)
                if team_data is None:
                    lines.append(f'**{brackt_name}** — ❌ Could not fetch data (rate limit?)')
                    continue
                record_str = f'{team_data["wins"]}–{team_data["losses"]}'
                if team_data['live_game']:
                    lines.append(f'**{brackt_name}** ({record_str}) — 🔴 LIVE: '
                                 f'{format_nba_game_line(team_data["live_game"], team_id)}')
                elif team_data['next_game']:
                    lines.append(f'**{brackt_name}** ({record_str}) — Next: '
                                 f'{format_nba_game_line(team_data["next_game"], team_id)}')
                else:
                    lines.append(f'**{brackt_name}** ({record_str}) — No upcoming games found')

        await interaction.followup.send('\n'.join(lines), ephemeral=True)


handler = NBAHandler()
