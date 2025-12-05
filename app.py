import os
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    send_from_directory,
)

from werkzeug.utils import secure_filename

# -----------------------------------------------------------------------------
# basic setup
# -----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "trades.db"
UPLOAD_FOLDER = BASE_DIR / "static" / "uploads"
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("APP_SECRET_KEY", "dev-secret-key-banu")
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)

# admin credential (bisa di-set di Railway env)
ADMIN_USERNAME = os.environ.get("APP_ADMIN_USER", "banu")
ADMIN_PASSWORD = os.environ.get("APP_ADMIN_PASS", "Banu22")


# -----------------------------------------------------------------------------
# db util
# -----------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT,
            direction TEXT,
            entry_price REAL,
            stop_loss REAL,
            take_profit REAL,
            risk_percent REAL,
            result TEXT,
            grade TEXT,
            strategy_tag TEXT,
            market_condition TEXT,
            status TEXT,
            followed_plan INTEGER DEFAULT 0,
            no_revenge INTEGER DEFAULT 0,
            no_fomo INTEGER DEFAULT 0,
            respected_rr INTEGER DEFAULT 0,
            featured INTEGER DEFAULT 0,
            notes_public TEXT,
            notes_private TEXT,
            screenshot_before TEXT,
            screenshot_after TEXT,
            rr_ratio REAL,
            result_r REAL,
            discipline_score REAL,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    conn.commit()
    conn.close()


init_db()

# -----------------------------------------------------------------------------
# formatting helpers (tampilan angka entry/sl/tp)
# -----------------------------------------------------------------------------
def format_price(value):
    """
    Format angka harga menjadi gaya Indonesia:
    91000      -> 91.000,00
    91000.5    -> 91.000,50
    None / ""  -> "-"
    """
    if value is None or value == "":
        return "-"

    try:
        num = float(value)
    except (TypeError, ValueError):
        # kalau bukan angka, tampilkan apa adanya
        return value

    # 91,000.00 -> 91.000,00
    s = f"{num:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return s


# daftarkan filter ke Jinja
app.jinja_env.filters["price"] = format_price

# -----------------------------------------------------------------------------
# helpers
# -----------------------------------------------------------------------------


def is_logged_in() -> bool:
    return bool(session.get("is_admin"))


def require_login():
    if not is_logged_in():
        return redirect(url_for("login", next=request.path))
    return None


def save_upload(file_storage, prefix: str) -> str | None:
    """
    Simpan file upload ke static/uploads.
    Return relative path "uploads/xxx.png" atau None.
    """
    if not file_storage or file_storage.filename == "":
        return None

    filename = secure_filename(file_storage.filename)
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    final_name = f"{prefix}_{ts}_{filename}"
    target_path = UPLOAD_FOLDER / final_name
    file_storage.save(target_path)

    return f"uploads/{final_name}"


def compute_rr(entry, sl, tp):
    try:
        e = float(entry)
        s = float(sl)
        t = float(tp)
    except (TypeError, ValueError):
        return None, None

    if e == s:
        return None, None

    # risk per unit
    risk = abs(e - s)
    reward = abs(t - e)
    if risk == 0:
        return None, None

    rr = round(reward / risk, 2)
    return rr, risk


def compute_result_r(result_value, rr_ratio):
    """
    Very simple: WIN => +R, LOSE => -1R, BE => 0
    """
    if rr_ratio is None:
        return None

    if result_value == "WIN":
        return rr_ratio
    if result_value == "LOSE":
        return -1.0
    if result_value == "BE":
        return 0.0
    return None


def compute_discipline_score(row: sqlite3.Row):
    checks = [
        row["followed_plan"],
        row["no_revenge"],
        row["no_fomo"],
        row["respected_rr"],
    ]
    total = len(checks)
    if total == 0:
        return None
    score = sum(1 for c in checks if c) / total * 100
    return round(score, 1)


# -----------------------------------------------------------------------------
# auth
# -----------------------------------------------------------------------------


@app.route("/login", methods=["GET", "POST"])
def login():
    next_url = request.args.get("next") or url_for("admin_dashboard")

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(next_url)

        flash("Invalid credentials", "error")

    return render_template(
        "login.html",
        is_public=False,
        is_admin=is_logged_in(),
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("public_root"))


# -----------------------------------------------------------------------------
# public views
# -----------------------------------------------------------------------------


@app.route("/")
def public_root():
    conn = get_db()
    cur = conn.cursor()

    # urut naik supaya equity curve chart kronologis
    cur.execute("SELECT * FROM trades ORDER BY trade_date ASC, id ASC")
    trades = cur.fetchall()
    conn.close()

    # group by status
    planned = [t for t in trades if t["status"] == "PLANNED"]
    active = [t for t in trades if t["status"] == "ACTIVE"]
    closed = [t for t in trades if t["status"] == "CLOSED"]

    # stats
    closed_for_stats = [t for t in closed if t["result"] in ("WIN", "LOSE", "BE")]
    closed_count = len(closed_for_stats)
    win_count = sum(1 for t in closed_for_stats if t["result"] == "WIN")
    win_rate = round(win_count / closed_count * 100, 1) if closed_count else 0.0

    r_values = [t["result_r"] for t in closed_for_stats if t["result_r"] is not None]
    avg_r = round(sum(r_values) / len(r_values), 2) if r_values else 0.0

    discipline_scores = [
        t["discipline_score"] for t in closed_for_stats if t["discipline_score"] is not None
    ]
    disc_avg = round(sum(discipline_scores) / len(discipline_scores), 1) if discipline_scores else 0.0

    # data untuk line chart cumulative R
    chart_labels = []
    chart_values = []
    cumulative_r = 0.0

    for t in closed_for_stats:
        chart_labels.append(t["trade_date"])
        if t["result_r"] is not None:
            cumulative_r += t["result_r"]
        chart_values.append(round(cumulative_r, 2))

    return render_template(
        "public_index.html",
        is_public=True,
        is_admin=is_logged_in(),
        planned=planned,
        active=active,
        closed=closed,
        closed_count=closed_count,
        win_rate=win_rate,
        avg_r=avg_r,
        discipline_score=disc_avg,
        chart_labels=chart_labels,
        chart_values=chart_values,
    )


@app.route("/trade/<int:trade_id>")
def trade_detail(trade_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM trades WHERE id = ?", (trade_id,))
    trade = cur.fetchone()
    conn.close()

    if not trade:
        return redirect(url_for("public_root"))

    return render_template(
        "trade_detail.html",
        trade=trade,
        is_public=True,
        is_admin=is_logged_in(),
    )


# -----------------------------------------------------------------------------
# admin views
# -----------------------------------------------------------------------------


@app.route("/admin")
def admin_dashboard():
    maybe_redirect = require_login()
    if maybe_redirect:
        return maybe_redirect

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM trades ORDER BY trade_date DESC, id DESC")
    trades = cur.fetchall()

    # stats for closed trades only
    closed_for_stats = [t for t in trades if t["status"] == "CLOSED"]
    closed_count = len(closed_for_stats)
    win_count = sum(1 for t in closed_for_stats if t["result"] == "WIN")
    win_rate = round(win_count / closed_count * 100, 1) if closed_count else 0.0

    r_values = [t["result_r"] for t in closed_for_stats if t["result_r"] is not None]
    avg_r = round(sum(r_values) / len(r_values), 2) if r_values else 0.0

    discipline_scores = [
        t["discipline_score"]
        for t in closed_for_stats
        if t["discipline_score"] is not None
    ]
    disc_avg = round(sum(discipline_scores) / len(discipline_scores), 1) if discipline_scores else 0.0

    # status counts
    planned_count = sum(1 for t in trades if t["status"] == "PLANNED")
    active_count = sum(1 for t in trades if t["status"] == "ACTIVE")

    conn.close()

    return render_template(
        "index.html",
        trades=trades,
        is_public=False,
        is_admin=True,
        planned_count=planned_count,
        active_count=active_count,
        closed_count=closed_count,
        win_rate=win_rate,
        avg_r=avg_r,
        discipline_score=disc_avg,
    )


@app.route("/admin/new", methods=["GET", "POST"])
def new_trade():
    maybe_redirect = require_login()
    if maybe_redirect:
        return maybe_redirect

    today = datetime.utcnow().strftime("%Y-%m-%d")

    if request.method == "POST":
        form = request.form

        trade_date = form.get("trade_date") or today
        symbol = form.get("symbol", "").upper()
        timeframe = form.get("timeframe")
        direction = form.get("direction")
        entry_price = form.get("entry_price")
        stop_loss = form.get("stop_loss")
        take_profit = form.get("take_profit")
        risk_percent = form.get("risk_percent")
        result = form.get("result")
        grade = form.get("grade")
        strategy_tag = form.get("strategy_tag")
        market_condition = form.get("market_condition")
        status = form.get("status", "PLANNED")

        followed_plan = 1 if form.get("followed_plan") else 0
        no_revenge = 1 if form.get("no_revenge") else 0
        no_fomo = 1 if form.get("no_fomo") else 0
        respected_rr = 1 if form.get("respected_rr") else 0
        featured = 1 if form.get("featured") else 0

        notes_public = form.get("notes_public")
        notes_private = form.get("notes_private")

        before_file = request.files.get("screenshot_before")
        after_file = request.files.get("screenshot_after")

        screenshot_before = save_upload(before_file, "before") if before_file else None
        screenshot_after = save_upload(after_file, "after") if after_file else None

        rr_ratio, _ = compute_rr(entry_price, stop_loss, take_profit)
        result_r = compute_result_r(result, rr_ratio)

        discipline_score = None
        checks = [followed_plan, no_revenge, no_fomo, respected_rr]
        if any(checks):
            discipline_score = round(sum(checks) / len(checks) * 100, 1)

        now_iso = datetime.utcnow().isoformat()

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO trades (
                trade_date, symbol, timeframe, direction,
                entry_price, stop_loss, take_profit,
                risk_percent, result, grade,
                strategy_tag, market_condition, status,
                followed_plan, no_revenge, no_fomo, respected_rr,
                featured, notes_public, notes_private,
                screenshot_before, screenshot_after,
                rr_ratio, result_r, discipline_score,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                trade_date,
                symbol,
                timeframe,
                direction,
                entry_price or None,
                stop_loss or None,
                take_profit or None,
                risk_percent or None,
                result,
                grade,
                strategy_tag,
                market_condition,
                status,
                followed_plan,
                no_revenge,
                no_fomo,
                respected_rr,
                featured,
                notes_public,
                notes_private,
                screenshot_before,
                screenshot_after,
                rr_ratio,
                result_r,
                discipline_score,
                now_iso,
                now_iso,
            ),
        )
        conn.commit()
        conn.close()

        return redirect(url_for("admin_dashboard"))

    return render_template(
        "new_trade.html",
        today=today,
        is_public=False,
        is_admin=True,
    )


@app.route("/admin/edit/<int:trade_id>", methods=["GET", "POST"])
def edit_trade(trade_id: int):
    maybe_redirect = require_login()
    if maybe_redirect:
        return maybe_redirect

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM trades WHERE id = ?", (trade_id,))
    trade = cur.fetchone()

    if not trade:
        conn.close()
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        form = request.form

        trade_date = form.get("trade_date") or trade["trade_date"]
        symbol = form.get("symbol", "").upper()
        timeframe = form.get("timeframe")
        direction = form.get("direction")
        entry_price = form.get("entry_price")
        stop_loss = form.get("stop_loss")
        take_profit = form.get("take_profit")
        risk_percent = form.get("risk_percent")
        result = form.get("result")
        grade = form.get("grade")
        strategy_tag = form.get("strategy_tag")
        market_condition = form.get("market_condition")
        status = form.get("status", "PLANNED")

        followed_plan = 1 if form.get("followed_plan") else 0
        no_revenge = 1 if form.get("no_revenge") else 0
        no_fomo = 1 if form.get("no_fomo") else 0
        respected_rr = 1 if form.get("respected_rr") else 0
        featured = 1 if form.get("featured") else 0

        notes_public = form.get("notes_public")
        notes_private = form.get("notes_private")

        before_file = request.files.get("screenshot_before")
        after_file = request.files.get("screenshot_after")

        screenshot_before = trade["screenshot_before"]
        screenshot_after = trade["screenshot_after"]

        if before_file and before_file.filename:
            screenshot_before = save_upload(before_file, "before")

        if after_file and after_file.filename:
            screenshot_after = save_upload(after_file, "after")

        rr_ratio, _ = compute_rr(entry_price, stop_loss, take_profit)
        result_r = compute_result_r(result, rr_ratio)

        discipline_score = None
        checks = [followed_plan, no_revenge, no_fomo, respected_rr]
        if any(checks):
            discipline_score = round(sum(checks) / len(checks) * 100, 1)

        now_iso = datetime.utcnow().isoformat()

        cur.execute(
            """
            UPDATE trades
            SET trade_date=?, symbol=?, timeframe=?, direction=?,
                entry_price=?, stop_loss=?, take_profit=?,
                risk_percent=?, result=?, grade=?,
                strategy_tag=?, market_condition=?, status=?,
                followed_plan=?, no_revenge=?, no_fomo=?, respected_rr=?,
                featured=?, notes_public=?, notes_private=?,
                screenshot_before=?, screenshot_after=?,
                rr_ratio=?, result_r=?, discipline_score=?,
                updated_at=?
            WHERE id=?
            """,
            (
                trade_date,
                symbol,
                timeframe,
                direction,
                entry_price or None,
                stop_loss or None,
                take_profit or None,
                risk_percent or None,
                result,
                grade,
                strategy_tag,
                market_condition,
                status,
                followed_plan,
                no_revenge,
                no_fomo,
                respected_rr,
                featured,
                notes_public,
                notes_private,
                screenshot_before,
                screenshot_after,
                rr_ratio,
                result_r,
                discipline_score,
                now_iso,
                trade_id,
            ),
        )
        conn.commit()
        conn.close()

        return redirect(url_for("admin_dashboard"))

    conn.close()
    return render_template(
        "edit_trade.html",
        trade=trade,
        is_public=False,
        is_admin=True,
    )


@app.route("/admin/delete/<int:trade_id>", methods=["POST"])
def delete_trade(trade_id: int):
    maybe_redirect = require_login()
    if maybe_redirect:
        return maybe_redirect

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
    conn.commit()
    conn.close()

    return redirect(url_for("admin_dashboard"))


# -----------------------------------------------------------------------------
# static uploads (for local dev; in prod biasanya langsung dilayani web server)
# -----------------------------------------------------------------------------


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


# -----------------------------------------------------------------------------
# main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)
