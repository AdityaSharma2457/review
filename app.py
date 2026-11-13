import base64
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from io import BytesIO
from pathlib import Path

import qrcode
from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shops (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    public_token TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS review_templates (
    id INTEGER PRIMARY KEY,
    shop_id INTEGER NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    used_at TEXT
);
CREATE TABLE IF NOT EXISTS demo_reviews (
    id INTEGER PRIMARY KEY,
    shop_id INTEGER NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    template_id INTEGER NOT NULL UNIQUE REFERENCES review_templates(id),
    public_token TEXT NOT NULL UNIQUE,
    review_text TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    status TEXT NOT NULL CHECK (status IN ('selected', 'published')),
    created_at TEXT NOT NULL,
    published_at TEXT
);
"""


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        DATABASE=os.environ.get(
            "REVIEW_DEMO_DATABASE",
            str(Path(app.instance_path) / "review_demo.sqlite3"),
        ),
    )
    if test_config:
        app.config.update(test_config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(app.config["DATABASE"])
    try:
        connection.executescript(SCHEMA)
    finally:
        connection.close()

    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
        return g.db

    @app.teardown_appcontext
    def close_db(_error=None):
        connection = g.pop("db", None)
        if connection is not None:
            connection.close()

    @app.context_processor
    def csrf_context():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return {"csrf_token": session["csrf_token"]}

    @app.before_request
    def protect_post_requests():
        if request.method == "POST":
            submitted = request.form.get("csrf_token", "")
            expected = session.get("csrf_token", "")
            if not expected or not hmac.compare_digest(submitted, expected):
                abort(400, description="Invalid form token. Reload the page and try again.")

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            return view(*args, **kwargs)

        return wrapped

    def current_shop():
        return get_db().execute(
            "SELECT id, name, public_token FROM shops WHERE user_id = ?",
            (session["user_id"],),
        ).fetchone()

    @app.route("/")
    def index():
        if "user_id" in session:
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            username = request.form.get("username", "").strip().lower()
            password = request.form.get("password", "")
            shop_name = request.form.get("shop_name", "").strip()
            if not username or len(username) > 80 or not shop_name or len(shop_name) > 120:
                flash("Enter a username and shop name within the allowed length.")
            elif len(password) < 8:
                flash("Use a password with at least 8 characters.")
            else:
                connection = get_db()
                try:
                    cursor = connection.execute(
                        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                        (username, generate_password_hash(password)),
                    )
                    connection.execute(
                        "INSERT INTO shops (user_id, name, public_token) VALUES (?, ?, ?)",
                        (cursor.lastrowid, shop_name, secrets.token_urlsafe(24)),
                    )
                    connection.commit()
                except sqlite3.IntegrityError:
                    connection.rollback()
                    flash("That username is already registered.")
                else:
                    session.clear()
                    session["user_id"] = cursor.lastrowid
                    flash("Your demo shop is ready.")
                    return redirect(url_for("dashboard"))
        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip().lower()
            user = get_db().execute(
                "SELECT id, password_hash FROM users WHERE username = ?", (username,)
            ).fetchone()
            if user is None or not check_password_hash(
                user["password_hash"], request.form.get("password", "")
            ):
                flash("Username or password is incorrect.")
            else:
                session.clear()
                session["user_id"] = user["id"]
                return redirect(url_for("dashboard"))
        return render_template("login.html")

    @app.post("/logout")
    @login_required
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/dashboard", methods=["GET", "POST"])
    @login_required
    def dashboard():
        connection = get_db()
        shop = current_shop()
        if shop is None:
            abort(404)
        if request.method == "POST":
            text = request.form.get("review_text", "").strip()
            if not text or len(text) > 1000:
                flash("Enter review text (up to 1,000 characters).")
            else:
                connection.execute(
                    "INSERT INTO review_templates (shop_id, text) VALUES (?, ?)",
                    (shop["id"], text),
                )
                connection.commit()
                flash("Demo text added.")
                return redirect(url_for("dashboard"))

        templates = connection.execute(
            "SELECT id, text, used_at FROM review_templates WHERE shop_id = ? ORDER BY id DESC",
            (shop["id"],),
        ).fetchall()
        customer_url = url_for(
            "customer", public_token=shop["public_token"], _external=True
        )
        qr = qrcode.make(customer_url)
        buffer = BytesIO()
        qr.save(buffer, format="PNG")
        qr_data = base64.b64encode(buffer.getvalue()).decode("ascii")
        return render_template(
            "dashboard.html",
            shop=shop,
            templates=templates,
            customer_url=customer_url,
            qr_data=qr_data,
        )

    @app.get("/customer/<public_token>")
    def customer(public_token):
        shop = get_db().execute(
            "SELECT id, name FROM shops WHERE public_token = ?", (public_token,)
        ).fetchone()
        if shop is None:
            abort(404)
        choices = get_db().execute(
            """SELECT id, text FROM review_templates
               WHERE shop_id = ? AND used_at IS NULL
               ORDER BY RANDOM() LIMIT 5""",
            (shop["id"],),
        ).fetchall()
        return render_template(
            "customer.html",
            shop=shop,
            choices=choices,
            public_token=public_token,
        )

    @app.post("/customer/<public_token>/select")
    def select_review(public_token):
        connection = get_db()
        shop = connection.execute(
            "SELECT id FROM shops WHERE public_token = ?", (public_token,)
        ).fetchone()
        if shop is None:
            abort(404)
        review_id = request.form.get("review_id", type=int)
        rating = request.form.get("rating", type=int)
        if review_id is None or rating is None or not 1 <= rating <= 5:
            abort(400, description="Choose one review and a rating from 1 to 5.")

        connection.execute("BEGIN IMMEDIATE")
        template = connection.execute(
            """SELECT id, text FROM review_templates
               WHERE id = ? AND shop_id = ? AND used_at IS NULL""",
            (review_id, shop["id"]),
        ).fetchone()
        if template is None:
            connection.rollback()
            flash("That demo review is no longer available. Choose another.")
            return redirect(url_for("customer", public_token=public_token))

        now = datetime.now(timezone.utc).isoformat()
        updated = connection.execute(
            "UPDATE review_templates SET used_at = ? WHERE id = ? AND used_at IS NULL",
            (now, review_id),
        )
        if updated.rowcount != 1:
            connection.rollback()
            flash("That demo review was just used. Choose another.")
            return redirect(url_for("customer", public_token=public_token))
        cursor = connection.execute(
            """INSERT INTO demo_reviews
               (shop_id, template_id, public_token, review_text, rating, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'selected', ?)""",
            (
                shop["id"],
                template["id"],
                secrets.token_urlsafe(24),
                template["text"],
                rating,
                now,
            ),
        )
        connection.commit()
        token = connection.execute(
            "SELECT public_token FROM demo_reviews WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()["public_token"]
        return redirect(url_for("mock_publish", public_token=token))

    @app.route("/demo/<public_token>", methods=["GET", "POST"])
    def mock_publish(public_token):
        connection = get_db()
        demo_review = connection.execute(
            """SELECT demo_reviews.*, shops.name AS shop_name
               FROM demo_reviews JOIN shops ON shops.id = demo_reviews.shop_id
               WHERE demo_reviews.public_token = ?""",
            (public_token,),
        ).fetchone()
        if demo_review is None:
            abort(404)
        if request.method == "POST" and demo_review["status"] == "selected":
            connection.execute(
                """UPDATE demo_reviews SET status = 'published', published_at = ?
                   WHERE public_token = ? AND status = 'selected'""",
                (datetime.now(timezone.utc).isoformat(), public_token),
            )
            connection.commit()
            return redirect(url_for("mock_publish", public_token=public_token))
        return render_template("mock_publish.html", demo_review=demo_review)

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
