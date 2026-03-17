import os
import datetime
from discord import app_commands
from dotenv import load_dotenv

# Resolve .env path relative to this file so it works from any working directory
_here = os.path.dirname(os.path.abspath(__file__))

if os.path.exists('/home/madmike/www/.env'):
    load_dotenv(dotenv_path='/home/madmike/www/.env')
else:
    load_dotenv(dotenv_path=os.path.join(_here, '.env'))

# API tokens — loaded here so all modules can import them from config
FOOTBALL_DATA_TOKEN = os.getenv('FOOTBALL_DATA_TOKEN')
BALLDONTLIE_TOKEN   = os.getenv('BALLDONTLIE_TOKEN')

LEAGUES_DIR   = 'leagues'
USER_AGENT    = 'BracktDraftNotify/1.0'
POLL_INTERVAL = 20

DISPLAY_CHOICES = [
    app_commands.Choice(name="public",  value="public"),
    app_commands.Choice(name="private", value="private"),
]

# ---------------------------------------------------------------------------
# UCL
# ---------------------------------------------------------------------------
UCL_COMPETITION_ID = 'CL'

UCL_NAME_MAP = {
    'Arsenal':             'Arsenal FC',
    'Bayern Munich':       'FC Bayern München',
    'Barcelona':           'FC Barcelona',
    'Paris Saint-Germain': 'Paris Saint-Germain FC',
    'Manchester City':     'Manchester City FC',
    'Liverpool':           'Liverpool FC',
    'Chelsea':             'Chelsea FC',
    'Atlético Madrid':     'Club Atlético de Madrid',
    'Newcastle United':    'Newcastle United FC',
    'Tottenham Hotspur':   'Tottenham Hotspur FC',
    'Real Madrid':         'Real Madrid CF',
    'Galatasaray':         'Galatasaray SK',
    'Atalanta':            'Atalanta BC',
    'Bayer Leverkusen':    'Bayer 04 Leverkusen',
    'Bodø/Glimt':          'FK Bodø/Glimt',
    'Sporting CP':         'Sporting Clube de Portugal',
}
UCL_REVERSE_MAP = {v: k for k, v in UCL_NAME_MAP.items()}

# ---------------------------------------------------------------------------
# NBA
# ---------------------------------------------------------------------------
BDL_BASE   = 'https://api.balldontlie.io/v1'
NBA_SEASON = 2025

NBA_PLAYIN_START = datetime.date(2026, 4, 14)
NBA_PLAYIN_END   = datetime.date(2026, 4, 17)

NBA_CUP_GAME_IDS = {
    20377171,  # 2025-26 NBA Cup Final: Knicks vs Spurs, Dec 16 2025
}

NBA_NAME_MAP = {
    'Boston Celtics':         'Boston Celtics',
    'Charlotte Hornets':      'Charlotte Hornets',
    'Cleveland Cavaliers':    'Cleveland Cavaliers',
    'Denver Nuggets':         'Denver Nuggets',
    'Detroit Pistons':        'Detroit Pistons',
    'Golden State Warriors':  'Golden State Warriors',
    'Houston Rockets':        'Houston Rockets',
    'LA Lakers':              'Los Angeles Lakers',
    'Miami Heat':             'Miami Heat',
    'Minnesota Timberwolves': 'Minnesota Timberwolves',
    'New York Knicks':        'New York Knicks',
    'Oklahoma City Thunder':  'Oklahoma City Thunder',
    'Orlando Magic':          'Orlando Magic',
    'Philadelphia 76ers':     'Philadelphia 76ers',
    'Phoenix Suns':           'Phoenix Suns',
    'San Antonio Spurs':      'San Antonio Spurs',
    'Toronto Raptors':        'Toronto Raptors',
}

NBA_TEAM_IDS = {
    'Boston Celtics':         2,
    'Charlotte Hornets':      4,
    'Cleveland Cavaliers':    6,
    'Denver Nuggets':         7,
    'Detroit Pistons':        8,
    'Golden State Warriors':  10,
    'Houston Rockets':        11,
    'Los Angeles Lakers':     14,
    'Miami Heat':             16,
    'Minnesota Timberwolves': 18,
    'New York Knicks':        20,
    'Oklahoma City Thunder':  21,
    'Orlando Magic':          22,
    'Philadelphia 76ers':     23,
    'Phoenix Suns':           24,
    'San Antonio Spurs':      27,
    'Toronto Raptors':        28,
}

# ---------------------------------------------------------------------------
# Formula 1
# ---------------------------------------------------------------------------
OPENF1_BASE  = 'https://api.openf1.org/v1'
F1_SEASON    = 2026

F1_CANCELLED_RACES = {
    'Bahrain Grand Prix',
    'Saudi Arabian Grand Prix',
}

F1_DRIVER_NUMBERS = {
    'Max Verstappen':         3,
    'Lando Norris':           1,
    'Charles Leclerc':       16,
    'Lewis Hamilton':        44,
    'George Russell':        63,
    'Oscar Piastri':         81,
    'Carlos Sainz':          55,
    'Fernando Alonso':       14,
    'Pierre Gasly':          10,
    'Esteban Ocon':          31,
    'Lance Stroll':          18,
    'Alex Albon':            23,
    'Liam Lawson':           30,
    'Isack Hadjar':           6,
    'Andrea Kimi Antonelli': 12,
    'Oliver Bearman':        87,
    'Arvid Lindblad':        41,
    'Gabriel Bortoleto':      5,
    'Nico Hülkenberg':       27,
    'Franco Colapinto':      43,
    'Sergio Perez':          11,
    'Valtteri Bottas':       77,
}

# ---------------------------------------------------------------------------
# IndyCar
# ---------------------------------------------------------------------------
INDYCAR_STANDINGS_URL  = 'https://www.indycar.com/Standings'
INDYCAR_SCOREBOARD_URL = 'https://site.api.espn.com/apis/site/v2/sports/racing/irl/scoreboard'
INDYCAR_USER_AGENT     = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

# ---------------------------------------------------------------------------
# NCAA
# ---------------------------------------------------------------------------
NCAA_BASE = 'https://site.api.espn.com/apis/site/v2/sports/basketball'

ESPN_LEAGUE = {
    'men':   'mens-college-basketball',
    'women': 'womens-college-basketball',
}

ESPN_ROUND_MAP = {
    'first four':           'First Four',
    '1st round':            'First Round',
    'first round':          'First Round',
    '2nd round':            'Second Round',
    'second round':         'Second Round',
    'sweet 16':             'Sweet 16',
    'sweet sixteen':        'Sweet 16',
    'elite eight':          'Elite Eight',
    'elite 8':              'Elite Eight',
    'final four':           'Final Four',
    'national championship':'Championship',
    'championship':         'Championship',
}

NCAA_ROUND_LABELS = {
    'First Four':   'First Four',
    'First Round':  'Round of 64',
    'Second Round': 'Round of 32',
    'Sweet 16':     'Sweet Sixteen',
    'Elite Eight':  'Elite Eight',
    'Final Four':   'Final Four',
    'Championship': 'Championship',
}

NCAA_SHOW_ALL_ROUNDS = {'Sweet Sixteen', 'Elite Eight', 'Final Four', 'Championship'}

NCAA_NAME_MAP = {
    'Ohio St.':            'Ohio State',
    'Michigan St.':        'Michigan St',
    'Iowa St.':            'Iowa State',
    "St. John's":          "St John's",
    'Connecticut (UConn)': 'UConn',
    'Connecticut':         'UConn',
}
