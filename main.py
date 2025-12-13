from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import uvicorn
from nba_api.live.nba.endpoints import scoreboard, playbyplay

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Mount static files if needed
app.mount("/static", StaticFiles(directory="."), name="static")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# --- NEW: Get List of Active Games for Dropdown ---
@app.get("/api/nba/games")
async def get_nba_games():
    try:
        board = scoreboard.ScoreBoard()
        games = board.games.get_dict()
        game_list = []
        for game in games:
            # We want games that are Live (2) or Scheduled (1) or Final (3)
            # You might want to filter only for Live/Scheduled if you prefer
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
        print("Error fetching games:", e)
        return []

# --- UPDATED: Get PBP for specific Game ID ---
@app.get("/api/nba/pbp")
async def get_nba_pbp(gameId: str):
    try:
        # Fetch Play by Play for that specific Game ID
        pbp = playbyplay.PlayByPlay(gameId)
        actions = pbp.get_dict()['actions']
        
        # Get last 15 actions, reversed (newest at top)
        recent_plays = []
        if actions:
            # Reversing to show newest first
            for action in reversed(actions[-15:]):
                recent_plays.append({
                    "clock": action['clock'],
                    "desc": action['description'],
                    "score": f"{action['scoreHome']} - {action['scoreAway']}",
                    "team": action['teamTricode']
                })
        else:
             return {"active": False, "message": "NO PLAYS YET / PRE-GAME", "plays": []}

        return {
            "active": True,
            "plays": recent_plays
        }

    except Exception as e:
        print(f"Error fetching PBP for {gameId}: {e}")
        return {"active": False, "message": "GAME NOT STARTED OR ENDED", "plays": []}

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)