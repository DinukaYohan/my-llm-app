# backend/app.py

import os
import sqlite3
import torch
from flask import Flask, request, jsonify, g
from transformers import AutoTokenizer, AutoModelForCausalLM

# ─── Flask app setup ────────────────────────────────────────────────────────────
app = Flask(__name__)

# ─── Database configuration ─────────────────────────────────────────────────────
# Build path to the SQLite database file in this same folder
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "conversations.db")

def get_db():
    """
    Return a SQLite connection for the current Flask request.
    Stored on `g` so that multiple calls in one request reuse the same connection.
    """
    if "_db" not in g:
        g._db = sqlite3.connect(DB_PATH)
        # Make rows behave like dictionaries: row["prompt"]
        g._db.row_factory = sqlite3.Row
    return g._db

@app.teardown_appcontext
def close_db(exception):
    """
    Called after each request finishes.
    Closes the database connection if it was opened.
    """
    db = g.pop("_db", None)
    if db is not None:
        db.close()

def init_db():
    """
    Create the `conversations` table if it doesn't exist.
    Columns:
      - id: primary key
      - prompt: text of the user prompt
      - response: text of the model reply
      - created_at: timestamp of when the row was inserted
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
      CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prompt TEXT NOT NULL,
        response TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
    """)
    conn.commit()
    conn.close()

# Initialize the database on startup
init_db()


# ─── Model loading ───────────────────────────────────────────────────────────────
MODEL_NAME = "Qwen/Qwen3-0.6B"

# 1) Load tokenizer and model once at startup
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model     = AutoModelForCausalLM.from_pretrained(
    MODEL_NAME,
    torch_dtype=torch.float32  # use float32 for MPS/CPU
)

# 2) Select device: MPS on Apple Silicon or fallback to CPU
device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
model.to(device)


# ─── API endpoint ───────────────────────────────────────────────────────────────
@app.route("/generate", methods=["POST"])
def generate():
    """
    Receive JSON { "prompt": "..." } in the request body,
    generate a reply via Qwen3-0.6B, store prompt+reply in SQLite,
    and return JSON { "reply": "..." }.
    """
    # Parse JSON body (force=True will raise if invalid JSON)
    data = request.get_json(force=True)
    prompt = data.get("prompt", "").strip()

    # Build the chat template for Qwen (non-thinking mode)
    messages = [{"role": "user", "content": prompt}]
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False
    )

    # Tokenize & move tensors to the correct device (MPS/CPU)
    inputs = tokenizer([text], return_tensors="pt").to(device)

    # Generate up to 512 new tokens
    output_ids = model.generate(**inputs, max_new_tokens=512)[0].tolist()

    # Only decode the newly generated tokens (skip over the input length)
    input_len = len(inputs.input_ids[0])
    reply = tokenizer.decode(
        output_ids[input_len:], 
        skip_special_tokens=True
    ).strip()

    # ─── Persist conversation to SQLite ────────────────────────────────────────
    db = get_db()
    db.execute(
        "INSERT INTO conversations (prompt, response) VALUES (?, ?)",
        (prompt, reply)
    )
    db.commit()

    # Return the reply as JSON
    return jsonify({"reply": reply})


@app.route("/history", methods=["GET"])
def history():
    try:
        limit = int(request.args.get("limit", 5))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "limit/offset must be integers"}), 400

    db = get_db()
    rows = db.execute(
        """
        SELECT id, prompt, response, created_at
        FROM conversations
        ORDER BY datetime(created_at) DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()

    return jsonify([
        {
            "id": r["id"],
            "prompt": r["prompt"],
            "response": r["response"],
            "created_at": r["created_at"],
        } for r in rows
    ])

# ── Entrypoint ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)