import os
import sqlite3
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, abort, session, make_response
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# ======================
# CONFIG
# ======================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "trades.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB
app.secret_key = "SUPER_SECRET_KEY_BANU"

# ADMIN LOGIN (sederhana)
ADMIN_USERNAME = "banu"
ADMIN_PASSWORD_HASH = generate_password_hash("superadmin123")

# Deskripsi strategy tag (untuk public view playbook)
STRATEGY_INFO = {
    "SND": "Supply & demand continuation after liquidity sweep.",
    "MR": "Mean reversion after extended move away from value.",
    "BO": "Breakout & retest strategy with structural confirmation.",
    "SWING": "Swing trading based on higher timeframe structures.",
    "INTRA": "Intraday momentum within specific trading sessions.",
}

# ======================
# DB HELPER
# ======================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT,
            symbol TEXT,
            timeframe TEXT,
            direction TEXT,
            entry_price REAL,
            stop_loss REAL,
            take_profit REAL,
            result TEXT,
            grade TEXT,
            strategy_tag TEXT,
            market_condition TEXT,
            risk_percent REAL,
            rr_ratio REAL,
            realized_r REAL,
            status TEXT,
            followed_plan INTEGER,
            no_revenge INTEGER,
            no_fomo INTEGER,
            respected_rr INTEGER,
            featured INTEGER,
            notes_public TEXT,
            notes_private TEXT,
            screenshot_before_filename TEXT,
            screenshot_after_filename TEXT,
            created_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()


init_db()

# ======================
# AUTH HELPERS
# ======================

def is_admin():
    return bool(session.get("is_admin"))


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not is_admin():
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


# ======================
# RISK & R MULTIPLE
# ======================

def compute_rr_and_realized(direction, entry, sl, tp, result):
    """
    Hitung R:R theoretical (rr_ratio) dan realized R (realized_r) berdasarkan result.
    """
    try:
        if entry is None or sl is None or tp is None:
            return None, None

        direction = (direction or "").upper()
        result = (result or "").upper()
        if direction not in ("BUY", "SELL"):
            return None, None

        if direction == "BUY":
            risk = entry - sl
            reward = tp - entry
        else:  # SELL
            risk = sl - entry
            reward = entry - tp

        if risk <= 0:
            return None, None

        rr = reward / risk

        if result == "WIN":
            realized_r = rr
        elif result == "LOSE":
            realized_r = -1.0
        else:
            realized_r = None

        return round(rr, 2), realized_r
    except Exception:
        return None, None


# ======================
# DASHBOARD HELPERS
# ======================

def _load_trades_for_dashboard():
    conn = get_db()
    trades = conn.execute(
        "SELECT * FROM trades ORDER BY datetime(trade_date) ASC, id ASC"
    ).fetchall()
    conn.close()
    return trades


def _get_unique_strategies(trades):
    return sorted(
        {
            (t["strategy_tag"] or "").strip()
            for t in trades
            if (t["strategy_tag"] or "").strip()
        }
    )


def _build_dashboard_stats(trades):
    closed = [t for t in trades if (t["result"] or "")]
    total = len(closed)
    wins = len([t for t in closed if (t["result"] or "").upper() == "WIN"])
    loses = len([t for t in closed if (t["result"] or "").upper() == "LOSE"])
    win_rate = round((wins / total) * 100, 1) if total > 0 else 0.0

    rr_list = [t["rr_ratio"] for t in closed if t["rr_ratio"] is not None]
    realized_list = [t["realized_r"] for t in closed if t["realized_r"] is not None]
    risk_list = [t["risk_percent"] for t in closed if t["risk_percent"] is not None]

    avg_rr = round(sum(rr_list) / len(rr_list), 2) if rr_list else 0.0
    avg_realized_r = round(sum(realized_list) / len(realized_list), 2) if realized_list else 0.0
    avg_risk = round(sum(risk_list) / len(risk_list), 2) if risk_list else 0.0
    max_risk = round(max(risk_list), 2) if risk_list else 0.0

    # equity & drawdown
    equity_points = []
    labels = []
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for t in closed:
        r = t["realized_r"] if t["realized_r"] is not None else 0.0
        cumulative += r
        equity_points.append(round(cumulative, 2))
        labels.append(f"{t['trade_date']} {t['symbol']} {t['direction']}")
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_drawdown:
            max_drawdown = dd

    max_drawdown = round(max_drawdown, 2)

    # timeframe stats
    tf_stats = {}
    for t in closed:
        tf = (t["timeframe"] or "").strip()
        if not tf:
            continue
        if tf not in tf_stats:
            tf_stats[tf] = {"count": 0, "wins": 0, "loses": 0, "r_list": []}
        tf_stats[tf]["count"] += 1
        if (t["result"] or "").upper() == "WIN":
            tf_stats[tf]["wins"] += 1
        elif (t["result"] or "").upper() == "LOSE":
            tf_stats[tf]["loses"] += 1
        if t["realized_r"] is not None:
            tf_stats[tf]["r_list"].append(t["realized_r"])

    for tf, data in tf_stats.items():
        if data["r_list"]:
            data["avg_r"] = round(sum(data["r_list"]) / len(data["r_list"]), 2)
        else:
            data["avg_r"] = 0.0
        data["win_rate"] = round(
            (data["wins"] / data["count"]) * 100, 1
        ) if data["count"] > 0 else 0.0

    # strategy stats
    strategy_stats = {}
    for t in closed:
        tag = (t["strategy_tag"] or "").strip()
        if not tag:
            continue
        if tag not in strategy_stats:
            strategy_stats[tag] = {"count": 0, "wins": 0, "loses": 0}
        strategy_stats[tag]["count"] += 1
        if (t["result"] or "").upper() == "WIN":
            strategy_stats[tag]["wins"] += 1
        elif (t["result"] or "").upper() == "LOSE":
            strategy_stats[tag]["loses"] += 1

    # discipline score
    disciplined = 0
    for t in closed:
        if (
            t["followed_plan"] == 1
            and t["no_revenge"] == 1
            and t["no_fomo"] == 1
            and t["respected_rr"] == 1
        ):
            disciplined += 1
    discipline_score = round((disciplined / total) * 100, 1) if total > 0 else 0.0

    return {
        "total": total,
        "wins": wins,
        "loses": loses,
        "win_rate": win_rate,
        "avg_rr": avg_rr,
        "avg_realized_r": avg_realized_r,
        "avg_risk": avg_risk,
        "max_risk": max_risk,
        "max_drawdown": max_drawdown,
        "discipline_score": discipline_score,
        "equity_labels": labels,
        "equity_points": equity_points,
        "tf_stats": tf_stats,
        "strategy_stats": strategy_stats,
    }


def _filter_trades(trades, status=None, direction=None, strategy=None, symbol_query=None):
    result = trades
    if status and status != "ALL":
        result = [t for t in result if (t["status"] or "").upper() == status.upper()]
    if direction and direction != "ALL":
        result = [t for t in result if (t["direction"] or "").upper() == direction.upper()]
    if strategy and strategy != "ALL":
        result = [t for t in result if (t["strategy_tag"] or "").upper() == strategy.upper()]
    if symbol_query:
        q = symbol_query.lower()
        result = [t for t in result if q in (t["symbol"] or "").lower()]
    return result


# ======================
# AUTH ROUTES
# ======================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        next_url = request.form.get("next") or url_for("index")

        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session["is_admin"] = True
            return redirect(next_url)

        return render_template("login.html", error="Invalid username or password", next=next_url)

    next_url = request.args.get("next") or url_for("index")
    return render_template("login.html", next=next_url)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ======================
# OWNER DASHBOARD
# ======================

@app.route("/")
def index():
    trades = _load_trades_for_dashboard()
    stats = _build_dashboard_stats(trades)
    unique_strategies = _get_unique_strategies(trades)

    featured = [t for t in trades if t["featured"] == 1]
    featured = list(reversed(featured))[-3:] if featured else []

    trades_desc = list(reversed(trades))

    planned_count = len([t for t in trades if (t["status"] or "").upper() == "PLANNED"])
    active_count = len([t for t in trades if (t["status"] or "").upper() == "ACTIVE"])
    closed_count = len([t for t in trades if (t["status"] or "").upper() == "CLOSED"])

    return render_template(
        "index.html",
        trades=trades_desc,
        featured=featured,
        stats=stats,
        unique_strategies=unique_strategies,
        strategy_info=STRATEGY_INFO,
        planned_count=planned_count,
        active_count=active_count,
        closed_count=closed_count,
        is_admin=is_admin(),
        is_public=False,
    )


# ======================
# PUBLIC VIEW
# ======================

@app.route("/public")
def public_view():
    trades = _load_trades_for_dashboard()
    stats = _build_dashboard_stats(trades)
    unique_strategies = _get_unique_strategies(trades)

    status = request.args.get("status", "ALL")
    direction = request.args.get("direction", "ALL")
    strategy = request.args.get("strategy", "ALL")
    symbol_query = request.args.get("symbol", "").strip()

    filtered = _filter_trades(trades, status, direction, strategy, symbol_query)
    filtered_desc = list(reversed(filtered))

    planned_count = len([t for t in trades if (t["status"] or "").upper() == "PLANNED"])
    active_count = len([t for t in trades if (t["status"] or "").upper() == "ACTIVE"])
    closed_count = len([t for t in trades if (t["status"] or "").upper() == "CLOSED"])

    featured = [t for t in trades if t["featured"] == 1]
    featured = list(reversed(featured))[-3:] if featured else []

    used_strategies = sorted({
        (t["strategy_tag"] or "").upper()
        for t in trades
        if (t["strategy_tag"] or "").strip()
    })
    playbook = []
    for tag in used_strategies:
        desc = STRATEGY_INFO.get(tag, "No description yet – used as tag in my trades.")
        playbook.append({"tag": tag, "description": desc})

    return render_template(
        "public_index.html",
        trades=filtered_desc,
        featured=featured,
        stats=stats,
        unique_strategies=unique_strategies,
        playbook=playbook,
        filter_status=status,
        filter_direction=direction,
        filter_strategy=strategy,
        filter_symbol=symbol_query,
        planned_count=planned_count,
        active_count=active_count,
        closed_count=closed_count,
        is_public=True,
        is_admin=is_admin(),
    )


# ======================
# EXPORT CSV (closed trades)
# ======================

@app.route("/public/export/csv")
def export_closed_csv():
    trades = _load_trades_for_dashboard()
    closed = [t for t in trades if (t["result"] or "")]

    header = [
        "trade_date", "symbol", "timeframe", "direction",
        "entry_price", "stop_loss", "take_profit",
        "result", "grade", "strategy_tag", "status",
        "risk_percent", "rr_ratio", "realized_r"
    ]
    lines = [",".join(header)]

    for t in closed:
        row = [
            t["trade_date"] or "",
            t["symbol"] or "",
            t["timeframe"] or "",
            t["direction"] or "",
            str(t["entry_price"] or ""),
            str(t["stop_loss"] or ""),
            str(t["take_profit"] or ""),
            t["result"] or "",
            t["grade"] or "",
            t["strategy_tag"] or "",
            t["status"] or "",
            str(t["risk_percent"] or ""),
            str(t["rr_ratio"] or ""),
            str(t["realized_r"] or ""),
        ]
        lines.append(",".join(row))

    csv_data = "\n".join(lines)
    resp = make_response(csv_data)
    resp.headers["Content-Type"] = "text/csv"
    resp.headers["Content-Disposition"] = "attachment; filename=trades_closed.csv"
    return resp


# ======================
# TRADE DETAIL
# ======================

@app.route("/trade/<int:trade_id>")
def trade_detail(trade_id):
    conn = get_db()
    trade = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    conn.close()
    if trade is None:
        abort(404)

    direction = (trade["direction"] or "").upper()
    status = (trade["status"] or "").upper()
    result = (trade["result"] or "").upper()

    return render_template(
        "trade_detail.html",
        trade=trade,
        direction=direction,
        status=status,
        result=result,
        strategy_info=STRATEGY_INFO,
        is_admin=is_admin(),
        is_public=False,
    )


# ======================
# ADMIN: NEW TRADE
# ======================

@app.route("/admin/new", methods=["GET", "POST"])
@login_required
def new_trade():
    if request.method == "POST":
        f = request.form

        trade_date = f.get("trade_date") or datetime.utcnow().strftime("%Y-%m-%d")
        symbol = f.get("symbol")
        timeframe = f.get("timeframe")
        direction = f.get("direction")
        result = f.get("result")
        grade = f.get("grade")
        strategy_tag = f.get("strategy_tag")
        market_condition = f.get("market_condition")
        status = f.get("status")

        entry_str = f.get("entry_price")
        sl_str = f.get("stop_loss")
        tp_str = f.get("take_profit")
        risk_str = f.get("risk_percent")

        entry_val = float(entry_str) if entry_str else None
        sl_val = float(sl_str) if sl_str else None
        tp_val = float(tp_str) if tp_str else None
        risk_val = float(risk_str) if risk_str else None

        rr_ratio, realized_r = compute_rr_and_realized(
            direction, entry_val, sl_val, tp_val, result
        )

        followed_plan = 1 if f.get("followed_plan") == "on" else 0
        no_revenge = 1 if f.get("no_revenge") == "on" else 0
        no_fomo = 1 if f.get("no_fomo") == "on" else 0
        respected_rr = 1 if f.get("respected_rr") == "on" else 0
        featured = 1 if f.get("featured") == "on" else 0

        notes_public = f.get("notes_public")
        notes_private = f.get("notes_private")

        file_before = request.files.get("screenshot_before")
        file_after = request.files.get("screenshot_after")
        before_name = None
        after_name = None

        if file_before and file_before.filename:
            before_name = datetime.utcnow().strftime("%Y%m%d%H%M%S_before_") + secure_filename(file_before.filename)
            file_before.save(os.path.join(app.config["UPLOAD_FOLDER"], before_name))

        if file_after and file_after.filename:
            after_name = datetime.utcnow().strftime("%Y%m%d%H%M%S_after_") + secure_filename(file_after.filename)
            file_after.save(os.path.join(app.config["UPLOAD_FOLDER"], after_name))

        conn = get_db()
        conn.execute(
            """
            INSERT INTO trades (
                trade_date, symbol, timeframe, direction,
                entry_price, stop_loss, take_profit,
                result, grade, strategy_tag, market_condition,
                risk_percent, rr_ratio, realized_r,
                status, followed_plan, no_revenge, no_fomo, respected_rr,
                featured, notes_public, notes_private,
                screenshot_before_filename, screenshot_after_filename,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_date, symbol, timeframe, direction,
                entry_val, sl_val, tp_val,
                result, grade, strategy_tag, market_condition,
                risk_val, rr_ratio, realized_r,
                status, followed_plan, no_revenge, no_fomo, respected_rr,
                featured, notes_public, notes_private,
                before_name, after_name,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
        conn.close()

        return redirect(url_for("index"))

    today = datetime.utcnow().strftime("%Y-%m-%d")
    return render_template("new_trade.html", today=today, is_admin=is_admin(), is_public=False)


# ======================
# ADMIN: EDIT TRADE
# ======================

@app.route("/admin/edit/<int:trade_id>", methods=["GET", "POST"])
@login_required
def edit_trade(trade_id):
    conn = get_db()
    trade = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    if trade is None:
        conn.close()
        abort(404)

    if request.method == "POST":
        f = request.form

        trade_date = f.get("trade_date") or trade["trade_date"]
        symbol = f.get("symbol")
        timeframe = f.get("timeframe")
        direction = f.get("direction")
        result = f.get("result")
        grade = f.get("grade")
        strategy_tag = f.get("strategy_tag")
        market_condition = f.get("market_condition")
        status = f.get("status")

        entry_str = f.get("entry_price")
        sl_str = f.get("stop_loss")
        tp_str = f.get("take_profit")
        risk_str = f.get("risk_percent")

        entry_val = float(entry_str) if entry_str else None
        sl_val = float(sl_str) if sl_str else None
        tp_val = float(tp_str) if tp_str else None
        risk_val = float(risk_str) if risk_str else None

        rr_ratio, realized_r = compute_rr_and_realized(
            direction, entry_val, sl_val, tp_val, result
        )

        followed_plan = 1 if f.get("followed_plan") == "on" else 0
        no_revenge = 1 if f.get("no_revenge") == "on" else 0
        no_fomo = 1 if f.get("no_fomo") == "on" else 0
        respected_rr = 1 if f.get("respected_rr") == "on" else 0
        featured = 1 if f.get("featured") == "on" else 0

        notes_public = f.get("notes_public")
        notes_private = f.get("notes_private")

        before_name = trade["screenshot_before_filename"]
        after_name = trade["screenshot_after_filename"]

        file_before = request.files.get("screenshot_before")
        file_after = request.files.get("screenshot_after")

        if file_before and file_before.filename:
            before_name = datetime.utcnow().strftime("%Y%m%d%H%M%S_before_") + secure_filename(file_before.filename)
            file_before.save(os.path.join(app.config["UPLOAD_FOLDER"], before_name))

        if file_after and file_after.filename:
            after_name = datetime.utcnow().strftime("%Y%m%d%H%M%S_after_") + secure_filename(file_after.filename)
            file_after.save(os.path.join(app.config["UPLOAD_FOLDER"], after_name))

        conn.execute(
            """
            UPDATE trades
            SET trade_date = ?, symbol = ?, timeframe = ?, direction = ?,
                entry_price = ?, stop_loss = ?, take_profit = ?,
                result = ?, grade = ?, strategy_tag = ?, market_condition = ?,
                risk_percent = ?, rr_ratio = ?, realized_r = ?,
                status = ?, followed_plan = ?, no_revenge = ?, no_fomo = ?, respected_rr = ?,
                featured = ?, notes_public = ?, notes_private = ?,
                screenshot_before_filename = ?, screenshot_after_filename = ?
            WHERE id = ?
            """,
            (
                trade_date, symbol, timeframe, direction,
                entry_val, sl_val, tp_val,
                result, grade, strategy_tag, market_condition,
                risk_val, rr_ratio, realized_r,
                status, followed_plan, no_revenge, no_fomo, respected_rr,
                featured, notes_public, notes_private,
                before_name, after_name,
                trade_id,
            ),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("trade_detail", trade_id=trade_id))

    conn.close()
    return render_template("edit_trade.html", trade=trade, is_admin=is_admin(), is_public=False)


# ======================
# ADMIN: DELETE TRADE
# ======================

@app.route("/admin/delete/<int:trade_id>", methods=["POST"])
@login_required
def delete_trade(trade_id):
    conn = get_db()
    trade = conn.execute(
        "SELECT screenshot_before_filename, screenshot_after_filename FROM trades WHERE id = ?",
        (trade_id,),
    ).fetchone()

    if trade:
        for fname in [trade["screenshot_before_filename"], trade["screenshot_after_filename"]]:
            if fname:
                path = os.path.join(app.config["UPLOAD_FOLDER"], fname)
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except OSError:
                    pass

        conn.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
        conn.commit()

    conn.close()
    return redirect(url_for("index"))


# ======================
# MAIN (LOCAL DEV)
# ======================

if __name__ == "__main__":
    # Untuk lokal: python app.py
    app.run(debug=True)
