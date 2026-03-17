"""
bot.py — Entry point for Brackt Notify.
Loads cogs, starts the polling loop, and runs the bot.
"""

import asyncio
import os

# Load .env before any other imports so all modules see the env vars
from dotenv import load_dotenv
_here = os.path.dirname(os.path.abspath(__file__))
if os.path.exists('/home/madmike/www/.env'):
    load_dotenv(dotenv_path='/home/madmike/www/.env')
else:
    load_dotenv(dotenv_path=os.path.join(_here, '.env'))

TOKEN = os.getenv('DISCORD_TOKEN')

import discord
from discord.ext import commands
from config import POLL_INTERVAL, LEAGUES_DIR
from league import (
    leagues_cache, load_league, update_cache,
    fetch_draft_state, sync_from_api,
    get_team_for_pick, get_total_picks, format_pick_number, mention,
)

os.makedirs(LEAGUES_DIR, exist_ok=True)

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@bot.event
async def on_ready():
    print(f'Bot is online as {bot.user}')

    for filename in os.listdir(LEAGUES_DIR):
        if not filename.endswith('.json'):
            continue
        try:
            channel_id = int(filename.replace('.json', ''))
            league     = load_league(channel_id)
            if not league:
                continue

            if not league.get('api_url'):
                print(f'League {channel_id} skipped — no API URL configured')
                leagues_cache[channel_id] = league
                continue

            saved_last_known = league.get('last_known_pick', 0)
            data = fetch_draft_state(league)
            if data:
                sync_from_api(league, data)
                last_completed = data['currentPickNumber'] - 1
                if 0 < saved_last_known <= last_completed:
                    league['last_known_pick'] = saved_last_known
                else:
                    league['last_known_pick'] = last_completed
                print(f'League {channel_id} synced at pick {league["current_pick"]}, '
                      f'resuming from pick {league["last_known_pick"]}')
            else:
                print(f'League {channel_id} API unavailable — using saved state')

            update_cache(channel_id, league)

        except Exception as e:
            print(f'Error initializing league {filename}: {e}')

    await bot.tree.sync()
    print('Slash commands synced!')
    asyncio.ensure_future(poll_all_leagues())


# ---------------------------------------------------------------------------
# Polling loop
# ---------------------------------------------------------------------------

async def poll_all_leagues():
    await bot.wait_until_ready()
    print(f'Polling all leagues every {POLL_INTERVAL} seconds...')

    while not bot.is_closed():
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

                channel = bot.get_channel(channel_id)
                if not channel:
                    continue

                data = fetch_draft_state(league)
                if data is None:
                    if league.get('api_available'):
                        league['api_available']    = False
                        league['using_sample_data'] = True
                        update_cache(channel_id, league)
                    continue

                last_completed = data['currentPickNumber'] - 1
                last_known     = league.get('last_known_pick', 0)

                # First poll after startup — sync silently
                if last_known == 0:
                    sync_from_api(league, data)
                    league['last_known_pick'] = last_completed
                    update_cache(channel_id, league)
                    continue

                # Rollback detection
                if last_completed < last_known:
                    picks_rolled_back = last_known - last_completed
                    current_username  = get_team_for_pick(league, last_completed + 1)
                    on_deck_username  = get_team_for_pick(league, last_completed + 2)
                    total             = get_total_picks(league)
                    formatted, _      = format_pick_number(league, last_completed + 1)
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

                # New picks
                elif last_completed > last_known:
                    new_picks = [p for p in data['picks'] if p['pickNumber'] > last_known]
                    if not new_picks:
                        continue

                    sorted_picks  = sorted(new_picks, key=lambda x: x['pickNumber'])
                    last_pick_num = sorted_picks[-1]['pickNumber']

                    for pick in sorted_picks:
                        username   = pick['username']
                        player     = pick['participantName']
                        sport      = pick['sport']
                        pick_num   = pick['pickNumber']
                        formatted, _ = format_pick_number(league, pick_num)

                        next_username     = get_team_for_pick(league, pick_num + 1)
                        on_deck_username  = get_team_for_pick(league, pick_num + 2)
                        total             = get_total_picks(league)
                        on_deck = (
                            f'\n📋 **On Deck:** {mention(league, on_deck_username)}'
                            if on_deck_username and pick_num + 2 <= total else ''
                        )

                        is_last = data['isDraftComplete'] and pick_num == last_pick_num
                        if is_last:
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

                    sync_from_api(league, data)

                # Pause state
                is_paused  = data.get('isPaused', False)
                was_paused = league.get('draft_was_paused', False)
                if is_paused and not was_paused:
                    await channel.send('⏸️ **The draft has been paused.**')
                elif not is_paused and was_paused:
                    await channel.send('▶️ **The draft has resumed!**')

                league['last_known_pick']  = last_completed
                league['draft_was_paused'] = is_paused
                update_cache(channel_id, league)

            except discord.Forbidden:
                print(f'League {channel_id}: Missing channel permissions — skipping')
                continue
            except Exception as e:
                print(f'Error polling league {channel_id}: {e}')
                continue

        await asyncio.sleep(POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Load cogs and run
# ---------------------------------------------------------------------------

async def main():
    async with bot:
        await bot.load_extension('cogs.admin')
        await bot.load_extension('cogs.public')
        await bot.start(TOKEN)


if __name__ == '__main__':
    asyncio.run(main())
