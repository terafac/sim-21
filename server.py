# save as ws_server_print.py
import asyncio
import json
import inspect
import websockets

# ---- Your real handler logic (you can modify this) ----
async def my_handler(websocket, path=None):
    """Handle incoming websocket messages and print them.
       Accepts either (websocket, path) or (websocket,) style calls.
    """
    # Print connection info
    try:
        peer = websocket.remote_address
    except Exception:
        peer = None
    print(f"✅ Client connected: {peer}  path={path}")

    try:
        async for message in websocket:
            # try parse JSON, otherwise print raw
            try:
                data = json.loads(message)
                print("📥 Received JSON:")
                print(json.dumps(data, indent=2))
            except json.JSONDecodeError:
                print("📥 Received non-JSON message:")
                print(message)
    except websockets.ConnectionClosed:
        print("❌ Client disconnected")
    except Exception as e:
        print("⚠️ Handler exception:", e)


# ---- Adapter to support both handler signatures ----
def make_adapter(user_handler):
    sig = inspect.signature(user_handler)
    params = len(sig.parameters)

    async def adapter(websocket, path=None):
        # If user's handler expects 1 param -> call with websocket only.
        # If expects 2 params -> call with websocket, path.
        if params == 1:
            await user_handler(websocket)
        else:
            await user_handler(websocket, path)
    return adapter

# ---- Server run ----
async def main(host="localhost", port=8765):
    adapter = make_adapter(my_handler)
    async with websockets.serve(adapter, host, port):
        print(f"🚀 WebSocket server running at ws://{host}:{port}")
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
