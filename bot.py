import discord
from dotenv import load_dotenv
import os

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

CHANNEL_ID = 1477527697268805836

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

# All 16 sports — these are the required sport slots
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

# Shorthand aliases so !pick commands are easier to type
SPORT_ALIASES = {
    "darts":        "PDC Darts",
    "pdc":          "PDC Darts",
    "ncaab":        "NCAA Basketball - Men's",
    "ncaabm":       "NCAA Basketball - Men's",
    "ncaabw":       "NCAA Basketball - Women's",
    "nhl":          "NHL",
    "ucl":          "UEFA Champions League",
    "champions":    "UEFA Champions League",
    "llws":         "Little League World Series",
    "littleleague": "Little League World Series",
    "mlb":          "MLB",
    "wnba":         "WNBA",
    "golf":         "PGA Golf",
    "pga":          "PGA Golf",
    "f1":           "Formula 1",
    "formula1":     "Formula 1",
    "ncaaf":        "NCAA Football",
    "nfl":          "NFL",
    "tennis":       "Tennis - Men's",
    "cs":           "Counter Strike",
    "csgo":         "Counter Strike",
    "fifa":         "FIFA Men's World Cup",
    "worldcup":     "FIFA Men's World Cup",
    "nba":          "NBA"
}

NUM_TEAMS = len(DRAFT_ORDER)
TOTAL_ROUNDS = 20
TOTAL_PICKS = NUM_TEAMS * TOTAL_ROUNDS
FLEX_SPOTS = 4

current_pick = 1
pick_history = []

# Tracks picks per team: { brackt_username: [ {pick, player, sport}, ... ] }
team_rosters = {team: [] for team in DRAFT_ORDER}

def get_team_for_pick(pick_number):
    pick_index = pick_number - 1
    round_number = pick_index // NUM_TEAMS
    position_in_round = pick_index % NUM_TEAMS
    if round_number % 2 == 0:
        team_index = position_in_round
    else:
        team_index = NUM_TEAMS - 1 - position_in_round
    return DRAFT_ORDER[team_index]

def get_next_team(pick_number):
    return get_team_for_pick(pick_number + 1)

def mention(brackt_username):
    user_id = DISCORD_IDS[brackt_username]
    return f"<@{user_id}>"

def current_round():
    return ((current_pick - 1) // NUM_TEAMS) + 1

def resolve_sport(sport_input):
    """Convert user sport input to a canonical sport name."""
    normalized = sport_input.strip().lower().replace(" ", "")
    # Check aliases first
    if normalized in SPORT_ALIASES:
        return SPORT_ALIASES[normalized]
    # Check if it matches a required sport directly (case insensitive)
    for sport in REQUIRED_SPORTS:
        if sport.lower() == sport_input.strip().lower():
            return sport
    # Return original input if no match found
    return sport_input.strip()

def get_missing_sports(brackt_username):
    """Return list of sports this team hasn't drafted yet."""
    roster = team_rosters[brackt_username]
    drafted_sports = [p['sport'] for p in roster]
    missing = [s for s in REQUIRED_SPORTS if s not in drafted_sports]
    return missing

def get_flex_remaining(brackt_username):
    """Return how many flex spots this team has left."""
    roster = team_rosters[brackt_username]
    drafted_sports = [p['sport'] for p in roster]
    required_filled = sum(1 for s in REQUIRED_SPORTS if s in drafted_sports)
    total_picks = len(roster)
    flex_used = total_picks - required_filled
    return FLEX_SPOTS - flex_used

@client.event
async def on_ready():
    print(f'Bot is online as {client.user}')

@client.event
async def on_message(message):
    global current_pick, pick_history, team_rosters

    if message.author == client.user:
        return

    if message.channel.id != CHANNEL_ID:
        return

    # !onclock
    if message.content.strip() == '!onclock':
        team = get_team_for_pick(current_pick)
        next_team = get_next_team(current_pick)
        await message.channel.send(
            f'🕐 **Pick {current_pick}** — {mention(team)} is on the clock!\n'
            f'Up next: {mention(next_team)}'
        )

    # !pick [name] [sport]
    elif message.content.strip().startswith('!pick '):
        parts = message.content.strip()[6:].rsplit(' ', 1)
        if len(parts) != 2:
            await message.channel.send(
                '❌ Invalid format. Use: `!pick [name] [sport]`\n'
                'Example: `!pick Boston Celtics NBA` or `!pick Scottie Scheffler Golf`'
            )
            return

        player_name, sport_input = parts
        sport = resolve_sport(sport_input)
        team = get_team_for_pick(current_pick)

        pick_entry = {
            'pick': current_pick,
            'team': team,
            'player': player_name,
            'sport': sport
        }
        pick_history.append(pick_entry)
        team_rosters[team].append({
            'pick': current_pick,
            'player': player_name,
            'sport': sport
        })
        current_pick += 1

        if current_pick > TOTAL_PICKS:
            await message.channel.send(
                f'✅ **Pick {current_pick - 1}:** {mention(team)} selected **{player_name}** '
                f'({sport})!\n\n'
                f'🏆 **The draft is complete! All {TOTAL_PICKS} picks have been made. '
                f'Good luck everyone!**'
            )
        else:
            next_team = get_next_team(current_pick - 1)
            await message.channel.send(
                f'✅ **Pick {current_pick - 1}:** {mention(team)} selected **{player_name}** '
                f'({sport})!\n'
                f'🕐 Now on the clock: {mention(next_team)}'
            )

    # !last5
    elif message.content.strip() == '!last5':
        if len(pick_history) == 0:
            await message.channel.send('📋 No picks have been made yet.')
        else:
            recent = pick_history[-5:]
            text = '📋 **Last 5 Picks**\n\n'
            for p in recent:
                overall = p["pick"]
                round_num = ((overall - 1) // NUM_TEAMS) + 1
                pick_in_round = ((overall - 1) % NUM_TEAMS) + 1
                formatted_pick = f'{round_num}.{pick_in_round:02d}'
                handle = DISCORD_HANDLES[p["team"]]
                text += f'Pick {formatted_pick} ({overall}): @{handle} — **{p["player"]}** ({p["sport"]})\n'
            
            # Send without mentions first, then edit to include them
            sent = await message.channel.send(text)
            
            edited_text = '📋 **Last 5 Picks**\n\n'
            for p in recent:
                overall = p["pick"]
                round_num = ((overall - 1) // NUM_TEAMS) + 1
                pick_in_round = ((overall - 1) % NUM_TEAMS) + 1
                formatted_pick = f'{round_num}.{pick_in_round:02d}'
                edited_text += f'Pick {formatted_pick} ({overall}): {mention(p["team"])} — **{p["player"]}** ({p["sport"]})\n'
            
            await sent.edit(content=edited_text)

    # !history
    elif message.content.strip() == '!history':
        if len(pick_history) == 0:
            await message.channel.send('📋 No picks have been made yet.')
        else:
            history_text = '📋 **Pick History**\n\n'
            for p in pick_history:
                history_text += f'Pick {p["pick"]}: {mention(p["team"])} — **{p["player"]}** ({p["sport"]})\n'
            await message.channel.send(history_text)

    # !mysports [username] - show missing sports and flex remaining
    elif message.content.strip().startswith('!mysports'):
        parts = message.content.strip().split(' ', 1)
        if len(parts) == 2:
            # Look up by brackt username
            brackt_name = parts[1].strip()
            if brackt_name not in DRAFT_ORDER:
                await message.channel.send(f'❌ Unknown team: `{brackt_name}`. Use their brackt.com username.')
                return
        else:
            # Try to match by Discord ID of whoever sent the message
            sender_id = str(message.author.id)
            brackt_name = None
            for team, uid in DISCORD_IDS.items():
                if uid == sender_id:
                    brackt_name = team
                    break
            if brackt_name is None:
                await message.channel.send(
                    '❌ Could not find your team. Try `!mysports [brackt username]`'
                )
                return

        missing = get_missing_sports(brackt_name)
        flex_left = get_flex_remaining(brackt_name)
        roster = team_rosters[brackt_name]
        total_picks = len(roster)

        if len(missing) == 0:
            missing_text = '✅ All sports covered!'
        else:
            missing_text = '\n'.join(f'  • {s}' for s in missing)

        await message.channel.send(
            f'📊 **{DISCORD_HANDLES[brackt_name]}\'s Roster ({total_picks}/{TOTAL_ROUNDS} picks)**\n\n'
            f'**Missing Sports ({len(missing)}):**\n{missing_text}\n\n'
            f'**Flex Spots Remaining:** {flex_left} of {FLEX_SPOTS}'
        )

    # !status
    elif message.content.strip() == '!status':
        team = get_team_for_pick(current_pick)
        await message.channel.send(
            f'📋 **Draft Status**\n'
            f'Round: {current_round()} of {TOTAL_ROUNDS}\n'
            f'Current Pick: {current_pick} of {TOTAL_PICKS}\n'
            f'On the Clock: {mention(team)}'
        )

    # !undo
    elif message.content.strip() == '!undo':
        if len(pick_history) == 0:
            await message.channel.send('❌ No picks to undo.')
        else:
            last = pick_history.pop()
            team_rosters[last['team']] = [
                p for p in team_rosters[last['team']]
                if p['pick'] != last['pick']
            ]
            current_pick -= 1
            team = get_team_for_pick(current_pick)
            await message.channel.send(
                f'↩️ **Pick {last["pick"]} undone** — {last["player"]} ({last["sport"]}) has been removed.\n'
                f'🕐 Back on the clock: {mention(team)}'
            )

    # !reset
    elif message.content.strip() == '!reset':
        current_pick = 1
        pick_history = []
        team_rosters = {team: [] for team in DRAFT_ORDER}
        await message.channel.send('🔄 Draft has been reset to pick 1.')

    # !help
    elif message.content.strip() == '!help':
        await message.channel.send(
            '📖 **Draft Bot Commands**\n\n'
            '`!onclock` — Show who is currently on the clock\n'
            '`!pick [name] [sport]` — Record a pick and advance to the next team\n'
            '`!last5` — Show the last 5 picks\n'
            '`!history` — Show all picks made so far\n'
            '`!mysports` — Show your missing sports and flex spots remaining\n'
            '`!mysports [brackt username]` — Check another team\'s sports\n'
            '`!status` — Show current round, pick number, and who is on the clock\n'
            '`!undo` — Undo the last pick\n'
            '`!reset` — Reset the draft back to pick 1\n'
            '`!help` — Show this command list\n\n'
            '**Sport Shortcuts:** nba, nfl, mlb, nhl, nba, f1, golf, tennis, fifa, '
            'ncaab, ncaabw, ncaaf, ucl, wnba, darts, cs, llws'
        )

client.run(TOKEN)