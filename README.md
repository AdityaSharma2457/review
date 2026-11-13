# Review Flow College Demo

A small Flask and SQLite prototype for demonstrating shop setup, QR codes, sample-review selection, star ratings, and a simulated publish step.

**This app is local-only.** After a customer chooses sample text and a rating, the mock destination automatically saves the result to this app's SQLite database after a short progress animation. It does not contact Google, any other review platform, or a browser automation service. A manual button is also available if JavaScript is disabled. Sample review text and the simulated publish result are not real customer reviews.

## Run locally

Requires Python 3.10 or later.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000>, create a demo account and shop, then add sample text and scan/open the QR code. The default SQLite database is created at `instance/review_demo.sqlite3`. Set `REVIEW_DEMO_DATABASE` to use a different local database path.

## Test

```powershell
python -m unittest discover -s tests -v
```

The app demonstrates tenant scoping in a shared database: shop-owned records are queried by `shop_id`. The built-in Flask server and generated development secret are for local coursework demonstrations only, not production deployment.
