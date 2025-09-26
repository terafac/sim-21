# AI Pong Competition Guide 🏆

Welcome, competitors! This guide will explain how to connect your trained AI model to the Pong game environment. Your goal is to create an AI that can receive real-time game state information and send back paddle movement commands to win the match.

---

## 🏁 The Goal

You will write a script that acts as a WebSocket client. This script will:
1.  **Connect** to the game server.
2.  **Receive**  messages containing json that has co-ordinates of ball in (x,y).
3.  **Process** this information with your trained model.
4.  **Send** an `ai_prediction` message back to the server with the calculated target Y-coordinate for your paddle.

---

## 🛠️ How to Compete: Step-by-Step

### Step 1: Run the Environment

First, you need to run the game environment locally to test your model.

1.  **Run the Server:**
    Open a terminal and start the Python server. This server acts as the bridge between the game and your AI script.
    ```bash
    # Make sure you have aiohttp installed (pip install aiohttp)
    python server.py
    ```

2.  **Open the Game:**
    Open the `main.html` file in your web browser. You will see the Pong game interface.

3.  **Set to Remote AI Mode:**
    In the game's right-hand panel, under "AI Control Mode," click the **"Remote AI"** button. This tells the game to wait for instructions from an external source (your script!) instead of using its simple built-in AI.

4.  **Start the Match:**
    Press the **"PRESS ENTER TO START"** button in the game window. The ball will start moving, and the game will begin sending out game state information.

### Step 2: Understand the Communication

Your AI script communicates with the server over WebSockets.

### Get the Paddles information
```bash
Invoke-RestMethod -Uri "http://localhost:3000/api/paddles" -Method Get
```
### Get the ball information
```bash
Invoke-RestMethod -Uri "http://localhost:3000/api/ball" -Method Get
```

#### Sending Your Prediction

After receiving the game state, your AI must decide where to move its paddle. You must then send a JSON message back to the server in the following format.
```bash
Invoke-RestMethod -Uri "http://127.0.0.1:8000/predict" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"model":"ai1","targetY":350,"immediate":false}'
```


### How to Run the Example:
1.  Run the html file `main.html`.
2.  Save the code above as `server.py`.
3.  Install the required library: `pip install websockets`.

### Send the information by hitting the API using follwing demo commands


Make sure, that you change ai1 and a12 before sending accordingly. 

### Get the information about the score
```bash
Invoke-RestMethod -Uri "http://localhost:3000/api/score" -Method Get
```

### ✨ Tips for Success

* **Speed Matters:** The faster your model can process the game state and return a `targetY`, the more responsive your paddle will be.

* **Stay Within Bounds:** The paddle cannot go off-screen. Your `targetY` should ideally be within the range `[paddle_height / 2, canvas_height - paddle_height / 2]`.
* **Test Locally:** Use the provided environment to test and refine your model as much as you want before the final submission.

Good luck!
