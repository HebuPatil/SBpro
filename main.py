from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import uvicorn
import requests # <--- Make sure this is imported
from nba_api.live.nba.endpoints import scoreboard, playbyplay

app = FastAPI()
templates = Jinja2Templates(directory=".")

app.mount("/static", StaticFiles(directory="."), name="static")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# ==========================================
# NBA ENDPOINTS (Existing)
# ==========================================
@app.get("/api/nba/games")
async def get_nba_games():
    try:
        board = scoreboard.ScoreBoard()
        games = board.games.get_dict()
        game_list = []
        for game in games:
            status_text = "Scheduled"
            if game['gameStatus'] == 2: status_text = "LIVE"
            if game['gameStatus'] == 3: status_text = "Final"
            
            game_list.append({
                "gameId": game['gameId'],
                "matchup": f"{game['awayTeam']['teamTricode']} @ {game['homeTeam']['teamTricode']}",
                "status": status_text
            })
        return game_list
    except Exception as e:
        print("Error fetching NBA games:", e)
        return []

@app.get("/api/nba/pbp")
async def get_nba_pbp(gameId: str):
    try:
        pbp = playbyplay.PlayByPlay(gameId)
        actions = pbp.get_dict()['actions']
        recent_plays = []
        if actions:
            for action in reversed(actions[-15:]):
                recent_plays.append({
                    "clock": action['clock'],
                    "desc": action['description'],
                    "score": f"{action['scoreHome']} - {action['scoreAway']}",
                    "team": action['teamTricode']
                })
        else:
             return {"active": False, "message": "NO PLAYS YET / PRE-GAME", "plays": []}
        return {"active": True, "plays": recent_plays}
    except Exception as e:
        return {"active": False, "message": "GAME NOT STARTED", "plays": []}

# ==========================================
# NFL ENDPOINTS (New)
# ==========================================
@app.get("/api/nfl/games")
async def get_nfl_games():
    try:
        # Fetch generic scoreboard
        url = "http://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
        res = requests.get(url).json()
        game_list = []
        
        for event in res['events']:
            game_id = event['id']
            status = event['status']['type']['state'].upper() # pre, in, post
            short_name = event['shortName'] # e.g. "KC @ BUF"
            
            # Format status for dropdown
            if status == "IN": status = "LIVE"
            elif status == "POST": status = "FINAL"
            elif status == "PRE": status = "SCHED"
            
            game_list.append({
                "gameId": game_id,
                "matchup": short_name,
                "status": status
            })
        return game_list
    except Exception as e:
        print("Error fetching NFL games:", e)
        return []

@app.get("/api/nfl/pbp")
async def get_nfl_pbp(gameId: str):
    try:
        # Fetch specific game summary
        url = f"http://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={gameId}"
        res = requests.get(url).json()
        
        # ESPN organizes PBP by "Drives". We need to flatten them.
        drives = res.get('drives', {}).get('previous', [])
        
        # Also check 'current' drive if live
        current_drive = res.get('drives', {}).get('current')
        if current_drive:
            drives.append(current_drive)

        recent_plays = []
        
        # Loop through last few drives to get plays
        for drive in reversed(drives[-3:]): # Check last 3 drives
            plays = drive.get('plays', [])
            for play in reversed(plays):
                # Extract clean data
                desc = play.get('text', 'No description')
                clock = play.get('clock', {}).get('displayValue', '-')
                # Determine team (if available)
                # ESPN API is tricky with team possession in plays, simplified here:
                recent_plays.append({
                    "clock": clock,
                    "desc": desc,
                    "score": f"Q{play.get('period', {}).get('number','-')}", # Using Quarter as score placeholder or use actual score if found
                    "team": "NFL" # Generic marker or extract from drive['team']['abbreviation']
                })
                if len(recent_plays) >= 15: break
            if len(recent_plays) >= 15: break

        if not recent_plays:
             return {"active": False, "message": "WAITING FOR KICKOFF", "plays": []}

        return {"active": True, "plays": recent_plays}

    except Exception as e:
        print(f"Error fetching NFL PBP for {gameId}: {e}")
        return {"active": False, "message": "FEED OFFLINE", "plays": []}

# ==========================================
# NHL ENDPOINTS (New)
# ==========================================
@app.get("/api/nhl/games")
async def get_nhl_games():
    try:
        # NHL 'Score Now' endpoint gets today's games
        url = "https://api-web.nhle.com/v1/score/now"
        res = requests.get(url).json()
        
        game_list = []
        # The API returns a 'games' list for the current day
        games = res.get('games', [])
        
        for game in games:
            game_id = game['id']
            state = game['gameState'] # FUT, PRE, LIVE, CRIT, FINAL, OFF
            
            # Map NHL states to our HUD statuses
            status_text = "Scheduled"
            if state in ["LIVE", "CRIT"]: status_text = "LIVE"
            if state in ["FINAL", "OFF"]: status_text = "Final"
            
            matchup = f"{game['awayTeam']['abbrev']} @ {game['homeTeam']['abbrev']}"
            
            game_list.append({
                "gameId": game_id,
                "matchup": matchup,
                "status": status_text
            })
            
        return game_list
    except Exception as e:
        print("Error fetching NHL games:", e)
        return []

@app.get("/api/nhl/pbp")
async def get_nhl_pbp(gameId: str):
    try:
        url = f"https://api-web.nhle.com/v1/gamecenter/{gameId}/play-by-play"
        res = requests.get(url).json()
        
        all_plays = res.get('plays', [])
        recent_plays = []
        
        # Grab the last 15 plays, reversed (newest first)
        for play in reversed(all_plays[-15:]):
            period = play.get('periodDescriptor', {}).get('number', 0)
            time = play.get('timeRemaining', '00:00')
            event_type = play.get('typeDescKey', '').upper()
            
            # Construct a description based on event type
            desc = event_type
            details = play.get('details', {})
            
            if event_type == 'GOAL':
                scorer = details.get('scoringPlayerId', 'Unknown') # ID only, usually need roster lookup
                # Simplified for HUD: Just show it's a Goal
                desc = f"🚨 GOAL! ({details.get('shotType', 'Shot')})"
            elif event_type == 'SHOT-ON-GOAL':
                desc = f"Shot on Goal ({details.get('shotType', '')})"
            elif event_type == 'HIT':
                desc = "Hit"
            elif event_type == 'PENALTY':
                desc = f"PENALTY ({details.get('typeCode', '')})"

            recent_plays.append({
                "clock": f"P{period} {time}",
                "desc": desc,
                "score": f"{details.get('awayScore', '-')}-{details.get('homeScore', '-')}" if event_type == 'GOAL' else "",
                "team": "NHL" # The API makes determining team ownership of an event complex, generic for now
            })

        if not recent_plays:
             return {"active": False, "message": "WARM UPS / PRE-GAME", "plays": []}

        return {"active": True, "plays": recent_plays}

    except Exception as e:
        print(f"Error fetching NHL PBP for {gameId}: {e}")
        return {"active": False, "message": "FEED OFFLINE", "plays": []}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)