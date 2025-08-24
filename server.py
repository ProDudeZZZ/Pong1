# server.py
# Python websockets server for Multiplayer Pong (authoritative server)
# HTTP is served separately (use: python -m http.server 8000) from the "static" folder.
# WebSocket endpoint: ws://localhost:8765
#
# Run:
#   pip install websockets
#   python server.py
#
# Then serve static files in another terminal:
#   cd static
#   python -m http.server 8000
#
# Open: http://localhost:8000 in two browser tabs/PCs

import asyncio
import json
import time
import websockets
from websockets.server import WebSocketServerProtocol
from dataclasses import dataclass, field
from typing import Dict, Optional, Set

HOST = "0.0.0.0"
PORT = 8765

WIDTH, HEIGHT = 900, 600
PADDLE_W, PADDLE_H = 14, 110
BALL_SIZE = 14
EDGE_PAD = 30
PADDLE_SPEED = 480.0
BALL_SPEED_START = 360.0
BALL_SPEED_INC = 28.0
MAX_BALL_ANGLE = 0.35
TICK_HZ = 60

ADMIN_CODE = "100"  # <-- admin code

@dataclass
class Player:
    ws: WebSocketServerProtocol
    side: str  # 'left' or 'right' or 'spectator'
    up: bool = False
    down: bool = False
    is_admin: bool = False

@dataclass
class GameState:
    left_y: float = HEIGHT/2 - PADDLE_H/2
    right_y: float = HEIGHT/2 - PADDLE_H/2
    ball_x: float = WIDTH/2 - BALL_SIZE/2
    ball_y: float = HEIGHT/2 - BALL_SIZE/2
    vx: float = BALL_SPEED_START
    vy: float = BALL_SPEED_START * 0.1
    score_l: int = 0
    score_r: int = 0
    paused: bool = False
    event: Optional[str] = None  # 'disco', 'invert', etc.
    broadcast_msg: Optional[str] = None

class PongServer:
    def __init__(self):
        self.clients: Set[WebSocketServerProtocol] = set()
        self.players: Dict[WebSocketServerProtocol, Player] = {}
        self.state = GameState()
        self.last_time = time.time()

    def assign_role(self, ws: WebSocketServerProtocol) -> str:
        # Count current left/right
        sides = [p.side for p in self.players.values()]
        if 'left' not in sides:
            return 'left'
        elif 'right' not in sides:
            return 'right'
        else:
            return 'spectator'

    async def register(self, ws: WebSocketServerProtocol):
        self.clients.add(ws)
        role = self.assign_role(ws)
        self.players[ws] = Player(ws=ws, side=role)
        await self.send(ws, {
            "type": "role",
            "side": role
        })

    async def unregister(self, ws: WebSocketServerProtocol):
        self.clients.discard(ws)
        self.players.pop(ws, None)

    async def send(self, ws: WebSocketServerProtocol, data: dict):
        try:
            await ws.send(json.dumps(data))
        except Exception:
            pass

    async def broadcast(self, data: dict):
        msg = json.dumps(data)
        tasks = []
        for ws in list(self.clients):
            try:
                tasks.append(ws.send(msg))
            except Exception:
                pass
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def reset_ball(self, toward: Optional[str] = None):
        self.state.ball_x = WIDTH/2 - BALL_SIZE/2
        self.state.ball_y = HEIGHT/2 - BALL_SIZE/2
        dir_x = 1.0 if toward == "right" else -1.0 if toward == "left" else (1.0 if (time.time()*1000)%2>1 else -1.0)
        self.state.vx = BALL_SPEED_START * dir_x
        self.state.vy = BALL_SPEED_START * 0.1

    async def handle_message(self, ws: WebSocketServerProtocol, data: dict):
        p = self.players.get(ws)
        if not p:
            return

        t = data.get("type")

        if t == "input":
            p.up = bool(data.get("up"))
            p.down = bool(data.get("down"))

        elif t == "pause":
            # anyone can pause locally? Keep server authoritative; allow admin or players
            if p.side in ("left", "right") or p.is_admin:
                self.state.paused = not self.state.paused

        elif t == "admin_auth":
            code = str(data.get("code", ""))
            if code == ADMIN_CODE:
                p.is_admin = True
                await self.send(ws, {"type": "admin_result", "ok": True})
            else:
                await self.send(ws, {"type": "admin_result", "ok": False})

        elif t == "admin":
            if not p.is_admin:
                return
            action = data.get("action")
            if action == "broadcast":
                msg = str(data.get("message", ""))[:200]
                self.state.broadcast_msg = msg
                await self.broadcast({"type": "broadcast", "message": msg})
            elif action == "event":
                ev = data.get("event")
                if ev in (None, "", "clear"):
                    self.state.event = None
                else:
                    self.state.event = ev
                await self.broadcast({"type": "event", "event": self.state.event})
            elif action == "reset_scores":
                self.state.score_l = 0
                self.state.score_r = 0
            elif action == "pause_toggle":
                self.state.paused = not self.state.paused

    def step_physics(self, dt: float):
        s = self.state
        # paddles
        left_vel = 0.0
        right_vel = 0.0

        # find the controlling connections
        for pl in self.players.values():
            if pl.side == "left":
                if pl.up and not pl.down:
                    left_vel = -PADDLE_SPEED
                elif pl.down and not pl.up:
                    left_vel = PADDLE_SPEED
            elif pl.side == "right":
                if pl.up and not pl.down:
                    right_vel = -PADDLE_SPEED
                elif pl.down and not pl.up:
                    right_vel = PADDLE_SPEED

        s.left_y += left_vel * dt
        s.right_y += right_vel * dt
        s.left_y = max(0, min(HEIGHT - PADDLE_H, s.left_y))
        s.right_y = max(0, min(HEIGHT - PADDLE_H, s.right_y))

        # ball
        s.ball_x += s.vx * dt
        s.ball_y += s.vy * dt

        # walls
        if s.ball_y <= 0:
            s.ball_y = 0
            s.vy *= -1
        elif s.ball_y + BALL_SIZE >= HEIGHT:
            s.ball_y = HEIGHT - BALL_SIZE
            s.vy *= -1

        # paddle rects
        left_rect = (EDGE_PAD, s.left_y, PADDLE_W, PADDLE_H)
        right_rect = (WIDTH - EDGE_PAD - PADDLE_W, s.right_y, PADDLE_W, PADDLE_H)

        # collision helper
        def rects_intersect(ax, ay, aw, ah, bx, by, bw, bh):
            return (ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by)

        # collide with left
        if rects_intersect(s.ball_x, s.ball_y, BALL_SIZE, BALL_SIZE, *left_rect) and s.vx < 0:
            s.ball_x = EDGE_PAD + PADDLE_W
            # influence by hit offset
            pcy = s.left_y + PADDLE_H/2
            offset = ((s.ball_y + BALL_SIZE/2) - pcy) / (PADDLE_H/2)
            s.vy = abs(s.vx) * MAX_BALL_ANGLE * (offset * 1.1)
            s.vx *= -1
            # speed up
            spd = (s.vx**2 + s.vy**2) ** 0.5 + BALL_SPEED_INC
            max_vy = spd * MAX_BALL_ANGLE * 2.2
            s.vy = max(-max_vy, min(max_vy, s.vy))
            vx_sq = max(spd**2 - s.vy**2, 6400.0)
            s.vx = (vx_sq ** 0.5)

        # collide with right
        if rects_intersect(s.ball_x, s.ball_y, BALL_SIZE, BALL_SIZE, *right_rect) and s.vx > 0:
            s.ball_x = WIDTH - EDGE_PAD - PADDLE_W - BALL_SIZE
            pcy = s.right_y + PADDLE_H/2
            offset = ((s.ball_y + BALL_SIZE/2) - pcy) / (PADDLE_H/2)
            s.vy = -abs(s.vx) * MAX_BALL_ANGLE * (offset * 1.1)
            s.vx *= -1
            spd = (s.vx**2 + s.vy**2) ** 0.5 + BALL_SPEED_INC
            max_vy = spd * MAX_BALL_ANGLE * 2.2
            s.vy = max(-max_vy, min(max_vy, s.vy))
            vx_sq = max(spd**2 - s.vy**2, 6400.0)
            s.vx = - (vx_sq ** 0.5)

        # scoring
        if s.ball_x <= 0:
            s.score_r += 1
            self.reset_ball(toward="left")
        elif s.ball_x + BALL_SIZE >= WIDTH:
            s.score_l += 1
            self.reset_ball(toward="right")

    async def tick(self):
        now = time.time()
        dt = max(0.0, min(1.0/30.0, now - self.last_time))
        self.last_time = now

        if not self.state.paused:
            self.step_physics(dt)

        # broadcast state
        payload = {
            "type": "state",
            "left_y": self.state.left_y,
            "right_y": self.state.right_y,
            "ball_x": self.state.ball_x,
            "ball_y": self.state.ball_y,
            "score_l": self.state.score_l,
            "score_r": self.state.score_r,
            "paused": self.state.paused,
            "event": self.state.event,
            "w": WIDTH, "h": HEIGHT
        }
        await self.broadcast(payload)

    async def handle_client(self, ws: WebSocketServerProtocol):
        await self.register(ws)
        try:
            async for msg in ws:
                try:
                    data = json.loads(msg)
                except Exception:
                    continue
                await self.handle_message(ws, data)
        finally:
            await self.unregister(ws)

    async def run(self):
        async with websockets.serve(self.handle_client, HOST, PORT, ping_interval=20, ping_timeout=20):
            # game loop
            tick_delay = 1.0 / TICK_HZ
            while True:
                await self.tick()
                await asyncio.sleep(tick_delay)

if __name__ == "__main__":
    server = PongServer()
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        pass
