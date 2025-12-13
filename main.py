from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import uvicorn
import requests
from nba_api.live.nba.endpoints import scoreboard, playbyplay

app = FastAPI()
templates = Jinja2Templates(directory=".")
app.mount("/static", StaticFiles(directory="."), name="static")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# ======================= NBA =======================
@app.get("/api/nba/games")
async def get_nba_games():
    try:
        board = scoreboard.ScoreBoard()
        games = board.games.get_dict()
        game_list = []
        for game in games:
            status = "Scheduled"
            if game['gameStatus'] == 2: status = "LIVE"
            if game['gameStatus'] == 3: status = "Final"
            game_list.append({
                "gameId": game['gameId'],
                "matchup": f"{game['awayTeam']['teamTricode']} @ {game['homeTeam']['teamTricode']}",
                "status": status
            })
        return game_list
    except: return []

@app.get("/api/nba/pbp")
async def get_nba_pbp(gameId: str):
    try:
        pbp = playbyplay.PlayByPlay(gameId)
        actions = pbp.get_dict()['actions']
        recent_plays = []
        # Get last 50 plays for a scrollable history
        if actions:
            for action in reversed(actions[-50:]):
                recent_plays.append({
                    "clock": action['clock'],
                    "desc": action['description'], # Contains player names
                    "score": f"{action['scoreHome']}-{action['scoreAway']}",
                    "team": action['teamTricode']
                })
        else: return {"active": False, "message": "PRE-GAME / NO DATA", "plays": []}
        return {"active": True, "plays": recent_plays}
    except: return {"active": False, "message": "FEED OFFLINE", "plays": []}

# ======================= NFL =======================
@app.get("/api/nfl/games")
async def get_nfl_games():
    try:
        url = "http://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
        res = requests.get(url).json()
        game_list = []
        for event in res['events']:
            status = event['status']['type']['state'].upper().replace("IN","LIVE").replace("POST","FINAL").replace("PRE","SCHED")
            game_list.append({
                "gameId": event['id'],
                "matchup": event['shortName'],
                "status": status
            })
        return game_list
    except: return []

@app.get("/api/nfl/pbp")
async def get_nfl_pbp(gameId: str):
    try:
        url = f"http://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={gameId}"
        res = requests.get(url).json()
        drives = res.get('drives', {}).get('previous', [])
        curr = res.get('drives', {}).get('current')
        if curr: drives.append(curr)
        
        recent_plays = []
        # Flatten drives to get simple play list
        for drive in reversed(drives[-5:]): # Check last 5 drives
            for play in reversed(drive.get('plays', [])):
                recent_plays.append({
                    "clock": play.get('clock', {}).get('displayValue', '-'),
                    "desc": play.get('text', 'Play'), # Contains "Mahomes pass to..."
                    "score": f"Q{play.get('period', {}).get('number','?')}",
                    "team": "NFL"
                })
                if len(recent_plays) >= 50: break
            if len(recent_plays) >= 50: break
            
        if not recent_plays: return {"active": False, "message": "WAITING FOR KICKOFF", "plays": []}
        return {"active": True, "plays": recent_plays}
    except: return {"active": False, "message": "FEED OFFLINE", "plays": []}

# ======================= NHL =======================
@app.get("/api/nhl/games")
async def get_nhl_games():
    try:
        url = "https://api-web.nhle.com/v1/score/now"
        res = requests.get(url).json()
        game_list = []
        for game in res.get('games', []):
            state = game['gameState']
            status = "LIVE" if state in ["LIVE","CRIT"] else ("Final" if state in ["FINAL","OFF"] else "Scheduled")
            game_list.append({
                "gameId": game['id'],
                "matchup": f"{game['awayTeam']['abbrev']} @ {game['homeTeam']['abbrev']}",
                "status": status
            })
        return game_list
    except: return []

@app.get("/api/nhl/pbp")
async def get_nhl_pbp(gameId: str):
    try:
        url = f"https://api-web.nhle.com/v1/gamecenter/{gameId}/play-by-play"
        res = requests.get(url).json()
        recent_plays = []
        for play in reversed(res.get('plays', [])[-50:]):
            desc = play.get('typeDescKey', 'Play')
            # Try to get player involved if available
            details = play.get('details', {})
            if 'shotType' in details: desc += f" ({details['shotType']})"
            if 'scoringPlayerId' in details: desc += " - GOAL"
            
            recent_plays.append({
                "clock": f"P{play.get('periodDescriptor',{}).get('number','?')} {play.get('timeRemaining','')}",
                "desc": desc,
                "score": f"{details.get('awayScore','-')}-{details.get('homeScore','-')}" if desc.endswith("GOAL") else "",
                "team": "NHL"
            })
        if not recent_plays: return {"active": False, "message": "PRE-GAME", "plays": []}
        return {"active": True, "plays": recent_plays}
    except: return {"active": False, "message": "FEED OFFLINE", "plays": []}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)