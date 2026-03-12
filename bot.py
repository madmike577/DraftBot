import discord
from discord import app_commands
import requests
import asyncio
import json
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
API_KEY = os.getenv('API_KEY')

DRAFT_API_URL = "https://www.brackt.com/api/seasons/9fa5e354-286c-4e1c-965a-99757613e46f/draft"

CHANNEL_ID = 1474092232414990517
POLL_INTERVAL = 20
STATE_FILE = 'state.json'

DRAFT_ORDER = [
    "jom315",
    "arny7",
    "Madmike",
    "getofffmynuts3",
    "jdog1202.",
    "benziti",
    "tomy",
    "mws1395",
    "el_stove"
]

DISCORD_HANDLES = {
    "jom315":         "jom315",
    "arny7":          "arny7",
    "Madmike":        "madmike577",
    "getofffmynuts3": "getofffmynuts3",
    "jdog1202.":      "jdog1202.",
    "benziti":        "benziti",
    "tomy":           "__voids__",
    "mws1395":        "mws1395",
    "el_stove":       "el_stove"
}

DISCORD_IDS = {
    "jom315":         "329830988823658496",
    "arny7":          "702684156437594193",
    "Madmike":        "143201113800179713",
    "getofffmynuts3": "687811127975084053",
    "jdog1202.":      "661418035206291470",
    "benziti":        "685311576646877211",
    "tomy":           "173941059150282752",
    "mws1395":        "1047233099207032934",
    "el_stove":       "129316443337523200"
}

REQUIRED_SPORTS = [
    "PDC Darts",
    "NCAA Basketball - Men's",
    "NCAA Basketball - Women's",
    "NHL",
    "UEFA Champions League",
    "Little League World Series",
    "MLB",
    "WNBA",
    "PGA Golf",
    "Formula 1",
    "NCAA Football",
    "NFL",
    "Tennis - Men's",
    "Counter Strike",
    "FIFA Men's World Cup",
    "NBA"
]

SAMPLE_DATA = {"seasonId":"9fa5e354-286c-4e1c-965a-99757613e46f","status":"draft","currentPickNumber":147,"totalPicks":180,"isDraftComplete":False,"isPaused":False,"onTheClock":{"teamName":"Mr. Worldwide","username":"Madmike"},"picks":[{"pickNumber":1,"round":1,"teamName":"Joms Jommers","username":"jom315","participantName":"Oklahoma City Thunder","sport":"NBA"},{"pickNumber":2,"round":1,"teamName":"Joyful Tortoises","username":"arny7","participantName":"Connecticut (UConn)","sport":"NCAA Basketball - Women's"},{"pickNumber":3,"round":1,"teamName":"Mr. Worldwide","username":"Madmike","participantName":"Luke Littler","sport":"PDC Darts"},{"pickNumber":4,"round":1,"teamName":"Giant Sheep","username":"getofffmynuts3","participantName":"Colorado Avalanche","sport":"NHL"},{"pickNumber":5,"round":1,"teamName":"Confident Crocodiles","username":"jdog1202.","participantName":"Los Angeles Dodgers","sport":"MLB"},{"pickNumber":6,"round":1,"teamName":"Crazy Vipers","username":"benziti","participantName":"Max Verstappen","sport":"Formula 1"},{"pickNumber":7,"round":1,"teamName":"Ancient Raccoons","username":"tomy","participantName":"Arsenal","sport":"UEFA Champions League"},{"pickNumber":8,"round":1,"teamName":"Electric Grizzlies","username":"mws1395","participantName":"George Russell","sport":"Formula 1"},{"pickNumber":9,"round":1,"teamName":"Mighty Foxes","username":"el_stove","participantName":"Scottie Scheffler","sport":"PGA Golf"},{"pickNumber":10,"round":2,"teamName":"Mighty Foxes","username":"el_stove","participantName":"Las Vegas Aces","sport":"WNBA"},{"pickNumber":11,"round":2,"teamName":"Electric Grizzlies","username":"mws1395","participantName":"Carlos Alcaraz","sport":"Tennis - Men's"},{"pickNumber":12,"round":2,"teamName":"Ancient Raccoons","username":"tomy","participantName":"Lando Norris","sport":"Formula 1"},{"pickNumber":13,"round":2,"teamName":"Crazy Vipers","username":"benziti","participantName":"UCLA","sport":"NCAA Basketball - Women's"},{"pickNumber":14,"round":2,"teamName":"Confident Crocodiles","username":"jdog1202.","participantName":"Jannik Sinner","sport":"Tennis - Men's"},{"pickNumber":15,"round":2,"teamName":"Giant Sheep","username":"getofffmynuts3","participantName":"Michigan","sport":"NCAA Basketball - Men's"},{"pickNumber":16,"round":2,"teamName":"Mr. Worldwide","username":"Madmike","participantName":"Bayern Munich","sport":"UEFA Champions League"},{"pickNumber":17,"round":2,"teamName":"Joyful Tortoises","username":"arny7","participantName":"Denver Nuggets","sport":"NBA"},{"pickNumber":18,"round":2,"teamName":"Joms Jommers","username":"jom315","participantName":"Minnesota Lynx","sport":"WNBA"},{"pickNumber":19,"round":3,"teamName":"Joms Jommers","username":"jom315","participantName":"Tampa Bay Lightning","sport":"NHL"},{"pickNumber":20,"round":3,"teamName":"Joyful Tortoises","username":"arny7","participantName":"Charles Leclerc","sport":"Formula 1"},{"pickNumber":21,"round":3,"teamName":"Mr. Worldwide","username":"Madmike","participantName":"Spain","sport":"FIFA Men's World Cup"},{"pickNumber":22,"round":3,"teamName":"Giant Sheep","username":"getofffmynuts3","participantName":"South Carolina","sport":"NCAA Basketball - Women's"},{"pickNumber":23,"round":3,"teamName":"Confident Crocodiles","username":"jdog1202.","participantName":"Carolina Hurricanes","sport":"NHL"},{"pickNumber":24,"round":3,"teamName":"Crazy Vipers","username":"benziti","participantName":"Vegas Golden Knights","sport":"NHL"},{"pickNumber":25,"round":3,"teamName":"Ancient Raccoons","username":"tomy","participantName":"New York Knicks","sport":"NBA"},{"pickNumber":26,"round":3,"teamName":"Electric Grizzlies","username":"mws1395","participantName":"Team Vitality","sport":"Counter Strike"},{"pickNumber":27,"round":3,"teamName":"Mighty Foxes","username":"el_stove","participantName":"Ohio State","sport":"NCAA Football"},{"pickNumber":28,"round":4,"teamName":"Mighty Foxes","username":"el_stove","participantName":"England","sport":"FIFA Men's World Cup"},{"pickNumber":29,"round":4,"teamName":"Electric Grizzlies","username":"mws1395","participantName":"Indiana Fever","sport":"WNBA"},{"pickNumber":30,"round":4,"teamName":"Ancient Raccoons","username":"tomy","participantName":"Argentina","sport":"FIFA Men's World Cup"},{"pickNumber":31,"round":4,"teamName":"Crazy Vipers","username":"benziti","participantName":"New York Liberty","sport":"WNBA"},{"pickNumber":32,"round":4,"teamName":"Confident Crocodiles","username":"jdog1202.","participantName":"Asia-Pacific and Middle East","sport":"Little League World Series"},{"pickNumber":33,"round":4,"teamName":"Giant Sheep","username":"getofffmynuts3","participantName":"Luke Humphries","sport":"PDC Darts"},{"pickNumber":34,"round":4,"teamName":"Mr. Worldwide","username":"Madmike","participantName":"Arizona","sport":"NCAA Basketball - Men's"},{"pickNumber":35,"round":4,"teamName":"Joyful Tortoises","username":"arny7","participantName":"Andrea Kimi Antonelli","sport":"Formula 1"},{"pickNumber":36,"round":4,"teamName":"Joms Jommers","username":"jom315","participantName":"Barcelona","sport":"UEFA Champions League"},{"pickNumber":37,"round":5,"teamName":"Joms Jommers","username":"jom315","participantName":"Lewis Hamilton","sport":"Formula 1"},{"pickNumber":38,"round":5,"teamName":"Joyful Tortoises","username":"arny7","participantName":"Duke","sport":"NCAA Basketball - Men's"},{"pickNumber":39,"round":5,"teamName":"Mr. Worldwide","username":"Madmike","participantName":"Japan","sport":"Little League World Series"},{"pickNumber":40,"round":5,"teamName":"Giant Sheep","username":"getofffmynuts3","participantName":"Paris Saint-Germain","sport":"UEFA Champions League"},{"pickNumber":41,"round":5,"teamName":"Confident Crocodiles","username":"jdog1202.","participantName":"Oscar Piastri","sport":"Formula 1"},{"pickNumber":42,"round":5,"teamName":"Crazy Vipers","username":"benziti","participantName":"France","sport":"FIFA Men's World Cup"},{"pickNumber":43,"round":5,"teamName":"Ancient Raccoons","username":"tomy","participantName":"Gian van Veen","sport":"PDC Darts"},{"pickNumber":44,"round":5,"teamName":"Electric Grizzlies","username":"mws1395","participantName":"Novak Djokovic","sport":"Tennis - Men's"},{"pickNumber":45,"round":5,"teamName":"Mighty Foxes","username":"el_stove","participantName":"FURIA","sport":"Counter Strike"},{"pickNumber":46,"round":6,"teamName":"Mighty Foxes","username":"el_stove","participantName":"Rory McIlroy","sport":"PGA Golf"},{"pickNumber":47,"round":6,"teamName":"Electric Grizzlies","username":"mws1395","participantName":"Manchester City","sport":"UEFA Champions League"},{"pickNumber":48,"round":6,"teamName":"Ancient Raccoons","username":"tomy","participantName":"New York Yankees","sport":"MLB"},{"pickNumber":49,"round":6,"teamName":"Crazy Vipers","username":"benziti","participantName":"Boston Celtics","sport":"NBA"},{"pickNumber":50,"round":6,"teamName":"Confident Crocodiles","username":"jdog1202.","participantName":"Brazil","sport":"FIFA Men's World Cup"},{"pickNumber":51,"round":6,"teamName":"Giant Sheep","username":"getofffmynuts3","participantName":"Phoenix Mercury","sport":"WNBA"},{"pickNumber":52,"round":6,"teamName":"Mr. Worldwide","username":"Madmike","participantName":"Houston","sport":"NCAA Basketball - Men's"},{"pickNumber":53,"round":6,"teamName":"Joyful Tortoises","username":"arny7","participantName":"Portugal","sport":"FIFA Men's World Cup"},{"pickNumber":54,"round":6,"teamName":"Joms Jommers","username":"jom315","participantName":"Texas","sport":"NCAA Football"},{"pickNumber":55,"round":7,"teamName":"Joms Jommers","username":"jom315","participantName":"LSU","sport":"NCAA Basketball - Women's"},{"pickNumber":56,"round":7,"teamName":"Joyful Tortoises","username":"arny7","participantName":"Edmonton Oilers","sport":"NHL"},{"pickNumber":57,"round":7,"teamName":"Mr. Worldwide","username":"Madmike","participantName":"San Antonio Spurs","sport":"NBA"},{"pickNumber":58,"round":7,"teamName":"Giant Sheep","username":"getofffmynuts3","participantName":"MOUZ","sport":"Counter Strike"},{"pickNumber":59,"round":7,"teamName":"Confident Crocodiles","username":"jdog1202.","participantName":"Notre Dame","sport":"NCAA Football"},{"pickNumber":60,"round":7,"teamName":"Crazy Vipers","username":"benziti","participantName":"Florida","sport":"NCAA Basketball - Men's"},{"pickNumber":61,"round":7,"teamName":"Ancient Raccoons","username":"tomy","participantName":"Tommy Fleetwood","sport":"PGA Golf"},{"pickNumber":62,"round":7,"teamName":"Electric Grizzlies","username":"mws1395","participantName":"Detroit Pistons","sport":"NBA"},{"pickNumber":63,"round":7,"teamName":"Mighty Foxes","username":"el_stove","participantName":"US - West","sport":"Little League World Series"},{"pickNumber":64,"round":8,"teamName":"Mighty Foxes","username":"el_stove","participantName":"Seattle Seahawks","sport":"NFL"},{"pickNumber":65,"round":8,"teamName":"Electric Grizzlies","username":"mws1395","participantName":"Germany","sport":"FIFA Men's World Cup"},{"pickNumber":66,"round":8,"teamName":"Ancient Raccoons","username":"tomy","participantName":"Team Falcons","sport":"Counter Strike"},{"pickNumber":67,"round":8,"teamName":"Crazy Vipers","username":"benziti","participantName":"Ben Shelton","sport":"Tennis - Men's"},{"pickNumber":68,"round":8,"teamName":"Confident Crocodiles","username":"jdog1202.","participantName":"Cleveland Cavaliers","sport":"NBA"},{"pickNumber":69,"round":8,"teamName":"Giant Sheep","username":"getofffmynuts3","participantName":"Carlos Sainz","sport":"Formula 1"},{"pickNumber":70,"round":8,"teamName":"Mr. Worldwide","username":"Madmike","participantName":"Indiana","sport":"NCAA Football"},{"pickNumber":71,"round":8,"teamName":"Joyful Tortoises","username":"arny7","participantName":"Los Angeles Rams","sport":"NFL"},{"pickNumber":72,"round":8,"teamName":"Joms Jommers","username":"jom315","participantName":"Oregon","sport":"NCAA Football"},{"pickNumber":73,"round":9,"teamName":"Joms Jommers","username":"jom315","participantName":"Michael van Gerwen","sport":"PDC Darts"},{"pickNumber":74,"round":9,"teamName":"Joyful Tortoises","username":"arny7","participantName":"Liverpool","sport":"UEFA Champions League"},{"pickNumber":75,"round":9,"teamName":"Mr. Worldwide","username":"Madmike","participantName":"Texas","sport":"NCAA Basketball - Women's"},{"pickNumber":76,"round":9,"teamName":"Giant Sheep","username":"getofffmynuts3","participantName":"Bryson DeChambeau","sport":"PGA Golf"},{"pickNumber":77,"round":9,"teamName":"Confident Crocodiles","username":"jdog1202.","participantName":"Buffalo Bills","sport":"NFL"},{"pickNumber":78,"round":9,"teamName":"Crazy Vipers","username":"benziti","participantName":"Chelsea","sport":"UEFA Champions League"},{"pickNumber":79,"round":9,"teamName":"Ancient Raccoons","username":"tomy","participantName":"Ole Miss","sport":"NCAA Football"},{"pickNumber":80,"round":9,"teamName":"Electric Grizzlies","username":"mws1395","participantName":"Dallas Stars","sport":"NHL"},{"pickNumber":81,"round":9,"teamName":"Mighty Foxes","username":"el_stove","participantName":"Seattle Mariners","sport":"MLB"},{"pickNumber":82,"round":10,"teamName":"Mighty Foxes","username":"el_stove","participantName":"Illinois","sport":"NCAA Basketball - Men's"},{"pickNumber":83,"round":10,"teamName":"Electric Grizzlies","username":"mws1395","participantName":"Georgia","sport":"NCAA Football"},{"pickNumber":84,"round":10,"teamName":"Ancient Raccoons","username":"tomy","participantName":"Team Spirit","sport":"Counter Strike"},{"pickNumber":85,"round":10,"teamName":"Crazy Vipers","username":"benziti","participantName":"Atlanta Braves","sport":"MLB"},{"pickNumber":86,"round":10,"teamName":"Confident Crocodiles","username":"jdog1202.","participantName":"PARIVISION","sport":"Counter Strike"},{"pickNumber":87,"round":10,"teamName":"Giant Sheep","username":"getofffmynuts3","participantName":"Taylor Fritz","sport":"Tennis - Men's"},{"pickNumber":88,"round":10,"teamName":"Mr. Worldwide","username":"Madmike","participantName":"Alexander Zverev","sport":"Tennis - Men's"},{"pickNumber":89,"round":10,"teamName":"Joyful Tortoises","username":"arny7","participantName":"New York Mets","sport":"MLB"},{"pickNumber":90,"round":10,"teamName":"Joms Jommers","username":"jom315","participantName":"Caribbean","sport":"Little League World Series"},{"pickNumber":91,"round":11,"teamName":"Joms Jommers","username":"jom315","participantName":"Boston Red Sox","sport":"MLB"},{"pickNumber":92,"round":11,"teamName":"Joyful Tortoises","username":"arny7","participantName":"Minnesota Wild","sport":"NHL"},{"pickNumber":93,"round":11,"teamName":"Mr. Worldwide","username":"Madmike","participantName":"Natus Vincere","sport":"Counter Strike"},{"pickNumber":94,"round":11,"teamName":"Giant Sheep","username":"getofffmynuts3","participantName":"US - Southeast","sport":"Little League World Series"},{"pickNumber":95,"round":11,"teamName":"Confident Crocodiles","username":"jdog1202.","participantName":"Jon Rahm","sport":"PGA Golf"},{"pickNumber":96,"round":11,"teamName":"Crazy Vipers","username":"benziti","participantName":"Philadelphia Eagles","sport":"NFL"},{"pickNumber":97,"round":11,"teamName":"Ancient Raccoons","username":"tomy","participantName":"Iowa St.","sport":"NCAA Basketball - Men's"},{"pickNumber":98,"round":11,"teamName":"Electric Grizzlies","username":"mws1395","participantName":"Vanderbilt","sport":"NCAA Basketball - Women's"},{"pickNumber":99,"round":11,"teamName":"Mighty Foxes","username":"el_stove","participantName":"Jack Draper","sport":"Tennis - Men's"},{"pickNumber":100,"round":12,"teamName":"Mighty Foxes","username":"el_stove","participantName":"Josh Rock","sport":"PDC Darts"},{"pickNumber":101,"round":12,"teamName":"Electric Grizzlies","username":"mws1395","participantName":"US - Southwest","sport":"Little League World Series"},{"pickNumber":102,"round":12,"teamName":"Ancient Raccoons","username":"tomy","participantName":"Lorenzo Musetti","sport":"Tennis - Men's"},{"pickNumber":103,"round":12,"teamName":"Crazy Vipers","username":"benziti","participantName":"Xander Schauffele","sport":"PGA Golf"},{"pickNumber":104,"round":12,"teamName":"Confident Crocodiles","username":"jdog1202.","participantName":"Atlético Madrid","sport":"UEFA Champions League"},{"pickNumber":105,"round":12,"teamName":"Giant Sheep","username":"getofffmynuts3","participantName":"Kansas City Chiefs","sport":"NFL"},{"pickNumber":106,"round":12,"teamName":"Mr. Worldwide","username":"Madmike","participantName":"Toronto Blue Jays","sport":"MLB"},{"pickNumber":107,"round":12,"teamName":"Joyful Tortoises","username":"arny7","participantName":"Fernando Alonso","sport":"Formula 1"},{"pickNumber":108,"round":12,"teamName":"Joms Jommers","username":"jom315","participantName":"Ludvig Aberg","sport":"PGA Golf"},{"pickNumber":109,"round":13,"teamName":"Joms Jommers","username":"jom315","participantName":"Green Bay Packers","sport":"NFL"},{"pickNumber":110,"round":13,"teamName":"Joyful Tortoises","username":"arny7","participantName":"LSU","sport":"NCAA Football"},{"pickNumber":111,"round":13,"teamName":"Mr. Worldwide","username":"Madmike","participantName":"Philadelphia Phillies","sport":"MLB"},{"pickNumber":112,"round":13,"teamName":"Giant Sheep","username":"getofffmynuts3","participantName":"Netherlands","sport":"FIFA Men's World Cup"},{"pickNumber":113,"round":13,"teamName":"Confident Crocodiles","username":"jdog1202.","participantName":"Seattle Storm","sport":"WNBA"},{"pickNumber":114,"round":13,"teamName":"Crazy Vipers","username":"benziti","participantName":"Alabama","sport":"NCAA Football"},{"pickNumber":115,"round":13,"teamName":"Ancient Raccoons","username":"tomy","participantName":"Montreal Canadiens","sport":"NHL"},{"pickNumber":116,"round":13,"teamName":"Electric Grizzlies","username":"mws1395","participantName":"Detroit Tigers","sport":"MLB"},{"pickNumber":117,"round":13,"teamName":"Mighty Foxes","username":"el_stove","participantName":"Newcastle United","sport":"UEFA Champions League"},{"pickNumber":118,"round":14,"teamName":"Mighty Foxes","username":"el_stove","participantName":"Houston Rockets","sport":"NBA"},{"pickNumber":119,"round":14,"teamName":"Electric Grizzlies","username":"mws1395","participantName":"Stephen Bunting","sport":"PDC Darts"},{"pickNumber":120,"round":14,"teamName":"Ancient Raccoons","username":"tomy","participantName":"Atlanta Dream","sport":"WNBA"},{"pickNumber":121,"round":14,"teamName":"Crazy Vipers","username":"benziti","participantName":"US - Metro","sport":"Little League World Series"},{"pickNumber":122,"round":14,"teamName":"Confident Crocodiles","username":"jdog1202.","participantName":"Connecticut","sport":"NCAA Basketball - Men's"},{"pickNumber":123,"round":14,"teamName":"Giant Sheep","username":"getofffmynuts3","participantName":"Curacao","sport":"Little League World Series"},{"pickNumber":124,"round":14,"teamName":"Mr. Worldwide","username":"Madmike","participantName":"Aurora","sport":"Counter Strike"},{"pickNumber":125,"round":14,"teamName":"Joyful Tortoises","username":"arny7","participantName":"Gerwyn Price","sport":"PDC Darts"},{"pickNumber":126,"round":14,"teamName":"Joms Jommers","username":"jom315","participantName":"G2 Esports","sport":"Counter Strike"},{"pickNumber":127,"round":15,"teamName":"Joms Jommers","username":"jom315","participantName":"Baltimore Ravens","sport":"NFL"},{"pickNumber":128,"round":15,"teamName":"Joyful Tortoises","username":"arny7","participantName":"Mexico","sport":"Little League World Series"},{"pickNumber":129,"round":15,"teamName":"Mr. Worldwide","username":"Madmike","participantName":"Collin Morikawa","sport":"PGA Golf"},{"pickNumber":130,"round":15,"teamName":"Giant Sheep","username":"getofffmynuts3","participantName":"Chicago Cubs","sport":"MLB"},{"pickNumber":131,"round":15,"teamName":"Confident Crocodiles","username":"jdog1202.","participantName":"North Carolina","sport":"NCAA Basketball - Men's"},{"pickNumber":132,"round":15,"teamName":"Crazy Vipers","username":"benziti","participantName":"Gary Anderson","sport":"PDC Darts"},{"pickNumber":133,"round":15,"teamName":"Ancient Raccoons","username":"tomy","participantName":"Tottenham Hotspur","sport":"UEFA Champions League"},{"pickNumber":134,"round":15,"teamName":"Electric Grizzlies","username":"mws1395","participantName":"Houston Texans","sport":"NFL"},{"pickNumber":135,"round":15,"teamName":"Mighty Foxes","username":"el_stove","participantName":"Florida Panthers","sport":"NHL"},{"pickNumber":136,"round":16,"teamName":"Mighty Foxes","username":"el_stove","participantName":"Latin America","sport":"Little League World Series"},{"pickNumber":137,"round":16,"teamName":"Electric Grizzlies","username":"mws1395","participantName":"Danny Noppert","sport":"PDC Darts"},{"pickNumber":138,"round":16,"teamName":"Ancient Raccoons","username":"tomy","participantName":"Alex de Minaur","sport":"Tennis - Men's"},{"pickNumber":139,"round":16,"teamName":"Crazy Vipers","username":"benziti","participantName":"The MongolZ","sport":"Counter Strike"},{"pickNumber":140,"round":16,"teamName":"Confident Crocodiles","username":"jdog1202.","participantName":"New England Patriots","sport":"NFL"},{"pickNumber":141,"round":16,"teamName":"Giant Sheep","username":"getofffmynuts3","participantName":"Minnesota Timberwolves","sport":"NBA"},{"pickNumber":142,"round":16,"teamName":"Mr. Worldwide","username":"Madmike","participantName":"Utah Mammoth","sport":"NHL"},{"pickNumber":143,"round":16,"teamName":"Joyful Tortoises","username":"arny7","participantName":"Los Angeles Chargers","sport":"NFL"},{"pickNumber":144,"round":16,"teamName":"Joms Jommers","username":"jom315","participantName":"Italy","sport":"FIFA Men's World Cup"},{"pickNumber":145,"round":17,"teamName":"Joms Jommers","username":"jom315","participantName":"Kansas","sport":"NCAA Basketball - Men's"},{"pickNumber":146,"round":17,"teamName":"Joyful Tortoises","username":"arny7","participantName":"Golden State Valkyries","sport":"WNBA"}]}

NUM_TEAMS = len(DRAFT_ORDER)
TOTAL_ROUNDS = 20
TOTAL_PICKS = NUM_TEAMS * TOTAL_ROUNDS
FLEX_SPOTS = 4
ADMIN_ID = 143201113800179713

# Bot state
current_pick = 1
last_known_pick = 0
pick_history = []
team_rosters = {t: [] for t in DRAFT_ORDER}
api_available = False
using_sample_data = False
draft_was_paused = False

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
omni = app_commands.Group(name="omni", description="Draft bot commands")
tree.add_command(omni)

# --- HELPERS ---

def mention(brackt_username):
    user_id = DISCORD_IDS.get(brackt_username)
    if user_id:
        return f"<@{user_id}>"
    return f"@{brackt_username}"

def get_team_for_pick(pick_number):
    pick_index = pick_number - 1
    round_number = pick_index // NUM_TEAMS
    position_in_round = pick_index % NUM_TEAMS
    if round_number % 2 == 0:
        team_index = position_in_round
    else:
        team_index = NUM_TEAMS - 1 - position_in_round
    return DRAFT_ORDER[team_index]

def get_next_pick_username(pick_number):
    return get_team_for_pick(pick_number + 1)

def format_pick_number(overall):
    round_num = ((overall - 1) // NUM_TEAMS) + 1
    pick_in_round = ((overall - 1) % NUM_TEAMS) + 1
    return f'{round_num}.{pick_in_round:02d}', round_num

def get_missing_sports(brackt_username):
    roster = team_rosters[brackt_username]
    drafted_sports = [p['sport'] for p in roster]
    return [s for s in REQUIRED_SPORTS if s not in drafted_sports]

def get_flex_remaining(brackt_username):
    roster = team_rosters[brackt_username]
    drafted_sports = [p['sport'] for p in roster]
    required_filled = sum(1 for s in REQUIRED_SPORTS if s in drafted_sports)
    flex_used = len(roster) - required_filled
    return FLEX_SPOTS - flex_used

def is_ephemeral(display: str) -> bool:
    return display == "private"

def mode_label():
    if api_available and not using_sample_data:
        return '🟢 Live API'
    return '🟡 Sample data (API blocked)'

# --- STATE PERSISTENCE ---

def save_state():
    state = {
        'current_pick': current_pick,
        'last_known_pick': last_known_pick,
        'pick_history': pick_history,
        'team_rosters': team_rosters
    }
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)
    print(f'State saved at pick {current_pick}')

def load_state():
    global current_pick, last_known_pick, pick_history, team_rosters
    if not os.path.exists(STATE_FILE):
        print('No saved state found, starting fresh from sample data')
        sync_from_sample()
        return
    try:
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
        current_pick = state.get('current_pick', 1)
        last_known_pick = state.get('last_known_pick', 0)
        pick_history = state.get('pick_history', [])
        team_rosters = state.get('team_rosters', {t: [] for t in DRAFT_ORDER})
        print(f'State loaded — resuming at pick {current_pick}')
    except Exception as e:
        print(f'Error loading state: {e}, loading from sample data')
        sync_from_sample()

def sync_from_sample():
    """Load sample data as starting state when no saved state exists."""
    global current_pick, pick_history, team_rosters
    current_pick = SAMPLE_DATA['currentPickNumber']
    pick_history = []
    team_rosters = {t: [] for t in DRAFT_ORDER}
    for pick in SAMPLE_DATA['picks']:
        username = pick['username']
        entry = {
            'pick': pick['pickNumber'],
            'round': pick['round'],
            'team': username,
            'player': pick['participantName'],
            'sport': pick['sport']
        }
        pick_history.append(entry)
        if username in team_rosters:
            team_rosters[username].append({
                'pick': pick['pickNumber'],
                'player': pick['participantName'],
                'sport': pick['sport']
            })
    save_state()
    print(f'Synced from sample data at pick {current_pick}')

def sync_from_api(data):
    """Only called when real live API data is confirmed. Overwrites state."""
    global current_pick, pick_history, team_rosters
    current_pick = data['currentPickNumber']
    pick_history = []
    team_rosters = {t: [] for t in DRAFT_ORDER}
    for pick in data['picks']:
        username = pick['username']
        entry = {
            'pick': pick['pickNumber'],
            'round': pick['round'],
            'team': username,
            'player': pick['participantName'],
            'sport': pick['sport']
        }
        pick_history.append(entry)
        if username in team_rosters:
            team_rosters[username].append({
                'pick': pick['pickNumber'],
                'player': pick['participantName'],
                'sport': pick['sport']
            })
    save_state()
    print(f'State synced from live API at pick {current_pick}')

# --- API ---

def fetch_draft_state():
    global api_available, using_sample_data
    headers = {
        'User-Agent': 'BracktDraftNotify/1.0'
    }
    if API_KEY:
        headers['Authorization'] = f'Bearer {API_KEY}'
    try:
        response = requests.get(DRAFT_API_URL, headers=headers, timeout=10)
        if response.status_code == 200:
            api_available = True
            using_sample_data = False
            return response.json()
        else:
            print(f'API returned {response.status_code}')
            api_available = False
            using_sample_data = True
            return None
    except Exception as e:
        print(f'API fetch error: {e}')
        api_available = False
        using_sample_data = True
        return None

# --- SLASH COMMANDS ---

@omni.command(name="onclock", description="Show who is currently on the clock")
@app_commands.describe(display="Show publicly or privately (default: public)")
@app_commands.choices(display=[
    app_commands.Choice(name="public", value="public"),
    app_commands.Choice(name="private", value="private")
])
async def onclock(interaction: discord.Interaction, display: str = "public"):
    pick_num = current_pick
    formatted, _ = format_pick_number(pick_num)
    username = get_team_for_pick(pick_num)
    after_username = get_next_pick_username(pick_num)
    msg = (
        f'🕐 **Pick {formatted} ({pick_num}):** {mention(username)} is on the clock!\n'
        f'Up next: {mention(after_username)}'
    )
    await interaction.response.send_message(msg, ephemeral=is_ephemeral(display))

@omni.command(name="last5", description="Show the last 5 picks")
@app_commands.describe(display="Show publicly or privately (default: public)")
@app_commands.choices(display=[
    app_commands.Choice(name="public", value="public"),
    app_commands.Choice(name="private", value="private")
])
async def last5(interaction: discord.Interaction, display: str = "public"):
    if len(pick_history) == 0:
        await interaction.response.send_message('📋 No picks have been made yet.', ephemeral=is_ephemeral(display))
        return
    recent = pick_history[-5:]
    text = '📋 **Last 5 Picks**\n\n'
    for p in recent:
        formatted, _ = format_pick_number(p["pick"])
        handle = DISCORD_HANDLES[p["team"]]
        text += f'Pick {formatted} ({p["pick"]}): **{handle}** — **{p["player"]}** ({p["sport"]})\n'
    await interaction.response.send_message(text, ephemeral=is_ephemeral(display))

@omni.command(name="team", description="Show all picks made by a specific team")
@app_commands.describe(
    username="Select a team",
    display="Show publicly or privately (default: public)"
)
@app_commands.choices(
    display=[
        app_commands.Choice(name="public", value="public"),
        app_commands.Choice(name="private", value="private")
    ],
    username=[
        app_commands.Choice(name="Jom (jom315)", value="jom315"),
        app_commands.Choice(name="Arny (arny7)", value="arny7"),
        app_commands.Choice(name="Mike (Madmike)", value="Madmike"),
        app_commands.Choice(name="Bill (getofffmynuts3)", value="getofffmynuts3"),
        app_commands.Choice(name="Jared (jdog1202.)", value="jdog1202."),
        app_commands.Choice(name="Benz (benziti)", value="benziti"),
        app_commands.Choice(name="Tom (__voids__)", value="tomy"),
        app_commands.Choice(name="Myles (mws1395)", value="mws1395"),
        app_commands.Choice(name="Stove (el_stove)", value="el_stove"),
    ]
)
async def team_command(interaction: discord.Interaction, username: str, display: str = "public"):
    roster = team_rosters[username]
    if len(roster) == 0:
        await interaction.response.send_message(
            f'📋 No picks recorded for **{DISCORD_HANDLES[username]}** yet.',
            ephemeral=is_ephemeral(display)
        )
        return
    text = f'📋 **{DISCORD_HANDLES[username]}\'s Picks ({len(roster)}/{TOTAL_ROUNDS})**\n\n'
    for p in roster:
        _, round_num = format_pick_number(p["pick"])
        text += f'Round {round_num}: **{p["player"]}** ({p["sport"]})\n'
    await interaction.response.send_message(text, ephemeral=is_ephemeral(display))

@omni.command(name="mysports", description="Show missing sports and flex spots for a team")
@app_commands.describe(
    username="Select a team (leave blank to look up your own)",
    display="Show publicly or privately (default: public)"
)
@app_commands.choices(
    display=[
        app_commands.Choice(name="public", value="public"),
        app_commands.Choice(name="private", value="private")
    ],
    username=[
        app_commands.Choice(name="Jom (jom315)", value="jom315"),
        app_commands.Choice(name="Arny (arny7)", value="arny7"),
        app_commands.Choice(name="Mike (Madmike)", value="Madmike"),
        app_commands.Choice(name="Bill (getofffmynuts3)", value="getofffmynuts3"),
        app_commands.Choice(name="Jared (jdog1202.)", value="jdog1202."),
        app_commands.Choice(name="Benz (benziti)", value="benziti"),
        app_commands.Choice(name="Tom (__voids__)", value="tomy"),
        app_commands.Choice(name="Myles (mws1395)", value="mws1395"),
        app_commands.Choice(name="Stove (el_stove)", value="el_stove"),
    ]
)
async def mysports(interaction: discord.Interaction, username: str = None, display: str = "public"):
    if username is None:
        sender_id = str(interaction.user.id)
        brackt_name = None
        for brackt_user, uid in DISCORD_IDS.items():
            if uid == sender_id:
                brackt_name = brackt_user
                break
        if brackt_name is None:
            await interaction.response.send_message(
                '❌ Could not find your team. Try selecting your username from the list.',
                ephemeral=True
            )
            return
    else:
        brackt_name = username
    missing = get_missing_sports(brackt_name)
    flex_left = get_flex_remaining(brackt_name)
    total_picks = len(team_rosters[brackt_name])
    missing_text = '✅ All sports covered!' if len(missing) == 0 else '\n'.join(f'  • {s}' for s in missing)
    msg = (
        f'📊 **{DISCORD_HANDLES[brackt_name]}\'s Roster ({total_picks}/{TOTAL_ROUNDS} picks)**\n\n'
        f'**Missing Sports ({len(missing)}):**\n{missing_text}\n\n'
        f'**Flex Spots Remaining:** {flex_left} of {FLEX_SPOTS}'
    )
    await interaction.response.send_message(msg, ephemeral=is_ephemeral(display))

@omni.command(name="status", description="Show current draft round, pick number, and who is on the clock")
@app_commands.describe(display="Show publicly or privately (default: public)")
@app_commands.choices(display=[
    app_commands.Choice(name="public", value="public"),
    app_commands.Choice(name="private", value="private")
])
async def status(interaction: discord.Interaction, display: str = "public"):
    pick_num = current_pick
    _, round_num = format_pick_number(pick_num)
    username = get_team_for_pick(pick_num)
    msg = (
        f'📋 **Draft Status** ({mode_label()})\n'
        f'Round: {round_num} of {TOTAL_ROUNDS}\n'
        f'Current Pick: {pick_num} of {TOTAL_PICKS}\n'
        f'On the Clock: {mention(username)}'
    )
    await interaction.response.send_message(msg, ephemeral=is_ephemeral(display))

@omni.command(name="help", description="Show all available Omni Draft Bot commands")
async def help_command(interaction: discord.Interaction):
    msg = (
        f'📖 **Omni Draft Bot Commands** ({mode_label()})\n\n'
        '`/omni onclock` — Show who is currently on the clock\n'
        '`/omni last5` — Show the last 5 picks\n'
        '`/omni team [username]` — Show all picks by a specific team\n'
        '`/omni mysports` — Show your missing sports and flex spots\n'
        '`/omni mysports [username]` — Check another team\'s sports\n'
        '`/omni status` — Show current round, pick, and who is on the clock\n'
        '`/omni help` — Show this message\n\n'
        'All commands support a `display` option: **public** (default) or **private**'
    )
    await interaction.response.send_message(msg, ephemeral=True)

# --- ADMIN COMMANDS ---

@omni.command(name="adminpick", description="Admin only: manually record a pick")
@app_commands.describe(
    player="Team or player name being picked",
    sport="Sport of the pick",
    username="Select the team making the pick (leave blank for current pick)"
)
@app_commands.choices(
    sport=[
        app_commands.Choice(name="NBA", value="NBA"),
        app_commands.Choice(name="NFL", value="NFL"),
        app_commands.Choice(name="MLB", value="MLB"),
        app_commands.Choice(name="NHL", value="NHL"),
        app_commands.Choice(name="NCAA Basketball - Men's", value="NCAA Basketball - Men's"),
        app_commands.Choice(name="NCAA Basketball - Women's", value="NCAA Basketball - Women's"),
        app_commands.Choice(name="NCAA Football", value="NCAA Football"),
        app_commands.Choice(name="PGA Golf", value="PGA Golf"),
        app_commands.Choice(name="Formula 1", value="Formula 1"),
        app_commands.Choice(name="Tennis - Men's", value="Tennis - Men's"),
        app_commands.Choice(name="UEFA Champions League", value="UEFA Champions League"),
        app_commands.Choice(name="FIFA Men's World Cup", value="FIFA Men's World Cup"),
        app_commands.Choice(name="WNBA", value="WNBA"),
        app_commands.Choice(name="PDC Darts", value="PDC Darts"),
        app_commands.Choice(name="Counter Strike", value="Counter Strike"),
        app_commands.Choice(name="Little League World Series", value="Little League World Series"),
    ],
    username=[
        app_commands.Choice(name="Jom (jom315)", value="jom315"),
        app_commands.Choice(name="Arny (arny7)", value="arny7"),
        app_commands.Choice(name="Mike (Madmike)", value="Madmike"),
        app_commands.Choice(name="Bill (getofffmynuts3)", value="getofffmynuts3"),
        app_commands.Choice(name="Jared (jdog1202.)", value="jdog1202."),
        app_commands.Choice(name="Benz (benziti)", value="benziti"),
        app_commands.Choice(name="Tom (__voids__)", value="tomy"),
        app_commands.Choice(name="Myles (mws1395)", value="mws1395"),
        app_commands.Choice(name="Stove (el_stove)", value="el_stove"),
    ]
)
async def adminpick(
    interaction: discord.Interaction,
    player: str,
    sport: str,
    username: str = None
):
    if interaction.user.id != ADMIN_ID:
        await interaction.response.send_message(
            '❌ You do not have permission to use this command.',
            ephemeral=True
        )
        return

    global current_pick, pick_history, team_rosters, last_known_pick

    brackt_name = username if username else get_team_for_pick(current_pick)

    pick_entry = {
        'pick': current_pick,
        'round': ((current_pick - 1) // NUM_TEAMS) + 1,
        'team': brackt_name,
        'player': player,
        'sport': sport
    }
    pick_history.append(pick_entry)
    team_rosters[brackt_name].append({
        'pick': current_pick,
        'player': player,
        'sport': sport
    })

    formatted, _ = format_pick_number(current_pick)
    last_known_pick = current_pick
    current_pick += 1
    save_state()

    next_brackt = get_team_for_pick(current_pick)
    channel = client.get_channel(CHANNEL_ID)
    await channel.send(
        f'✅ **Pick {formatted} ({current_pick - 1}):** {mention(brackt_name)} '
        f'selected **{player}** ({sport})!\n'
        f'🕐 Now on the clock: {mention(next_brackt)}'
    )
    await interaction.response.send_message(
        f'✅ Pick recorded: **{player}** ({sport}) for {DISCORD_HANDLES[brackt_name]}',
        ephemeral=True
    )

# --- POLLING LOOP ---

async def poll_draft():
    global last_known_pick, api_available, draft_was_paused
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)
    print(f'Starting API polling every {POLL_INTERVAL} seconds...')

    while not client.is_closed():
        data = fetch_draft_state()

        if data is None:
            await asyncio.sleep(POLL_INTERVAL)
            continue

        new_pick_number = data['currentPickNumber']

        # Detect new picks
        if new_pick_number > last_known_pick and last_known_pick > 0:
            new_picks = [p for p in data['picks'] if p['pickNumber'] > last_known_pick]
            for pick in sorted(new_picks, key=lambda x: x['pickNumber']):
                username = pick['username']
                player = pick['participantName']
                sport = pick['sport']
                pick_num = pick['pickNumber']
                formatted, _ = format_pick_number(pick_num)
                await channel.send(
                    f'✅ **Pick {formatted} ({pick_num}):** {mention(username)} '
                    f'selected **{player}** ({sport})!'
                )

            if data['isDraftComplete']:
                await channel.send(
                    f'🏆 **The draft is complete! All {TOTAL_PICKS} picks have been made. '
                    f'Good luck everyone!**'
                )
            else:
                on_clock = data['onTheClock']
                next_username = on_clock['username']
                next_pick_num = new_pick_number
                formatted, _ = format_pick_number(next_pick_num)
                if next_pick_num < TOTAL_PICKS:
                    after_username = get_next_pick_username(next_pick_num)
                    await channel.send(
                        f'🕐 **Pick {formatted} ({next_pick_num}):** '
                        f'{mention(next_username)} is on the clock!\n'
                        f'Up next: {mention(after_username)}'
                    )

        # Pause detection — only fire once when state changes
        is_paused = data.get('isPaused', False)
        if is_paused and not draft_was_paused:
            await channel.send('⏸️ **The draft has been paused.**')
        elif not is_paused and draft_was_paused:
            await channel.send('▶️ **The draft has resumed!**')
        draft_was_paused = is_paused

        # Sync from live API and save
        sync_from_api(data)
        last_known_pick = new_pick_number

        await asyncio.sleep(POLL_INTERVAL)

# --- STARTUP ---

@client.event
async def on_ready():
    global last_known_pick
    print(f'Bot is online as {client.user}')
    load_state()
    last_known_pick = current_pick - 1

    # Try live API on startup
    data = fetch_draft_state()
    if data:
        print('Live API available on startup — syncing...')
        sync_from_api(data)
        last_known_pick = data['currentPickNumber']
    else:
        print(f'API not available — loaded from saved state at pick {current_pick}')

    await tree.sync()
    print('Slash commands synced!')
    asyncio.ensure_future(poll_draft())

client.run(TOKEN)