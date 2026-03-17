"""
sports/indycar.py — IndyCar fixture data and command handlers.
"""

import datetime
import unicodedata
import requests
import discord
from bs4 import BeautifulSoup

from config import INDYCAR_STANDINGS_URL, INDYCAR_SCOREBOARD_URL, INDYCAR_USER_AGENT
from league import league_display_name, is_ephemeral
from sports.base import SportHandler


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------

def indycar_normalize_name(name: str) -> str:
    """
    Normalize driver names for consistent matching between brackt.com
    (curly apostrophes, accents) and indycar.com (straight apostrophes).
    """
    name = name.replace('\u2019', "'").replace('\u2018', "'").replace('\u02bc', "'")
    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    return name.strip()


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_indycar_standings() -> list | None:
    """Scrape championship standings from indycar.com/Standings."""
    try:
        resp = requests.get(
            INDYCAR_STANDINGS_URL,
            headers={'User-Agent': INDYCAR_USER_AGENT},
            timeout=15
        )
        if resp.status_code != 200:
            print(f'IndyCar standings HTTP {resp.status_code}')
            return None
        soup  = BeautifulSoup(resp.text, 'html.parser')
        table = soup.find('table')
        if not table:
            print('IndyCar standings: no table found')
            return None

        standings = []
        for row in table.find_all('tr'):
            cells = [td.get_text(strip=True) for td in row.find_all('td')]
            if len(cells) < 5:
                continue
            try:
                rank        = int(cells[0])
                raw_name    = cells[2]
                name        = indycar_normalize_name(raw_name)
                points      = int(cells[5])
                behind_str  = cells[6]
                behind      = int(behind_str) if behind_str.lstrip('-').isdigit() else 0
                standings.append({'rank': rank, 'name': name, 'points': points, 'behind': behind})
            except (ValueError, IndexError):
                continue

        return standings if standings else None

    except Exception as e:
        print(f'IndyCar standings scrape error: {e}')
        return None

def fetch_indycar_schedule() -> dict | None:
    """Fetch IndyCar schedule from ESPN scoreboard."""
    try:
        resp = requests.get(INDYCAR_SCOREBOARD_URL, timeout=10)
        if resp.status_code != 200:
            print(f'IndyCar ESPN scoreboard HTTP {resp.status_code}')
            return None
        data     = resp.json()
        calendar = data.get('leagues', [{}])[0].get('calendar', [])
        return {'calendar': calendar}
    except Exception as e:
        print(f'IndyCar ESPN scoreboard error: {e}')
        return None

def indycar_upcoming_races(calendar: list) -> list:
    now      = datetime.datetime.now(datetime.timezone.utc)
    upcoming = []
    for entry in calendar:
        date_str = entry.get('startDate', '')
        if not date_str:
            continue
        try:
            dt = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            if dt > now:
                upcoming.append({'name': entry['label'], 'dt': dt})
        except ValueError:
            continue
    upcoming.sort(key=lambda x: x['dt'])
    return upcoming

def indycar_race_ts(dt: datetime.datetime) -> str:
    return f'<t:{int(dt.timestamp())}:F>'


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class IndyCarHandler(SportHandler):
    sport_names = ['Indycar Series']

    async def schedule(self, interaction: discord.Interaction, league: dict, display: str) -> None:
        if not any(p['sport'] == 'Indycar Series' for p in league.get('pick_history', [])):
            await interaction.response.send_message(
                '❌ No IndyCar picks found in this league.', ephemeral=True
            ); return

        await interaction.response.defer(ephemeral=is_ephemeral(display))
        standings = fetch_indycar_standings()
        schedule  = fetch_indycar_schedule()
        if standings is None or schedule is None:
            await interaction.followup.send(
                '❌ Could not reach IndyCar data. Try again later.', ephemeral=True
            ); return

        driver_owners = {}
        for p in league['pick_history']:
            if p['sport'] == 'Indycar Series':
                handle = league['handles'].get(p['team'], p['team'])
                driver_owners[indycar_normalize_name(p['player'])] = handle

        standing_lines = []
        for s in standings[:10]:
            name   = s['name']
            owner  = driver_owners.get(name)
            marker = f' ⬅ {owner}' if owner else ''
            standing_lines.append(f'`P{s["rank"]:>2}` **{name}** — {s["points"]} pts{marker}')

        upcoming   = indycar_upcoming_races(schedule['calendar'])
        race_lines = [f'• **{r["name"]}** — {indycar_race_ts(r["dt"])}' for r in upcoming[:3]]

        lines = [
            f'🏎️ **IndyCar Series** · {league_display_name(league)}',
            f'**{len(upcoming)} races remaining**\n',
            '**Driver Championship (Top 10):**',
            *standing_lines,
            '\n**Next 3 Races:**',
            *race_lines,
        ]
        await interaction.followup.send('\n'.join(lines), ephemeral=is_ephemeral(display))

    async def nextmatch(self, interaction: discord.Interaction, league: dict) -> None:
        if not any(p['sport'] == 'Indycar Series' for p in league.get('pick_history', [])):
            await interaction.response.send_message(
                '❌ No IndyCar picks found in this league.', ephemeral=True
            ); return

        sender_id  = str(interaction.user.id)
        user_teams = [u for u, uid in league['players'].items() if uid == sender_id]
        if not user_teams:
            await interaction.response.send_message(
                '❌ Your Discord account is not mapped to any team in this league.', ephemeral=True
            ); return

        user_picks = [p['player'] for p in league['pick_history']
                      if p['sport'] == 'Indycar Series' and p['team'] in user_teams]
        if not user_picks:
            await interaction.response.send_message(
                '❌ You have no IndyCar picks in this league.', ephemeral=True
            ); return

        await interaction.response.defer(ephemeral=True)
        standings = fetch_indycar_standings()
        schedule  = fetch_indycar_schedule()
        if standings is None or schedule is None:
            await interaction.followup.send(
                '❌ Could not reach IndyCar data. Try again later.', ephemeral=True
            ); return

        standings_map = {s['name']: s for s in standings}
        upcoming      = indycar_upcoming_races(schedule['calendar'])
        next_race     = upcoming[0] if upcoming else None

        lines = [f'🏎️ **Your IndyCar driver{"s" if len(user_picks) > 1 else ""}:**\n']
        if next_race:
            lines.append(f'📅 **Next Race:** {next_race["name"]} — {indycar_race_ts(next_race["dt"])}\n')
        else:
            lines.append('📅 **Next Race:** Season complete\n')

        for driver_name in user_picks:
            norm = indycar_normalize_name(driver_name)
            s    = standings_map.get(norm)
            if not s:
                lines.append(f'**{driver_name}** — No standings data found')
                continue
            lines.append(f'**{driver_name}** — P{s["rank"]} · {s["points"]} pts')

        await interaction.followup.send('\n'.join(lines), ephemeral=True)


handler = IndyCarHandler()
