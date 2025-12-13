from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import uvicorn
import requests
from nba_api.live.nba.endpoints import scoreboard, playbyplay

app = FastAPI()

# Point to current directory for templates and static files
templates = Jinja2Templates(directory=".")
app.mount("/static", StaticFiles(directory="."), name="static")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# ==========================================
# NBA ENDPOINTS (FIXED: Direct CDN Access)
# ==========================================
# Helper to clean ISO duration (e.g. PT07M29.00S -> 07:29)
def format_nba_clock(iso_string):
    if not iso_string: return ""
    # Remove PT and S, split by M
    clean = iso_string.replace("PT", "").replace("S", "")
    if "M" in clean:
        parts = clean.split("M")
        minutes = parts[0].zfill(2)
        seconds = parts[1].split(".")[0].zfill(2) # Remove decimals
        return f"{minutes}:{seconds}"
    return clean
# ==========================================
# INSERT THIS MISSING ENDPOINT
# ==========================================
@app.get("/api/nba/games")
async def get_nba_games():
    try:
        # specific NBA CDN endpoint for today's scoreboard
        url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
        res = requests.get(url).json()
        
        game_list = []
        for game in res['scoreboard']['games']:
            # Map status code: 1=Sched, 2=Live, 3=Final
            status_map = {1: "SCHED", 2: "LIVE", 3: "FINAL"}
            status = status_map.get(game['gameStatus'], "SCHED")
            
            game_list.append({
                "gameId": game['gameId'],
                "matchup": f"{game['awayTeam']['teamTricode']} @ {game['homeTeam']['teamTricode']}",
                "status": status
            })
        return game_list
    except Exception as e:
        print(f"NBA Games List Error: {e}")
        return []

@app.get("/api/nba/pbp")
async def get_nba_pbp(gameId: str):
    try:
        url = f"https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{gameId}.json"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Referer": "https://www.nba.com/"
        }
        res = requests.get(url, headers=headers)
        
        if res.status_code != 200:
            return {"active": False, "message": "CONNECTING...", "plays": []}

        data = res.json()
        actions = data['game']['actions']
        
        # Get Home Team Tricode for coloring logic
        # Usually found in the meta data or inferred from first play, but for PBP we can check the score keys
        # A safer way in this specific endpoint is to check the 'teamTricode' of a play against known home/away from a schedule,
        # but the JSON usually has game info. Let's rely on the plays.
        
        recent_plays = []
        if actions:
            for action in reversed(actions[-50:]):
                # Clean the clock
                raw_clock = action.get('clock', '')
                clean_clock = format_nba_clock(raw_clock)
                
                # Determine Side (Home vs Away) for coloring
                # The API usually doesn't explicitly say "home" or "away" on the action itself easily without a roster map.
                # HOWEVER, we can use the score update. 
                # If scoreHome changed, it's Home. If scoreAway changed, it's Away. 
                # Fallback: We'll send the raw tricode and handle the specific Home/Away matching in main logic if we had schedule data.
                # For now, let's just pass the tricode. 
                # ACTUALLY, to fulfill your "Red vs Green" request, we need to know who is who.
                # Let's simple check: scoreHome > previous score? 
                
                # Simplified approach: The frontend usually knows Home vs Away from the schedule dropdown. 
                # We will just pass the team code. You asked for "Away=Red, Home=Green".
                # We need to know WHICH code is Home/Away.
                
                recent_plays.append({
                    "clock": clean_clock,
                    "desc": action.get('description', 'Play'),
                    "score": f"{action.get('scoreHome', '')}-{action.get('scoreAway', '')}",
                    "team": action.get('teamTricode', ''),
                    "qualifier": action.get('qualifiers', []) # Helpful for 'dunk', '3pt'
                })
        else: 
            return {"active": False, "message": "PRE-GAME / NO DATA", "plays": []}
            
        return {"active": True, "plays": recent_plays}
    except Exception as e:
        print(f"NBA PBP Error: {e}")
        return {"active": False, "message": "FEED OFFLINE", "plays": []}
# ==========================================
# NFL ENDPOINTS
# ==========================================
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
        for drive in reversed(drives[-10:]):
            drive_team = drive.get('team', {}).get('abbreviation', 'NFL')
            for play in reversed(drive.get('plays', [])):
                recent_plays.append({
                    "clock": play.get('clock', {}).get('displayValue', '-'),
                    "desc": play.get('text', 'Play'),
                    "score": f"Q{play.get('period', {}).get('number','?')}",
                    "team": drive_team
                })
                if len(recent_plays) >= 50: break
            if len(recent_plays) >= 50: break
            
        if not recent_plays: return {"active": False, "message": "WAITING FOR KICKOFF", "plays": []}
        return {"active": True, "plays": recent_plays}
    except: return {"active": False, "message": "FEED OFFLINE", "plays": []}

# ==========================================
# NHL ENDPOINTS
# ==========================================
@app.get("/api/nhl/games")
async def get_nhl_games():
    try:
        url = "https://api-web.nhle.com/v1/score/now"
        res = requests.get(url).json()
        game_list = []
        for game in res.get('games', []):
            state = game['gameState']
            status = "LIVE" if state in ["LIVE", "CRIT"] else ("FINAL" if state in ["FINAL", "OFF"] else "SCHED")
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
        landing_url = f"https://api-web.nhle.com/v1/gamecenter/{gameId}/landing"
        landing = requests.get(landing_url).json()
        
        home_id = landing['homeTeam']['id']
        home_abbr = landing['homeTeam']['abbrev']
        away_id = landing['awayTeam']['id']
        away_abbr = landing['awayTeam']['abbrev']
        
        pbp_url = f"https://api-web.nhle.com/v1/gamecenter/{gameId}/play-by-play"
        pbp = requests.get(pbp_url).json()
        
        recent_plays = []
        for play in reversed(pbp.get('plays', [])[-50:]):
            desc = play.get('typeDescKey', 'Play')
            details = play.get('details', {})
            
            team_id = details.get('eventOwnerTeamId')
            team_abbr = "NHL"
            if team_id == home_id: team_abbr = home_abbr
            elif team_id == away_id: team_abbr = away_abbr
            
            if 'shotType' in details: desc += f" ({details['shotType']})"
            if 'scoringPlayerId' in details: desc += " - GOAL"
            
            recent_plays.append({
                "clock": f"P{play.get('periodDescriptor',{}).get('number','?')} {play.get('timeRemaining','')}",
                "desc": desc,
                "score": f"{details.get('awayScore','-')}-{details.get('homeScore','-')}" if "GOAL" in desc else "",
                "team": team_abbr
            })
            
        if not recent_plays: return {"active": False, "message": "PRE-GAME", "plays": []}
        return {"active": True, "plays": recent_plays}
    except: return {"active": False, "message": "FEED OFFLINE", "plays": []}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)