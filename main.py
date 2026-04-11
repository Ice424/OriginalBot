import sqlite3
import numpy as np
import disnake
import json
import time
import difflib
import colorsys

from urllib.request import urlopen
from PIL import Image
from disnake.ext import commands
from typing import TypeAlias
from requests import post

ActivityTypes: TypeAlias = disnake.Activity | disnake.Game | disnake.CustomActivity | disnake.Streaming | disnake.Spotify

intents = disnake.Intents.all()

ORIGINAL_SERVER_ID = 1054033732639653888

command_sync_flags = commands.CommandSyncFlags.default()
command_sync_flags.sync_commands_debug = True

bot = commands.InteractionBot(
    intents=intents,
    test_guilds=[ORIGINAL_SERVER_ID],
    command_sync_flags=command_sync_flags,
)

def get_theme_color(image_url, k=5):
    img = Image.open(urlopen(image_url)).convert("RGB")

    pixels = np.array(img).reshape(-1, 3)

    # choose random initial centers
    centers = pixels[np.random.choice(len(pixels), k, replace=False)]

    for _ in range(10):  # iterations
        distances = np.linalg.norm(pixels[:, None] - centers, axis=2)
        labels = np.argmin(distances, axis=1)

        new_centers = np.array([
            pixels[labels == i].mean(axis=0) if np.any(labels == i) else centers[i]
            for i in range(k)
        ])

        centers = new_centers

        

    best = None
    best_score = 0

    for c in centers:
        r, g, b = c
        h, s, v = colorsys.rgb_to_hsv(r/255, g/255, b/255)
        score = s * v  # prefer bright + saturated

        if score > best_score:
            best_score = score
            best = c

    dominant = best

    r, g, b = dominant.astype(int)
    r,g,b = int(r), int(g), int(b)
    return (r, g, b)




conn = sqlite3.connect("games.db")
conn.execute("PRAGMA foreign_keys = ON")
cur = conn.cursor()

async def link_player_game(userid: int, game_name: str):
    cur.execute("""
    INSERT OR IGNORE INTO player_games(player, game)
    SELECT players.id, games.id
    FROM players, games
    WHERE players.userid = ? AND games.name = ?
    """, (userid, game_name))
    conn.commit()
    cur.execute("SELECT * FROM games WHERE name = ?", (game_name,))
    row = cur.fetchone()
    if row[2]:
        guild = bot.get_guild(ORIGINAL_SERVER_ID)
        if not guild:
            return
        await guild.get_member(userid).add_roles(guild.get_role(row[2]))
    

def add_player(player_name: str, player_id: int):
    cur.execute(
        "INSERT OR IGNORE INTO players(name, userid) VALUES (?, ?)",
        (player_name, player_id)
    )
    conn.commit()
    
def add_game(game_name: str):
    cur.execute("INSERT OR IGNORE INTO games(name) VALUES (?)", (game_name,))
    conn.commit()
    return cur.rowcount == 1

async def add_link_game(activity:ActivityTypes | None, member:disnake.Member):
    if activity and activity.type is disnake.ActivityType.playing and activity.name:
            if add_game(activity.name):
                add_colour(activity.name)
            await link_player_game(member.id, activity.name)



def add_colour(game_name: str):
    r,g,b = get_theme_color(get_igdb_cover(game_name))
    color = disnake.Color.from_rgb(r,g,b).value
    cur.execute(
        "UPDATE games SET color=? WHERE name=?",
        (color, game_name)
    )
    conn.commit()

def sql_setup():
    cur.execute("""
    CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        userid INTEGER UNIQUE NOT NULL
        
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS games (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        roleid INTEGER UNIQUE,
        color INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS player_games (
        player INTEGER,
        game INTEGER,
        PRIMARY KEY (player, game),
        FOREIGN KEY (player) REFERENCES players(id),
        FOREIGN KEY (game) REFERENCES games(id)
    )
    """)

    conn.commit()

def game_exists(game_name: str) -> bool:
    cur.execute("""
    SELECT EXISTS(
        SELECT 1 FROM games WHERE name = ?
    )
    """, (game_name,))
    
    return bool(cur.fetchone()[0])

    

             
@bot.event
async def on_ready():
    guild = bot.get_guild(ORIGINAL_SERVER_ID)
    if not guild:
        print("Failed to get guild")
        return

    for member in guild.members:
        if member.bot:
            continue
        add_player(member.name, member.id)
        

        activities = member.activities
        for activity in activities:

            
            await add_link_game(activity, member)
            

@bot.event
async def on_presence_update(before: disnake.Member, after: disnake.Member):
    if after.bot:
        return

    await add_link_game(after.activity, after)

    for activity in after.activities:
        await add_link_game(activity, after)
        
@bot.slash_command(description="Creates and assigns a role based on recorded games")
async def assign_game(inter: disnake.ApplicationCommandInteraction, game:str):
    if game_exists(game): 
        await link_player_game(inter.user.id, game)
        
        
    

@bot.slash_command(description="Creates and assigns a role based on recorded games")
async def add_role(inter: disnake.ApplicationCommandInteraction, game:str, hex_colour:str|None = None):
    await inter.send(f"Creating {game} role")
    cur.execute("SELECT * FROM games WHERE name = ?", (game,))
    row = cur.fetchone()
    if row is None:
        await inter.channel.send("Game does not exist")
        return
    print(row)
    if row[2]:
        await inter.channel.send("Role already exists")
        return
    
    
    colour = None
    if hex_colour:
        colour = disnake.Color.from_hex(hex_colour)
        cur.execute(
        "UPDATE games SET color=? WHERE name=?",
        (colour.value, game)
        )
        conn.commit()
        
    else:
        if row[3]:
            colour = disnake.Colour(row[3])
        else:
            r,g,b = get_theme_color(get_igdb_cover(row[1]))
            colour = disnake.Colour.from_rgb(r,g,b)
    if colour is None:
        await inter.channel.send("Could not generate colour please specify one or try again")
        return
    
    embed = disnake.Embed(
        title=row[1],
        color=colour
    )
    
    guild = bot.get_guild(ORIGINAL_SERVER_ID)
    if guild is None:
        await inter.channel.send("Could not find guild??????")
        return
    
    role = await guild.create_role(name=row[1], colour=colour)
    
    cur.execute(
        "UPDATE games SET roleid=? WHERE name=?",
        (role.id, row[1])
    )
    conn.commit()
    
    for id in get_userids_for_game(row[1]):
        user = guild.get_member(id)
        if user:
            await user.add_roles(role)
    
    await inter.channel.send("Created & Assigned role")
    


def get_userids_for_game(game_name: str):
    cur.execute("""
    SELECT players.userid
    FROM players
    JOIN player_games ON players.id = player_games.player
    JOIN games ON games.id = player_games.game
    WHERE games.name = ?
    """, (game_name,))
    
    return [row[0] for row in cur.fetchall()]
    

@assign_game.autocomplete("game")
@add_role.autocomplete("game")
def game_autocomp(inter: disnake.ApplicationCommandInteraction, string: str):
    cur.execute("SELECT name FROM games")
    games_db = cur.fetchall()
    games = []
    for game in games_db:
        games.append(game[0])
    
    return [game for game in games if string.lower() in game.lower()]


def refresh_igdb():
    print("Refresh token")
    
    with open("igdb.json", "r") as f:
        igdb = json.load(f)
    igdb_ID = igdb["Client_ID"]
    igdb_Secret = igdb["Client_Secret"]
    
    url = "https://id.twitch.tv/oauth2/token"

    data = {
        "client_id": igdb_ID,
        "client_secret": igdb_Secret,
        "grant_type": "client_credentials"
    }

    response = post(url, data=data)

    token = response.json()
    token["expiry_time"] = time.time() + token["expires_in"]
    token["client_id"] = igdb_ID
    with open("igdb_token.json", "w") as f:
        f.write(json.dumps(token, indent=4))


def get_igdb_cover(game_name: str):
    if time.time() >= igdb_token["expiry_time"] - 60:
        
        refresh_igdb()
    
    request = f'search "{game_name}"; fields cover, name, id;'
    response = post('https://api.igdb.com/v4/games', **{'headers': {'Client-ID': igdb_token["client_id"], 'Authorization': f'Bearer {igdb_token["access_token"]}'},'data': request})
    #print ("response: %s" % str(response.json()))

    games = {}
    games_list=[]
    for game in response.json():
        if "cover" in game:
            games[game["name"]] = {
                "id":game["id"],
                "cover": game["cover"]
            }
        
            games_list.append(game["name"])
    
    print(games_list)
    print(game_name)
    close_matches = difflib.get_close_matches(game_name.lower(), games_list, n=3)
    print(close_matches)
    game_name = close_matches[0]
    
    
    request = f'fields url; where game = {games[game_name]["id"]};'
    response = post('https://api.igdb.com/v4/covers', **{'headers': {'Client-ID': igdb_token["client_id"], 'Authorization': f'Bearer {igdb_token["access_token"]}'},'data': request})
    covers = response.json()
    game_cover_url = ""
    for cover in covers:
        if cover["id"] == games[game_name]["cover"]:
            game_cover_url = cover["url"]
    game_cover_url = "https:" + game_cover_url.replace("t_thumb", "t_cover_small")
    return game_cover_url



sql_setup()
igdb_token = {}

try:
    with open("igdb_token.json", "r") as f:
        igdb_token = json.load(f)
except:
    refresh_igdb()
    with open("igdb_token.json", "r") as f:
        igdb_token = json.load(f)
    
if time.time() >= igdb_token["expiry_time"] - 60:
    refresh_igdb()
        
    
if __name__ == "__main__":
    with open("token.txt", "r") as f:
        token = f.read()
    
    bot.run(token)
    
