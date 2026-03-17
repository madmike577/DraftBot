"""
sports/ucl.py — UEFA Champions League fixture data and command handlers.
"""

import datetime
import requests
import discord

from config import UCL_COMPETITION_ID, UCL_NAME_MAP, UCL_REVERSE_MAP, FOOTBALL_DATA_TOKEN
from league import league_display_name, is_ephemeral
from sports.base import SportHandler


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_ucl_fixtures() -> list | None:
    """
    Fetch UCL knockout matches from football-data.org.
    Auto-detects the current active stage — no manual updates needed.
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

        KNOCKOUT_STAGE_ORDER = ['LAST_16', 'QUARTER_FINALS', 'SEMI_FINALS', 'FINAL']
        knockout_stages = set(KNOCKOUT_STAGE_ORDER)

        by_stage: dict[str, list] = {}
        for m in matches:
            stage = m.get('stage', '')
            if stage in knockout_stages:
                by_stage.setdefault(stage, []).append(m)

        current_stage = None
        for stage in KNOCKOUT_STAGE_ORDER:
            stage_matches = by_stage.get(stage, [])
            if not stage_matches:
                continue
            if any(m.get('status') != 'FINISHED' for m in stage_matches):
                current_stage = stage
                break

        if not current_stage:
            for stage in reversed(KNOCKOUT_STAGE_ORDER):
                if stage in by_stage:
                    current_stage = stage
                    break

        if not current_stage:
            return []

        print(f'UCL current stage detected: {current_stage}')
        stage_matches = by_stage[current_stage]
        for m in stage_matches:
            m['_detected_stage'] = current_stage
        return stage_matches

    except Exception as e:
        print(f'UCL fixture fetch error: {e}')
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ucl_pick_owner(league: dict, brackt_name: str) -> str | None:
    for p in league['pick_history']:
        if p['sport'] == 'UEFA Champions League' and p['player'] == brackt_name:
            return league['handles'].get(p['team'], p['team'])
    return None

def match_score(match: dict, team_key: str):
    if not match or match.get('status') != 'FINISHED':
        return None
    s = match.get('score', {}).get('fullTime', {})
    return s.get('home') if team_key == 'home' else s.get('away')

def build_ucl_matchups(league: dict, matches: list) -> list:
    drafted = {
        UCL_NAME_MAP.get(p['player'], p['player'])
        for p in league['pick_history']
        if p['sport'] == 'UEFA Champions League'
    }

    ties: dict = {}
    for m in matches:
        home = m['homeTeam']['name']
        away = m['awayTeam']['name']
        key  = frozenset([home, away])
        if key not in ties:
            ties[key] = []
        ties[key].append(m)

    result = []
    for key, legs in ties.items():
        legs        = sorted(legs, key=lambda x: x['utcDate'])
        home_api    = legs[0]['homeTeam']['name']
        away_api    = legs[0]['awayTeam']['name']
        home_brackt = UCL_REVERSE_MAP.get(home_api, home_api)
        away_brackt = UCL_REVERSE_MAP.get(away_api, away_api)

        if home_api not in drafted and away_api not in drafted:
            continue

        home_owner = ucl_pick_owner(league, home_brackt)
        away_owner = ucl_pick_owner(league, away_brackt)

        leg1     = legs[0] if len(legs) > 0 else None
        leg2     = legs[1] if len(legs) > 1 else None
        is_final = leg1 and leg1.get('_detected_stage') == 'FINAL'

        l1_home   = match_score(leg1, 'home')
        l1_away   = match_score(leg1, 'away')
        l1_played = l1_home is not None

        l2_home   = match_score(leg2, 'home')
        l2_away   = match_score(leg2, 'away')
        l2_played = l2_home is not None

        agg_home = (l1_home or 0) + (l2_away or 0)
        agg_away = (l1_away or 0) + (l2_home or 0)

        if leg2 and leg2['status'] != 'FINISHED':
            next_date = leg2['utcDate']
        elif leg1 and leg1['status'] != 'FINISHED':
            next_date = leg1['utcDate']
        else:
            next_date = leg2['utcDate'] if leg2 else leg1['utcDate']

        result.append({
            'home_brackt': home_brackt,
            'away_brackt': away_brackt,
            'home_owner':  home_owner,
            'away_owner':  away_owner,
            'leg1': leg1, 'leg2': leg2,
            'l1_home': l1_home, 'l1_away': l1_away,
            'l2_home': l2_home, 'l2_away': l2_away,
            'l1_played': l1_played, 'l2_played': l2_played,
            'agg_home': agg_home, 'agg_away': agg_away,
            'next_date': next_date,
            'is_final':  is_final,
        })

    return sorted(result, key=lambda x: x['next_date'])

def format_ucl_tie(t: dict) -> str:
    home   = t['home_brackt']
    away   = t['away_brackt']
    home_o = f" ({t['home_owner']})" if t['home_owner'] else ''
    away_o = f" ({t['away_owner']})" if t['away_owner'] else ''
    is_final = t.get('is_final', False)

    if is_final:
        if t['l1_played']:
            h, a = t['l1_home'], t['l1_away']
            if h > a:
                return f'🏆 **{home}{home_o}** are Champions! Beat **{away}{away_o}** {h}–{a}'
            elif a > h:
                return f'🏆 **{away}{away_o}** are Champions! Beat **{home}{home_o}** {a}–{h}'
            else:
                return f'🏆 **{home}{home_o}** vs **{away}{away_o}** — {h}–{h} (decided by pens)'
        else:
            leg1_ts = int(datetime.datetime.fromisoformat(
                t['leg1']['utcDate'].replace('Z', '+00:00')).timestamp()) if t['leg1'] else None
            date_str = f'<t:{leg1_ts}:F>' if leg1_ts else 'TBD'
            return f'🏆 **UCL Final:** **{home}{home_o}** vs **{away}{away_o}**\n   {date_str}'

    if t['l2_played']:
        agg_home = t['agg_home']
        agg_away = t['agg_away']
        if agg_home > agg_away:
            winner, loser     = home, away
            winner_o, loser_o = home_o, away_o
            agg_w, agg_l      = agg_home, agg_away
        elif agg_away > agg_home:
            winner, loser     = away, home
            winner_o, loser_o = away_o, home_o
            agg_w, agg_l      = agg_away, agg_home
        else:
            return (
                f'✅ **{home}{home_o}** vs **{away}{away_o}** — '
                f'{agg_home}–{agg_away} agg (decided by extra time/pens)'
            )
        return f'✅ **{winner}{winner_o}** beat **{loser}{loser_o}** {agg_w}–{agg_l} on aggregate'

    elif t['l1_played']:
        leg2_ts  = int(datetime.datetime.fromisoformat(
            t['leg2']['utcDate'].replace('Z', '+00:00')).timestamp()) if t['leg2'] else None
        date_str = f'<t:{leg2_ts}:F>' if leg2_ts else 'TBD'
        if t['l1_home'] > t['l1_away']:
            lead_str = f'{home} leads {t["l1_home"]}–{t["l1_away"]} from leg 1'
        elif t['l1_away'] > t['l1_home']:
            lead_str = f'{away} leads {t["l1_away"]}–{t["l1_home"]} from leg 1'
        else:
            lead_str = f'Level {t["l1_home"]}–{t["l1_away"]} from leg 1'
        return f'⏳ **{home}{home_o}** vs **{away}{away_o}**\n   Leg 2: {date_str} · {lead_str}'
    else:
        leg1_ts  = int(datetime.datetime.fromisoformat(
            t['leg1']['utcDate'].replace('Z', '+00:00')).timestamp()) if t['leg1'] else None
        date_str = f'<t:{leg1_ts}:F>' if leg1_ts else 'TBD'
        return f'🔜 **{home}{home_o}** vs **{away}{away_o}**\n   Leg 1: {date_str}'


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class UCLHandler(SportHandler):
    sport_names = ['UEFA Champions League']

    async def schedule(self, interaction: discord.Interaction, league: dict, display: str) -> None:
        if not any(p['sport'] == 'UEFA Champions League' for p in league.get('pick_history', [])):
            await interaction.response.send_message(
                '❌ No UEFA Champions League picks found in this league.', ephemeral=True
            ); return

        await interaction.response.defer(ephemeral=is_ephemeral(display))
        matches = fetch_ucl_fixtures()
        if matches is None:
            await interaction.followup.send(
                '❌ Could not reach the football data API. Try again later.', ephemeral=True
            ); return

        ties = build_ucl_matchups(league, matches)
        if not ties:
            await interaction.followup.send(
                '❌ No UCL fixtures found involving drafted clubs.', ephemeral=True
            ); return

        lines = [f'🏆 **UEFA Champions League** · {league_display_name(league)}\n']
        for t in ties:
            lines.append(format_ucl_tie(t))
        await interaction.followup.send('\n'.join(lines), ephemeral=is_ephemeral(display))

    async def nextmatch(self, interaction: discord.Interaction, league: dict) -> None:
        if not any(p['sport'] == 'UEFA Champions League' for p in league.get('pick_history', [])):
            await interaction.response.send_message(
                '❌ No UEFA Champions League picks found in this league.', ephemeral=True
            ); return

        sender_id  = str(interaction.user.id)
        user_teams = [u for u, uid in league['players'].items() if uid == sender_id]
        if not user_teams:
            await interaction.response.send_message(
                '❌ Your Discord account is not mapped to any team in this league.',
                ephemeral=True
            ); return

        user_picks = [
            p['player'] for p in league['pick_history']
            if p['sport'] == 'UEFA Champions League' and p['team'] in user_teams
        ]
        if not user_picks:
            await interaction.response.send_message(
                '❌ You have no UEFA Champions League picks in this league.', ephemeral=True
            ); return

        await interaction.response.defer(ephemeral=True)
        matches = fetch_ucl_fixtures()
        if matches is None:
            await interaction.followup.send(
                '❌ Could not reach the football data API. Try again later.', ephemeral=True
            ); return

        ties           = build_ucl_matchups(league, matches)
        user_api_names = {UCL_NAME_MAP.get(p, p) for p in user_picks}

        relevant = []
        for t in ties:
            home_api = UCL_NAME_MAP.get(t['home_brackt'], t['home_brackt'])
            away_api = UCL_NAME_MAP.get(t['away_brackt'], t['away_brackt'])
            if home_api in user_api_names or away_api in user_api_names:
                relevant.append(t)

        if not relevant:
            await interaction.followup.send(
                '✅ All your UCL teams have finished their fixtures.', ephemeral=True
            ); return

        lines = [f'📅 **Your next UCL match{"es" if len(relevant) > 1 else ""}:**\n']
        for t in relevant:
            lines.append(format_ucl_tie(t))
        await interaction.followup.send('\n'.join(lines), ephemeral=True)


handler = UCLHandler()
