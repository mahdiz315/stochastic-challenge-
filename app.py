
from flask import Flask, render_template, request, jsonify, send_file, Response
import csv
import io
import os
import random
import secrets
import sqlite3
import threading
from collections import Counter
from datetime import datetime

app = Flask(__name__)
DB_PATH = os.environ.get("DATABASE_PATH", "stochastic_challenge.db")
db_lock = threading.Lock()


def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_lock:
        conn = db()
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS games (
            room TEXT PRIMARY KEY,
            teacher_token TEXT NOT NULL,
            round_no INTEGER NOT NULL,
            total_rounds INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS students (
            room TEXT NOT NULL,
            player_id TEXT NOT NULL,
            name TEXT NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (room, player_id)
        );

        CREATE TABLE IF NOT EXISTS predictions (
            room TEXT NOT NULL,
            round_no INTEGER NOT NULL,
            player_id TEXT NOT NULL,
            choice INTEGER NOT NULL,
            PRIMARY KEY (room, round_no, player_id)
        );

        CREATE TABLE IF NOT EXISTS results (
            room TEXT NOT NULL,
            round_no INTEGER NOT NULL,
            die_result INTEGER NOT NULL,
            PRIMARY KEY (room, round_no)
        );
        """)
        conn.commit()
        conn.close()


init_db()


def get_game(room):
    conn = db()
    row = conn.execute("SELECT * FROM games WHERE room=?", (room,)).fetchone()
    conn.close()
    return dict(row) if row else None


def require_teacher(game, token):
    return bool(game and secrets.compare_digest(game["teacher_token"], token or ""))


def base_url():
    # Works on localhost and on public hosting such as Render.
    return request.host_url.rstrip("/")


def public_state(room, player_id=None):
    conn = db()
    game = conn.execute("SELECT * FROM games WHERE room=?", (room,)).fetchone()
    if not game:
        conn.close()
        return None

    round_no = game["round_no"]
    students = conn.execute(
        "SELECT player_id, name, score FROM students WHERE room=?",
        (room,)
    ).fetchall()

    leaderboard = sorted(
        [{"name": r["name"], "score": r["score"]} for r in students],
        key=lambda x: (-x["score"], x["name"].lower())
    )

    prediction_count = conn.execute(
        "SELECT COUNT(*) AS c FROM predictions WHERE room=? AND round_no=?",
        (room, round_no)
    ).fetchone()["c"]

    result_row = conn.execute(
        "SELECT die_result FROM results WHERE room=? AND round_no=?",
        (room, round_no)
    ).fetchone()
    result = result_row["die_result"] if result_row else None

    winners_this_round = 0
    if result is not None:
        winners_this_round = conn.execute(
            "SELECT COUNT(*) AS c FROM predictions "
            "WHERE room=? AND round_no=? AND choice=?",
            (room, round_no, result)
        ).fetchone()["c"]

    own = None
    if player_id:
        s = conn.execute(
            "SELECT name, score FROM students WHERE room=? AND player_id=?",
            (room, player_id)
        ).fetchone()
        if s:
            pred = conn.execute(
                "SELECT choice FROM predictions WHERE room=? AND round_no=? AND player_id=?",
                (room, round_no, player_id)
            ).fetchone()
            own = {
                "name": s["name"],
                "score": s["score"],
                "prediction": pred["choice"] if pred else None,
            }

    state = {
        "room": room,
        "round": round_no,
        "total_rounds": game["total_rounds"],
        "status": game["status"],
        "student_count": len(students),
        "prediction_count": prediction_count,
        "top5": leaderboard[:5],
        "result": result,
        "winners_this_round": winners_this_round,
        "own": own,
        "finished_stats": finished_stats_conn(conn, room, game["total_rounds"])
            if game["status"] == "finished" else None,
    }
    conn.close()
    return state


def finished_stats_conn(conn, room, total_rounds):
    scores = [r["score"] for r in conn.execute(
        "SELECT score FROM students WHERE room=?", (room,)
    ).fetchall()]

    all_predictions = [r["choice"] for r in conn.execute(
        "SELECT choice FROM predictions WHERE room=?", (room,)
    ).fetchall()]

    die_results = [r["die_result"] for r in conn.execute(
        "SELECT die_result FROM results WHERE room=?", (room,)
    ).fetchall()]

    pred_counts = Counter(all_predictions)
    die_counts = Counter(die_results)

    most_popular = None
    if pred_counts:
        m = max(pred_counts.values())
        most_popular = [n for n in range(1, 7) if pred_counts.get(n, 0) == m]

    most_rolled = None
    if die_counts:
        m = max(die_counts.values())
        most_rolled = [n for n in range(1, 7) if die_counts.get(n, 0) == m]

    ranking = [
        {"name": r["name"], "score": r["score"]}
        for r in conn.execute(
            "SELECT name, score FROM students WHERE room=? "
            "ORDER BY score DESC, name COLLATE NOCASE ASC",
            (room,)
        ).fetchall()
    ]

    return {
        "expected_random_score": round(total_rounds / 6, 2),
        "class_average": round(sum(scores) / len(scores), 2) if scores else 0,
        "highest_score": max(scores) if scores else 0,
        "lowest_score": min(scores) if scores else 0,
        "most_popular_number": most_popular,
        "number_rolled_most_often": most_rolled,
        "ranking": ranking,
    }


@app.route("/")
def student_page():
    return render_template("student.html")


@app.route("/teacher")
def teacher_page():
    return render_template("teacher.html")


@app.route("/health")
def health():
    return jsonify({"ok": True})


@app.route("/api/create", methods=["POST"])
def create_game():
    data = request.get_json(silent=True) or {}
    try:
        total_rounds = int(data.get("total_rounds", 20))
    except Exception:
        total_rounds = 20
    total_rounds = max(1, min(total_rounds, 100))

    with db_lock:
        conn = db()
        while True:
            room = str(random.randint(1000, 9999))
            exists = conn.execute("SELECT 1 FROM games WHERE room=?", (room,)).fetchone()
            if not exists:
                break

        token = secrets.token_urlsafe(24)
        conn.execute(
            "INSERT INTO games(room, teacher_token, round_no, total_rounds, status, created_at) "
            "VALUES(?,?,?,?,?,?)",
            (room, token, 1, total_rounds, "accepting",
             datetime.now().isoformat(timespec="seconds"))
        )
        conn.commit()
        conn.close()

    student_url = f"{base_url()}/?room={room}"
    return jsonify({
        "ok": True,
        "room": room,
        "teacher_token": token,
        "student_url": student_url,
        "state": public_state(room),
    })


@app.route("/api/join", methods=["POST"])
def join_game():
    data = request.get_json(silent=True) or {}
    room = str(data.get("room", "")).strip()
    name = str(data.get("name", "")).strip()[:40]
    player_id = str(data.get("player_id", "")).strip()[:100]

    if not room or not name or not player_id:
        return jsonify({"ok": False, "error": "Room, name, and player ID are required."}), 400

    with db_lock:
        conn = db()
        game = conn.execute("SELECT * FROM games WHERE room=?", (room,)).fetchone()
        if not game:
            conn.close()
            return jsonify({"ok": False, "error": "Game room not found."}), 404
        if game["status"] == "finished":
            conn.close()
            return jsonify({"ok": False, "error": "This game has already finished."}), 400

        conn.execute(
            "INSERT INTO students(room, player_id, name, score) VALUES(?,?,?,0) "
            "ON CONFLICT(room, player_id) DO UPDATE SET name=excluded.name",
            (room, player_id, name)
        )
        conn.commit()
        conn.close()

    return jsonify({"ok": True, "state": public_state(room, player_id)})


@app.route("/api/state")
def state():
    room = str(request.args.get("room", "")).strip()
    player_id = str(request.args.get("player_id", "")).strip() or None
    state_data = public_state(room, player_id)
    if not state_data:
        return jsonify({"ok": False, "error": "Game room not found."}), 404
    return jsonify({"ok": True, "state": state_data})


@app.route("/api/predict", methods=["POST"])
def predict():
    data = request.get_json(silent=True) or {}
    room = str(data.get("room", "")).strip()
    player_id = str(data.get("player_id", "")).strip()

    try:
        choice = int(data.get("choice"))
    except Exception:
        choice = 0

    if choice not in range(1, 7):
        return jsonify({"ok": False, "error": "Choice must be 1 through 6."}), 400

    with db_lock:
        conn = db()
        game = conn.execute("SELECT * FROM games WHERE room=?", (room,)).fetchone()
        if not game:
            conn.close()
            return jsonify({"ok": False, "error": "Game room not found."}), 404

        student = conn.execute(
            "SELECT 1 FROM students WHERE room=? AND player_id=?",
            (room, player_id)
        ).fetchone()
        if not student:
            conn.close()
            return jsonify({"ok": False, "error": "Please join the game first."}), 403

        if game["status"] != "accepting":
            conn.close()
            return jsonify({"ok": False, "error": "Predictions are locked."}), 400

        conn.execute(
            "INSERT INTO predictions(room, round_no, player_id, choice) VALUES(?,?,?,?) "
            "ON CONFLICT(room, round_no, player_id) DO UPDATE SET choice=excluded.choice",
            (room, game["round_no"], player_id, choice)
        )
        conn.commit()
        conn.close()

    return jsonify({"ok": True, "state": public_state(room, player_id)})


@app.route("/api/lock", methods=["POST"])
def lock_predictions():
    data = request.get_json(silent=True) or {}
    room = str(data.get("room", "")).strip()
    token = str(data.get("teacher_token", "")).strip()

    with db_lock:
        conn = db()
        game = conn.execute("SELECT * FROM games WHERE room=?", (room,)).fetchone()
        game_dict = dict(game) if game else None
        if not require_teacher(game_dict, token):
            conn.close()
            return jsonify({"ok": False, "error": "Teacher authorization failed."}), 403
        if game["status"] != "accepting":
            conn.close()
            return jsonify({"ok": False, "error": "Predictions are not currently open."}), 400

        conn.execute("UPDATE games SET status='locked' WHERE room=?", (room,))
        conn.commit()
        conn.close()

    return jsonify({"ok": True, "state": public_state(room)})


@app.route("/api/result", methods=["POST"])
def set_result():
    data = request.get_json(silent=True) or {}
    room = str(data.get("room", "")).strip()
    token = str(data.get("teacher_token", "")).strip()

    try:
        result = int(data.get("result"))
    except Exception:
        result = 0

    if result not in range(1, 7):
        return jsonify({"ok": False, "error": "Die result must be 1 through 6."}), 400

    with db_lock:
        conn = db()
        game = conn.execute("SELECT * FROM games WHERE room=?", (room,)).fetchone()
        game_dict = dict(game) if game else None
        if not require_teacher(game_dict, token):
            conn.close()
            return jsonify({"ok": False, "error": "Teacher authorization failed."}), 403
        if game["status"] != "locked":
            conn.close()
            return jsonify({"ok": False, "error": "Lock predictions before entering the die result."}), 400

        existing = conn.execute(
            "SELECT 1 FROM results WHERE room=? AND round_no=?",
            (room, game["round_no"])
        ).fetchone()
        if existing:
            conn.close()
            return jsonify({"ok": False, "error": "This round already has a result."}), 400

        conn.execute(
            "INSERT INTO results(room, round_no, die_result) VALUES(?,?,?)",
            (room, game["round_no"], result)
        )

        winners = conn.execute(
            "SELECT player_id FROM predictions WHERE room=? AND round_no=? AND choice=?",
            (room, game["round_no"], result)
        ).fetchall()

        for w in winners:
            conn.execute(
                "UPDATE students SET score=score+1 WHERE room=? AND player_id=?",
                (room, w["player_id"])
            )

        conn.execute("UPDATE games SET status='result' WHERE room=?", (room,))
        conn.commit()
        conn.close()

    return jsonify({"ok": True, "state": public_state(room)})


@app.route("/api/next", methods=["POST"])
def next_round():
    data = request.get_json(silent=True) or {}
    room = str(data.get("room", "")).strip()
    token = str(data.get("teacher_token", "")).strip()

    with db_lock:
        conn = db()
        game = conn.execute("SELECT * FROM games WHERE room=?", (room,)).fetchone()
        game_dict = dict(game) if game else None
        if not require_teacher(game_dict, token):
            conn.close()
            return jsonify({"ok": False, "error": "Teacher authorization failed."}), 403
        if game["status"] != "result":
            conn.close()
            return jsonify({"ok": False, "error": "Enter the die result before moving on."}), 400

        if game["round_no"] >= game["total_rounds"]:
            conn.execute("UPDATE games SET status='finished' WHERE room=?", (room,))
        else:
            conn.execute(
                "UPDATE games SET round_no=round_no+1, status='accepting' WHERE room=?",
                (room,)
            )
        conn.commit()
        conn.close()

    return jsonify({"ok": True, "state": public_state(room)})


@app.route("/api/finish", methods=["POST"])
def finish_game():
    data = request.get_json(silent=True) or {}
    room = str(data.get("room", "")).strip()
    token = str(data.get("teacher_token", "")).strip()

    with db_lock:
        conn = db()
        game = conn.execute("SELECT * FROM games WHERE room=?", (room,)).fetchone()
        game_dict = dict(game) if game else None
        if not require_teacher(game_dict, token):
            conn.close()
            return jsonify({"ok": False, "error": "Teacher authorization failed."}), 403

        conn.execute("UPDATE games SET status='finished' WHERE room=?", (room,))
        conn.commit()
        conn.close()

    return jsonify({"ok": True, "state": public_state(room)})


@app.route("/qr")
def qr_code():
    import qrcode
    room = str(request.args.get("room", "")).strip()
    if not get_game(room):
        return "Game not found", 404

    student_url = f"{base_url()}/?room={room}"
    img = qrcode.make(student_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/export.csv")
def export_csv():
    room = str(request.args.get("room", "")).strip()
    token = str(request.args.get("teacher_token", "")).strip()

    conn = db()
    game = conn.execute("SELECT * FROM games WHERE room=?", (room,)).fetchone()
    game_dict = dict(game) if game else None
    if not require_teacher(game_dict, token):
        conn.close()
        return "Teacher authorization failed.", 403

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Round", "Die Result",
        "# Choosing 1", "# Choosing 2", "# Choosing 3",
        "# Choosing 4", "# Choosing 5", "# Choosing 6",
        "Total Predictions"
    ])

    for r in range(1, game["total_rounds"] + 1):
        preds = [x["choice"] for x in conn.execute(
            "SELECT choice FROM predictions WHERE room=? AND round_no=?",
            (room, r)
        ).fetchall()]
        counts = Counter(preds)
        result_row = conn.execute(
            "SELECT die_result FROM results WHERE room=? AND round_no=?",
            (room, r)
        ).fetchone()
        writer.writerow([
            r,
            result_row["die_result"] if result_row else "",
            counts.get(1, 0), counts.get(2, 0), counts.get(3, 0),
            counts.get(4, 0), counts.get(5, 0), counts.get(6, 0),
            len(preds),
        ])

    writer.writerow([])
    writer.writerow(["Student", "Final Score"])
    for p in conn.execute(
        "SELECT name, score FROM students WHERE room=? "
        "ORDER BY score DESC, name COLLATE NOCASE ASC",
        (room,)
    ).fetchall():
        writer.writerow([p["name"], p["score"]])

    conn.close()

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=stochastic_challenge_{room}.csv"},
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
