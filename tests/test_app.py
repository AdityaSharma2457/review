import os
import re
import sqlite3
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

from app import create_app


class ReviewFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.sqlite3")
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-key",
                "DATABASE": self.db_path,
            }
        )
        self.client = self.app.test_client()
        self.client.get("/register")

    def tearDown(self):
        self.temp_dir.cleanup()

    def token(self):
        with self.client.session_transaction() as session:
            token = session.get("csrf_token")
        if token is None:
            self.client.get("/register")
            with self.client.session_transaction() as session:
                token = session["csrf_token"]
        return token

    def register(self, username, shop_name, place_id="ChIJ_demoPlaceId"):
        return self.client.post(
            "/register",
            data={
                "csrf_token": self.token(),
                "username": username,
                "password": "college-demo-password",
                "shop_name": shop_name,
                "place_id": place_id,
            },
            follow_redirects=True,
        )

    def add_demo_review(self, text):
        return self.client.post(
            "/dashboard",
            data={
                "csrf_token": self.token(),
                "action": "add_review",
                "review_text": text,
            },
            follow_redirects=True,
        )

    def customer_path(self, page):
        match = re.search(rb'href="(http://localhost/customer/[^"]+)"', page.data)
        self.assertIsNotNone(match)
        return match.group(1).decode().replace("http://localhost", "")

    def test_customer_review_link_uses_shop_place_id(self):
        self.register("owner", "Demo Cafe", "ChIJ_demoPlaceId-123")
        dashboard = self.client.get("/dashboard")
        self.assertIn(b"ChIJ_demoPlaceId-123", dashboard.data)
        customer_path = self.customer_path(dashboard)
        customer = self.client.get(customer_path)
        self.assertIn(b"Continue to Google Reviews", customer.data)
        self.assertIn(b"write and submit your review yourself", customer.data)
        self.assertNotIn(b"Sample text", customer.data)

        google_response = self.client.get(customer_path + "/google")
        self.assertEqual(google_response.status_code, 302)
        destination = urlparse(google_response.headers["Location"])
        self.assertEqual(destination.netloc, "search.google.com")
        self.assertEqual(
            parse_qs(destination.query)["placeid"], ["ChIJ_demoPlaceId-123"]
        )

    def test_google_redirect_encodes_place_id(self):
        self.register("encoded-owner", "Encoded Shop", "Place & ID/123")
        customer_path = self.customer_path(self.client.get("/dashboard"))
        response = self.client.get(customer_path + "/google")
        self.assertEqual(response.status_code, 302)
        destination = urlparse(response.headers["Location"])
        self.assertEqual(parse_qs(destination.query)["placeid"], ["Place & ID/123"])

    def test_place_id_required_and_web_addresses_are_rejected(self):
        no_place_id = self.client.post(
            "/register",
            data={
                "csrf_token": self.token(),
                "username": "missing-place",
                "password": "college-demo-password",
                "shop_name": "Missing Place Shop",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Enter a valid Google Place ID", no_place_id.data)

        web_address = self.client.post(
            "/register",
            data={
                "csrf_token": self.token(),
                "username": "url-place",
                "password": "college-demo-password",
                "shop_name": "URL Place Shop",
                "place_id": "https://example.com",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Enter a valid Google Place ID", web_address.data)

    def test_shop_data_isolated_between_accounts(self):
        self.register("alice", "Alice's Cafe", "ChIJ_alicePlace")
        self.add_demo_review("Alice-only sample text")
        alice_page = self.client.get("/dashboard")
        self.assertIn(b"ChIJ_alicePlace", alice_page.data)
        self.assertIn(b"Alice-only sample text", alice_page.data)
        self.client.post("/logout", data={"csrf_token": self.token()})
        self.register("bob", "Bob's Books", "ChIJ_bobPlace")
        bob_page = self.client.get("/dashboard")
        self.assertNotIn(b"ChIJ_alicePlace", bob_page.data)
        self.assertNotIn(b"Alice-only sample text", bob_page.data)
        self.assertIn(b"ChIJ_bobPlace", bob_page.data)

    def test_demo_library_selects_once_and_never_redirects_to_google(self):
        self.register("demo-owner", "Classroom Cafe")
        self.add_demo_review("A sample text used only for the local demo.")
        dashboard = self.client.get("/dashboard")
        self.assertIn(b"Review text library", dashboard.data)
        self.assertIn(b"1 available for demo", dashboard.data)

        match = re.search(rb'href="(http://localhost/demo/[^"]+)"', dashboard.data)
        self.assertIsNotNone(match)
        demo_path = match.group(1).decode().replace("http://localhost", "")
        picker = self.client.get(demo_path)
        self.assertIn(b"LOCAL DEMO", picker.data)
        self.assertIn(b"A sample text used only for the local demo.", picker.data)
        self.assertNotIn(b"Continue to Google", picker.data)

        response = self.client.post(
            demo_path + "/select",
            data={
                "csrf_token": self.token(),
                "review_id": "1",
                "rating": "4",
            },
        )
        self.assertEqual(response.status_code, 302)
        result = self.client.get(response.headers["Location"])
        self.assertIn(b"SAVED IN LOCAL DEMO", result.data)
        self.assertIn(b"A sample text used only for the local demo.", result.data)
        self.assertIn(b"4 out of 5 stars", result.data)
        self.assertIn(b"not sent to Google", result.data)

        empty_picker = self.client.get(demo_path)
        self.assertIn(b"No unused examples", empty_picker.data)
        connection = sqlite3.connect(self.db_path)
        try:
            used_at = connection.execute(
                "SELECT used_at FROM review_templates WHERE id = 1"
            ).fetchone()[0]
            row = connection.execute(
                "SELECT status, rating FROM demo_reviews WHERE template_id = 1"
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNotNone(used_at)
        self.assertEqual(row, ("published", 4))

    def test_demo_picker_does_not_expose_other_shops_reviews(self):
        self.register("first-demo", "First Shop")
        self.add_demo_review("Private sample text")
        self.client.post("/logout", data={"csrf_token": self.token()})
        self.register("second-demo", "Second Shop")
        dashboard = self.client.get("/dashboard")
        match = re.search(rb'href="(http://localhost/demo/[^"]+)"', dashboard.data)
        self.assertIsNotNone(match)
        demo_path = match.group(1).decode().replace("http://localhost", "")
        picker = self.client.get(demo_path)
        self.assertIn(b"No unused examples", picker.data)
        self.assertNotIn(b"Private sample text", picker.data)

    def test_shopkeeper_can_update_place_id(self):
        self.register("owner", "Demo Cafe")
        response = self.client.post(
            "/dashboard",
            data={
                "csrf_token": self.token(),
                "action": "update_place_id",
                "place_id": "ChIJ_newPlaceId",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Google Place ID updated", response.data)
        self.assertIn(b"ChIJ_newPlaceId", response.data)
        google_response = self.client.get(
            self.customer_path(response) + "/google"
        )
        self.assertIn("ChIJ_newPlaceId", google_response.headers["Location"])

    def test_existing_database_is_migrated(self):
        legacy_path = os.path.join(self.temp_dir.name, "legacy.sqlite3")
        connection = sqlite3.connect(legacy_path)
        try:
            connection.executescript(
                """CREATE TABLE users (
                       id INTEGER PRIMARY KEY,
                       username TEXT NOT NULL UNIQUE,
                       password_hash TEXT NOT NULL
                   );
                   CREATE TABLE shops (
                       id INTEGER PRIMARY KEY,
                       user_id INTEGER NOT NULL UNIQUE,
                       name TEXT NOT NULL,
                       public_token TEXT NOT NULL UNIQUE
                   );"""
            )
        finally:
            connection.close()
        create_app({"TESTING": True, "DATABASE": legacy_path})
        connection = sqlite3.connect(legacy_path)
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(shops)")}
        finally:
            connection.close()
        self.assertIn("place_id", columns)

    def test_post_requires_csrf_token(self):
        self.register("secure", "Secure Demo Shop")
        response = self.client.post("/dashboard", data={"place_id": "ChIJ_other"})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
