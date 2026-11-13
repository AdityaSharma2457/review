# Review Flow College Demo

A Flask and SQLite college project for shop accounts, QR codes, Google review links, and a separate local review-picker demonstration.

Shopkeepers enter their Google Place ID when registering; the customer QR page links directly to that shop's Google review page, where customers write and submit their own reviews. Separately, the dashboard has a sample-text library and local classroom demo picker. That isolated demo lets a visitor select one of up to five unused examples and a rating, then records the result locally and marks the example as used. The sample text picker is not part of the customer-to-Google flow and never submits anything to Google or another review platform.

## Run locally

Requires Python 3.10 or later.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000>, create a shop account with its Google Place ID, then scan or open the customer QR code from the dashboard. Use the dashboard's separate **Preview local demo** link to try the sample picker. Use Google's [Place ID Finder](https://developers.google.com/maps/documentation/javascript/examples/places-placeid-finder) if you need to look up the ID. Existing databases are migrated to add the Place ID field and demo tables; existing shopkeepers can update their Place ID on the dashboard. The default SQLite database is created at `instance/review_demo.sqlite3`. Set `REVIEW_DEMO_DATABASE` to use a different local database path.

## Test

```powershell
python -m unittest discover -s tests -v
```

The app demonstrates tenant scoping in a shared database. The built-in Flask server and generated development secret are for local coursework demonstrations only, not production deployment.
