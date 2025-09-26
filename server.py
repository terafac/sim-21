# server_with_score_endpoint.py
import asyncio
import json
import inspect
import websockets
from datetime import datetime
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# ---------- Shared state ----------
latest_ball_state = None
latest_ball_lock = threading.RLock()   # use RLock to be safe across threads

checkpoint_history = []
total_checkpoints = 0

# paddle_state: store simple canonical state for paddles (center y)
DEFAULT_PADDLE_CENTER = 350  # adjust if your canvas size differs
paddle_state = {
    "ai1": {"y": float(DEFAULT_PADDLE_CENTER)},
    "ai2": {"y": float(DEFAULT_PADDLE_CENTER)},
}

# score_state: store current scores for ai1 and ai2
score_state = {
    "ai1": 0,
    "ai2": 0,
}

# connected websockets (maintained by the asyncio WS handler)
connected_websockets = set()

# reference to main asyncio loop (set in main)
MAIN_LOOP = None

def _now_ms():
    return int(datetime.now().timestamp() * 1000)

def _normalize_record(source: dict):
    ts = source.get("timestamp") or source.get("ts") or _now_ms()
    ball = source.get("ball") or source.get("ballData") or source.get("gameState", {}).get("ball") or {}

    paddle1 = None
    paddle2 = None
    if "gameState" in source and isinstance(source["gameState"], dict):
        gs = source["gameState"]
        paddle1 = gs.get("paddle1") or gs.get("ai1Paddle") or gs.get("paddleLeft")
        paddle2 = gs.get("paddle2") or gs.get("ai2Paddle") or gs.get("paddleRight")

    record = {
        "timestamp": int(ts),
        "position_x": ball.get("x") or ball.get("pos", {}).get("x") or ball.get("position", {}).get("x"),
        "position_y": ball.get("y") or ball.get("pos", {}).get("y") or ball.get("position", {}).get("y"),
        "velocity_x": ball.get("velocityX") or ball.get("velocity", {}).get("x") or ball.get("vel", {}).get("x"),
        "velocity_y": ball.get("velocityY") or ball.get("velocity", {}).get("y") or ball.get("vel", {}).get("y"),
        "radius": ball.get("radius"),
        "speed": ball.get("speed"),
        "lastHit": ball.get("lastHit") or ball.get("last_hit") or source.get("lastHit"),
        "paddle1": paddle1,
        "paddle2": paddle2,
        "raw": source
    }
    return record

# ---------- WebSocket handler ----------
async def my_handler(websocket, path=None):
    global latest_ball_state, checkpoint_history, total_checkpoints, connected_websockets

    peer = getattr(websocket, "remote_address", None)
    print(f"✅ WS Client connected: {peer}  path={path}")
    connected_websockets.add(websocket)

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                print("📥 Received non-JSON message (WS):")
                print(message)
                continue

            print("📥 Received JSON (WS):")
            print(json.dumps(data, indent=2))

            handled_checkpoint = False

            # accept WS checkpoint types and also client gameState payloads
            if data.get("type") == "ball_checkpoint" or "gameState" in data:
                record = _normalize_record(data)
                with latest_ball_lock:
                    latest_ball_state = record
                    checkpoint_history.append(record)
                    total_checkpoints += 1
                print(f"🔁 Updated shared latest_ball_state from WS (total_checkpoints={total_checkpoints})")
                handled_checkpoint = True

            # Optionally respond to client (ack)
            try:
                if websocket.open:
                    ack = {"type": "server_ack", "received_type": data.get("type"), "ts": _now_ms()}
                    await websocket.send(json.dumps(ack))
            except Exception:
                pass

    except websockets.ConnectionClosed:
        print("❌ WS Client disconnected")
    except Exception as e:
        print("⚠️ WS handler exception:", e)
    finally:
        connected_websockets.discard(websocket)

# ---------- Broadcasting helper ----------
async def broadcast_message(payload: dict):
    """
    Send payload (dict) to all connected websockets.
    This coroutine must be scheduled on the main event loop (use run_coroutine_threadsafe from other threads).
    """
    if not connected_websockets:
        return
    text = json.dumps(payload)
    stale = []
    for ws in list(connected_websockets):
        try:
            if ws.open:
                await ws.send(text)
            else:
                stale.append(ws)
        except Exception:
            stale.append(ws)
    for s in stale:
        connected_websockets.discard(s)

# ---------- HTTP server (stdlib) ----------
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def _set_json_headers(self, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")  # allow all for dev
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self):
        # CORS preflight
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        # GET /api/ball -> return latest ball state
        if self.path.startswith("/api/ball"):
            print(f"[HTTP] GET /api/ball received (thread={threading.current_thread().name})")
            with latest_ball_lock:
                if latest_ball_state is None:
                    print("[HTTP] No latest_ball_state available -> returning 404")
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({"error": "no ball state available yet"}).encode())
                    return
                resp = json.loads(json.dumps(latest_ball_state))
            self._set_json_headers(200)
            self.wfile.write(json.dumps(resp).encode())
            return

        # GET /api/checkpoints -> return small history
        if self.path.startswith("/api/checkpoints"):
            print(f"[HTTP] GET /api/checkpoints (thread={threading.current_thread().name})")
            with latest_ball_lock:
                items = list(checkpoint_history)[-50:]  # last 50
            self._set_json_headers(200)
            self.wfile.write(json.dumps({"count": len(items), "items": items}).encode())
            return

        # GET /api/paddles -> return current paddle state
        if self.path.startswith("/api/paddles"):
            print(f"[HTTP] GET /api/paddles (thread={threading.current_thread().name})")
            with latest_ball_lock:
                resp = { "paddles": paddle_state.copy() }
            self._set_json_headers(200)
            self.wfile.write(json.dumps(resp).encode())
            return

        # NEW: GET /api/score -> return current scores
        if self.path.startswith("/api/score"):
            print(f"[HTTP] GET /api/score (thread={threading.current_thread().name})")
            with latest_ball_lock:
                resp = { "ai1": int(score_state.get("ai1", 0)), "ai2": int(score_state.get("ai2", 0)) }
            self._set_json_headers(200)
            self.wfile.write(json.dumps(resp).encode())
            return

        # Unknown GET
        self._set_json_headers(404)
        self.wfile.write(json.dumps({"error": "not found"}).encode())

    def do_POST(self):
        global latest_ball_state, total_checkpoints, paddle_state, MAIN_LOOP, score_state

        path = self.path or ""
        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length) if content_length else b""
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as e:
            self._set_json_headers(400)
            self.wfile.write(json.dumps({"error": "invalid json", "detail": str(e)}).encode())
            return

        # POST /api/checkpoint-data or /api/ball-hit -> accept JSON payload and update latest_ball_state
        if path.startswith("/api/checkpoint-data") or path.startswith("/api/ball-hit"):
            with latest_ball_lock:
                ts = payload.get("checkpoint", {}).get("timestamp") or payload.get("timestamp") or _now_ms()
                ball = payload.get("gameState", {}).get("ball") or payload.get("ballState") or payload.get("ball") or {}
                game_ctx = payload.get("gameState") or payload.get("game") or {}

                record = {
                    "timestamp": int(ts),
                    "position": {"x": ball.get("x") or ball.get("position", {}).get("x"), "y": ball.get("y") or ball.get("position", {}).get("y")},
                    "velocity": {"x": ball.get("velocityX") or ball.get("velocity", {}).get("x"), "y": ball.get("velocityY") or ball.get("velocity", {}).get("y")},
                    "speed": ball.get("speed"),
                    "lastHit": ball.get("lastHit") or ball.get("last_hit"),
                    "checkpoint": payload.get("checkpoint"),
                    "raw_payload": payload,
                    "gameContext": game_ctx
                }

                latest_ball_state = record
                checkpoint_history.append(record)
                total_checkpoints += 1
                print(f"[HTTP POST] Stored checkpoint (total_checkpoints={total_checkpoints})")

                # If payload carries scores, update server-side score_state
                # Accept shapes: {"scores":{"ai1":N,"ai2":M}} or {"score": {...}} or {"ai1Score":N,"ai2Score":M}
                scores = payload.get("scores") or payload.get("score")
                if not scores:
                    # legacy field names
                    if payload.get("ai1Score") is not None or payload.get("ai2Score") is not None:
                        scores = {"ai1": payload.get("ai1Score"), "ai2": payload.get("ai2Score")}
                if isinstance(scores, dict):
                    try:
                        # only update numeric values present
                        if scores.get("ai1") is not None:
                            score_state["ai1"] = int(scores["ai1"])
                        if scores.get("ai2") is not None:
                            score_state["ai2"] = int(scores["ai2"])
                        print(f"[HTTP POST] Updated score_state from payload -> {score_state}")
                    except Exception as e:
                        print("[HTTP POST] Failed to parse scores from payload:", e)

            # Optionally broadcast this update to all WS clients
            try:
                if MAIN_LOOP:
                    msg = {"type": "ball_checkpoint", "payload": record}
                    asyncio.run_coroutine_threadsafe(broadcast_message(msg), MAIN_LOOP)
                    # also broadcast score update if we changed it
                    if isinstance(scores, dict):
                        score_msg = {"type": "score_update", "scores": {"ai1": score_state["ai1"], "ai2": score_state["ai2"]}, "ts": _now_ms()}
                        asyncio.run_coroutine_threadsafe(broadcast_message(score_msg), MAIN_LOOP)
            except Exception as e:
                print("[HTTP POST] Broadcast scheduling failed:", e)

            self._set_json_headers(200)
            self.wfile.write(json.dumps({"ok": True, "stored_at": _now_ms()}).encode())
            return

        # POST /api/paddle-control -> control paddles (existing behavior)
        if path.startswith("/api/paddle-control"):
            paddle = payload.get("paddle")
            action = payload.get("action")
            if paddle not in ("ai1", "ai2"):
                self._set_json_headers(400)
                self.wfile.write(json.dumps({"error": "invalid paddle; use 'ai1' or 'ai2'"}).encode())
                return

            with latest_ball_lock:
                cur_y = paddle_state.get(paddle, {}).get("y")
                if cur_y is None:
                    cur_y = DEFAULT_PADDLE_CENTER
                    paddle_state[paddle]["y"] = cur_y

                if action == "set":
                    y = payload.get("y")
                    try:
                        y = float(y)
                    except Exception:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({"error": "invalid y value for set"}).encode())
                        return
                    paddle_state[paddle]["y"] = y

                elif action == "move":
                    dy = payload.get("dy")
                    try:
                        dy = float(dy)
                    except Exception:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({"error": "invalid dy value for move"}).encode())
                        return
                    paddle_state[paddle]["y"] = cur_y + dy

                elif action == "home":
                    paddle_state[paddle]["y"] = DEFAULT_PADDLE_CENTER

                else:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({"error": "invalid action; use 'set','move',or 'home'"}).encode())
                    return

                update = {
                    "type": "paddle_update",
                    "paddle": paddle,
                    "y": paddle_state[paddle]["y"],
                    "ts": _now_ms()
                }
                print(f"[HTTP POST] Paddle control applied: {update}")

            try:
                if MAIN_LOOP:
                    asyncio.run_coroutine_threadsafe(broadcast_message(update), MAIN_LOOP)
            except Exception as e:
                print("[HTTP POST] Broadcast scheduling failed:", e)

            self._set_json_headers(200)
            self.wfile.write(json.dumps({"ok": True, "paddle": paddle, "y": paddle_state[paddle]["y"]}).encode())
            return

        # NEW: POST /api/score -> set scores manually
        if path.startswith("/api/score"):
            # Accept {"ai1": N, "ai2": M}
            ai1 = payload.get("ai1")
            ai2 = payload.get("ai2")
            with latest_ball_lock:
                changed = False
                if ai1 is not None:
                    try:
                        score_state["ai1"] = int(ai1)
                        changed = True
                    except Exception:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({"error": "invalid ai1 value; must be integer"}).encode())
                        return
                if ai2 is not None:
                    try:
                        score_state["ai2"] = int(ai2)
                        changed = True
                    except Exception:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({"error": "invalid ai2 value; must be integer"}).encode())
                        return

                print(f"[HTTP POST] Manual score update: {score_state}")

            # broadcast score update to websockets, if any
            try:
                if MAIN_LOOP and changed:
                    score_msg = {"type": "score_update", "scores": {"ai1": score_state["ai1"], "ai2": score_state["ai2"]}, "ts": _now_ms()}
                    asyncio.run_coroutine_threadsafe(broadcast_message(score_msg), MAIN_LOOP)
            except Exception as e:
                print("[HTTP POST] Score broadcast scheduling failed:", e)

            self._set_json_headers(200)
            self.wfile.write(json.dumps({"ok": True, "scores": score_state}).encode())
            return

        # Unknown POST
        self._set_json_headers(404)
        self.wfile.write(json.dumps({"error": "not found"}).encode())

# ---------- Thread to run HTTP server ----------
def run_http_server(host="0.0.0.0", port=3000):
    server = HTTPServer((host, port), SimpleHTTPRequestHandler)
    print(f"🌐 HTTP API server running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()

# ---------- Adapter for handler signature compatibility ----------
def make_adapter(user_handler):
    sig = inspect.signature(user_handler)
    params = len(sig.parameters)
    async def adapter(websocket, path=None):
        if params == 1:
            await user_handler(websocket)
        else:
            await user_handler(websocket, path)
    return adapter

# ---------- Main: start HTTP thread and run websocket server ----------
async def main(host="localhost", port=8765, http_host="0.0.0.0", http_port=3000):
    global MAIN_LOOP
    MAIN_LOOP = asyncio.get_running_loop()

    # start HTTP server in background thread (no extra deps)
    http_thread = threading.Thread(target=run_http_server, args=(http_host, http_port), daemon=True, name="HTTPThread")
    http_thread.start()

    adapter = make_adapter(my_handler)
    async with websockets.serve(adapter, host, port):
        print(f"🚀 WebSocket server running at ws://{host}:{port}")
        print("📡 Accepting websocket messages and also serving HTTP API endpoints.")
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
        print(f"📊 Total checkpoints received: {total_checkpoints}")
        print(f"🏁 Final score_state: {score_state}")
