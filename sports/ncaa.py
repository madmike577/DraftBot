"""
sports/ncaa.py — NCAA tournament fixture data and command handlers (men's and women's).
"""

import datetime
import requests
import discord

from config import (
    NCAA_BASE, ESPN_LEAGUE, ESPN_ROUND_MAP, NCAA_ROUND_LABELS,
    NCAA_SHOW_ALL_ROUNDS, NCAA_NAME_MAP, USER_AGENT,
)
from league import league_display_name, is_ephemeral
from sports.base import SportHandler


# ---------------------------------------------------------------------------
# Name helpers
# ---------------------------------------------------------------------------

def normalize_ncaa_name(brackt_name: str) -> str:
    return NCAA_NAME_MAP.get(brackt_name, brackt_name)

def ncaa_names_match(api_name: str, normalized_brackt: str) -> bool:
    return api_name.strip().lower() == normalized_brackt.strip().lower()


# ---------------------------------------------------------------------------
# ESPN API
# ---------------------------------------------------------------------------

def espn_parse_round(notes: list) -> tuple[str, str]:
    for note in notes:
        headline    = note.get('headline', '').lower()
        round_label = ''
        for key, label in ESPN_ROUND_MAP.items():
            if key in headline:
                round_label = label
                break
        if not round_label:
            continue
        region = ''
        for r in ('east', 'south', 'midwest', 'west'):   # midwest before west
            if r in headline:
                region = r.capitalize()
                break
        return round_label, region
    return '', ''

def espn_normalize_game(event: dict) -> dict | None:
    competitions = event.get('competitions', [])
    if not competitions:
        return None
    comp = competitions[0]

    notes         = comp.get('notes', [])
    bracket_round, region = espn_parse_round(notes)
    if not bracket_round or bracket_round == 'First Four':
        return None

    competitors = comp.get('competitors', [])
    if len(competitors) < 2:
        return None

    home_c = next((c for c in competitors if c.get('homeAway') == 'home'), competitors[0])
    away_c = next((c for c in competitors if c.get('homeAway') == 'away'), competitors[1])

    def parse_competitor(c: dict) -> dict:
        team   = c.get('team', {})
        seed   = str(c.get('curatedRank', {}).get('current', '') or '')
        if not seed or seed == '99':
            seed = ''
        score  = c.get('score', '')
        winner = c.get('winner', False)
        name   = team.get('shortDisplayName', team.get('displayName', '?'))
        return {'short': name, 'seed': seed, 'score': score, 'winner': winner}

    home_parsed = parse_competitor(home_c)
    away_parsed = parse_competitor(away_c)

    if home_c.get('curatedRank', {}).get('current') == 99:
        home_parsed['short'] = 'TBD (First Four)'
        home_parsed['seed']  = ''
    if away_c.get('curatedRank', {}).get('current') == 99:
        away_parsed['short'] = 'TBD (First Four)'
        away_parsed['seed']  = ''

    status      = comp.get('status', {})
    status_type = status.get('type', {})
    state_name  = status_type.get('name', '').lower()

    if 'final' in state_name:
        game_state = 'final'
    elif 'progress' in state_name or 'halftime' in state_name:
        game_state = 'live'
    else:
        game_state = 'pre'

    period     = status.get('period', '')
    clock      = status.get('displayClock', '')
    period_str = f'{period}H' if period else ''

    date_str = event.get('date', '')
    epoch    = ''
    if date_str:
        try:
            dt    = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            epoch = str(int(dt.timestamp()))
        except ValueError:
            pass

    return {
        'away':          away_parsed,
        'home':          home_parsed,
        'bracketRound':  bracket_round,
        'region':        region,
        'gameState':     game_state,
        'startTimeEpoch': epoch,
        'currentPeriod': period_str,
        'contestClock':  clock,
    }

def fetch_ncaa_scoreboard(gender: str, date: datetime.date) -> list | None:
    league   = ESPN_LEAGUE.get(gender, 'mens-college-basketball')
    date_str = date.strftime('%Y%m%d')
    url      = f'{NCAA_BASE}/{league}/scoreboard'
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
        return [g for event in events if (g := espn_normalize_game(event))]
    except Exception as e:
        print(f'ESPN NCAA scoreboard error ({gender} {date}): {e}')
        return None

def fetch_ncaa_tournament_window(gender: str, days_ahead: int = 14) -> list:
    all_games = []
    today     = datetime.date.today()
    for i in range(days_ahead):
        games = fetch_ncaa_scoreboard(gender, today + datetime.timedelta(days=i))
        if games:
            all_games.extend(games)
    all_games.sort(key=lambda g: int(g.get('startTimeEpoch', 0) or 0))
    return all_games

def ncaa_team_names(game: dict) -> tuple:
    away = game.get('away', {})
    home = game.get('home', {})
    return (
        away.get('short', '?'),
        str(away.get('seed', '') or ''),
        home.get('short', '?'),
        str(home.get('seed', '') or ''),
    )

def find_ncaa_team_game(games: list, brackt_name: str) -> dict | None:
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
    for brackt_lower, handle in team_owners.items():
        if ncaa_names_match(api_name, brackt_lower):
            return handle
    return ''

def ncaa_format_game_line(g: dict, team_owners: dict) -> str:
    away_name, away_seed, home_name, home_seed = ncaa_team_names(g)
    away_owner = ncaa_get_owner(away_name, team_owners)
    home_owner = ncaa_get_owner(home_name, team_owners)

    def fmt_side(name, seed, owner):
        seed_str  = f'({seed}) ' if seed else ''
        owner_str = f' ⬅ {owner}' if owner else ''
        return f'{seed_str}**{name}**{owner_str}'

    away_str = fmt_side(away_name, away_seed, away_owner)
    home_str = fmt_side(home_name, home_seed, home_owner)
    state    = g.get('gameState', '')

    if state == 'final':
        a_score = g.get('away', {}).get('score', '')
        h_score = g.get('home', {}).get('score', '')
        a_won   = g.get('away', {}).get('winner', False)
        if away_owner and not home_owner:
            result = '✅' if a_won else '❌'
        elif home_owner and not away_owner:
            result = '✅' if not a_won else '❌'
        else:
            result = '🏁'
        return f'{result} {away_str}  vs  {home_str}  Final {a_score}-{h_score}'
    elif state == 'live':
        a_score  = g.get('away', {}).get('score', '')
        h_score  = g.get('home', {}).get('score', '')
        period   = g.get('currentPeriod', '')
        clock    = g.get('contestClock', '')
        live_str = f'{period} {clock}'.strip() or 'LIVE'
        return f'🔴 {away_str}  vs  {home_str}  {a_score}-{h_score} ({live_str})'
    else:
        ts = ncaa_epoch_to_ts(g.get('startTimeEpoch'))
        return f'🏀 {away_str}  vs  {home_str}  {ts}'


# ---------------------------------------------------------------------------
# Handler — covers both men's and women's
# ---------------------------------------------------------------------------

class NCAAHandler(SportHandler):
    sport_names = [
        'NCAAM Basketball',
        'NCAAW Basketball',
        "NCAA Basketball - Men's",
        "NCAA Basketball - Women's",
    ]

    def _resolve(self, sport: str) -> tuple[str, str, str, str]:
        """Return (gender, pick_sport, sport_label, emoji)."""
        if sport in ('NCAAM Basketball', "NCAA Basketball - Men's"):
            return 'men', 'NCAAM Basketball', "NCAA Men's Basketball", '🏀'
        return 'women', 'NCAAW Basketball', "NCAA Women's Basketball", '🏀'

    async def schedule(self, interaction: discord.Interaction, league: dict, display: str) -> None:
        sport  = interaction.namespace.sport
        gender, pick_sport, sport_label, emoji = self._resolve(sport)

        if not any(p['sport'] == pick_sport for p in league.get('pick_history', [])):
            await interaction.response.send_message(
                f'❌ No {sport_label} picks found in this league.', ephemeral=True
            ); return

        await interaction.response.defer(ephemeral=is_ephemeral(display))
        games = fetch_ncaa_tournament_window(gender, days_ahead=14)

        if not games:
            await interaction.followup.send(
                f'{emoji} **{sport_label}** · {league_display_name(league)}\n'
                '📋 No tournament games found in the next 14 days.',
                ephemeral=is_ephemeral(display)
            ); return

        current_round = None
        for g in games:
            if g.get('gameState') != 'final':
                current_round = NCAA_ROUND_LABELS.get(g.get('bracketRound', ''), g.get('bracketRound', ''))
                break
        if not current_round:
            current_round = NCAA_ROUND_LABELS.get(games[-1].get('bracketRound', ''), 'Tournament')

        show_all = current_round in NCAA_SHOW_ALL_ROUNDS

        team_owners: dict[str, str] = {}
        for p in league['pick_history']:
            if p['sport'] == pick_sport:
                norm   = normalize_ncaa_name(p['player'])
                handle = league['handles'].get(p['team'], p['team'])
                team_owners[norm.lower()] = handle

        region_order = ['East', 'South', 'West', 'Midwest', '']
        by_region: dict[str, list] = {r: [] for r in region_order}

        for g in games:
            round_label = NCAA_ROUND_LABELS.get(g.get('bracketRound', ''), g.get('bracketRound', ''))
            if round_label != current_round:
                continue
            away_name, _, home_name, _ = ncaa_team_names(g)
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

    async def nextmatch(self, interaction: discord.Interaction, league: dict) -> None:
        sport  = interaction.namespace.sport
        gender, pick_sport, sport_label, emoji = self._resolve(sport)

        if not any(p['sport'] == pick_sport for p in league.get('pick_history', [])):
            await interaction.response.send_message(
                f'❌ No {sport_label} picks found in this league.', ephemeral=True
            ); return

        sender_id  = str(interaction.user.id)
        user_teams = [u for u, uid in league['players'].items() if uid == sender_id]
        if not user_teams:
            await interaction.response.send_message(
                '❌ Your Discord account is not mapped to any team in this league.', ephemeral=True
            ); return

        user_picks = [p['player'] for p in league['pick_history']
                      if p['sport'] == pick_sport and p['team'] in user_teams]
        if not user_picks:
            await interaction.response.send_message(
                f'❌ You have no {sport_label} picks in this league.', ephemeral=True
            ); return

        await interaction.response.defer(ephemeral=True)
        games = fetch_ncaa_tournament_window(gender, days_ahead=14)
        lines = [f'{emoji} **Your {sport_label} team{"s" if len(user_picks) > 1 else ""}:**\n']

        for brackt_name in user_picks:
            normalized = normalize_ncaa_name(brackt_name)
            game       = find_ncaa_team_game(games, brackt_name)

            if not game:
                past_games = []
                today = datetime.date.today()
                for i in range(1, 4):
                    dg = fetch_ncaa_scoreboard(gender, today - datetime.timedelta(days=i))
                    if dg:
                        past_games.extend(dg)
                past_game = find_ncaa_team_game(past_games, brackt_name)
                if past_game and past_game.get('gameState') == 'final':
                    away_name, _, home_name, _ = ncaa_team_names(past_game)
                    my_away     = ncaa_names_match(away_name, normalized)
                    won         = (my_away and past_game.get('away', {}).get('winner')) or \
                                  (not my_away and past_game.get('home', {}).get('winner'))
                    round_label = NCAA_ROUND_LABELS.get(past_game.get('bracketRound', ''),
                                                        past_game.get('bracketRound', ''))
                    if won:
                        lines.append(f'**{brackt_name}** — ✅ Advanced from {round_label}, awaiting next opponent')
                    else:
                        lines.append(f'**{brackt_name}** — ❌ Eliminated in {round_label}')
                else:
                    lines.append(f'**{brackt_name}** — No upcoming games found')
                continue

            round_raw   = game.get('bracketRound', '')
            round_label = NCAA_ROUND_LABELS.get(round_raw, round_raw)
            away_name, away_seed, home_name, home_seed = ncaa_team_names(game)
            state   = game.get('gameState', '')
            my_away = ncaa_names_match(away_name, normalized)
            my_seed = away_seed if my_away else home_seed
            opp_name = home_name if my_away else away_name
            opp_seed = home_seed if my_away else away_seed
            seed_str = f'({my_seed}) ' if my_seed else ''
            opp_str  = f'({opp_seed}) {opp_name}' if opp_seed else opp_name

            if state == 'final':
                a_score = game.get('away', {}).get('score', '')
                h_score = game.get('home', {}).get('score', '')
                won     = (my_away and game.get('away', {}).get('winner')) or \
                          (not my_away and game.get('home', {}).get('winner'))
                my_score    = a_score if my_away else h_score
                their_score = h_score if my_away else a_score
                result = '✅ Won' if won else '❌ Lost'
                lines.append(f'{seed_str}**{brackt_name}** — {result} · {round_label}\n'
                              f'   vs {opp_str} — Final {my_score}–{their_score}')
            elif state == 'live':
                a_score  = game.get('away', {}).get('score', '')
                h_score  = game.get('home', {}).get('score', '')
                my_score = a_score if my_away else h_score
                opp_score = h_score if my_away else a_score
                period   = game.get('currentPeriod', '')
                clock    = game.get('contestClock', '')
                live_str = f'{period} {clock}'.strip() or 'LIVE'
                lines.append(f'{seed_str}**{brackt_name}** — 🔴 LIVE · {round_label}\n'
                              f'   vs {opp_str} — {my_score}–{opp_score} ({live_str})')
            else:
                ts = ncaa_epoch_to_ts(game.get('startTimeEpoch'))
                lines.append(f'{seed_str}**{brackt_name}** — {round_label}\n'
                              f'   vs {opp_str} — {ts}')

        await interaction.followup.send('\n'.join(lines), ephemeral=True)


handler = NCAAHandler()
