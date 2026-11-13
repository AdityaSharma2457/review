import os
import re
import tempfile
import unittest

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
                "WTF_CSRF_ENABLED": False,
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

    def register(self, username, shop_name):
        return self.client.post(
            "/register",
            data={
                "csrf_token": self.token(),
                "username": username,
                "password": "college-demo-password",
                "shop_name": shop_name,
            },
            follow_redirects=True,
        )

    def add_text(self, text):
        return self.client.post(
            "/dashboard",
            data={"csrf_token": self.token(), "review_text": text},
            follow_redirects=True,
        )

    def test_shop_data_isolated_between_accounts(self):
        self.register("alice", "Alice's Cafe")
        self.add_text("Alice's private demo text")
        self.client.post("/logout", data={"csrf_token": self.token()})
        self.register("bob", "Bob's Books")
        page = self.client.get("/dashboard")
        self.assertNotIn(b"Alice's private demo text", page.data)
        self.assertIn(b"Bob&#39;s Books", page.data)

    def test_customer_select_and_publish_are_local_and_one_time(self):
        self.register("owner", "Demo Cafe")
        self.add_text("Sample text for a local simulation")
        dashboard = self.client.get("/dashboard")
        match = re.search(rb'href="(http://localhost/customer/[^"]+)"', dashboard.data)
        self.assertIsNotNone(match)
        customer_path = match.group(1).decode().replace("http://localhost", "")
        customer_page = self.client.get(customer_path)
        self.assertIn(b"Sample text for a local simulation", customer_page.data)
        token = self.token()
        selected = self.client.post(
            customer_path + "/select",
            data={"csrf_token": token, "review_id": "1", "rating": "5"},
        )
        self.assertEqual(selected.status_code, 302)
        mock_path = selected.headers["Location"]
        preview = self.client.get(mock_path)
        self.assertIn(b"MOCK DESTINATION", preview.data)
        self.assertIn(b"Sample text for a local simulation", preview.data)
        self.assertIn(b"Publishing to the local demo", preview.data)
        self.assertIn(b"form.requestSubmit()", preview.data)
        published = self.client.post(
            mock_path, data={"csrf_token": token}, follow_redirects=True
        )
        self.assertIn(b"Simulation complete", published.data)
        unavailable = self.client.get(customer_path)
        self.assertIn(b"There are no unused sample reviews", unavailable.data)

    def test_post_requires_csrf_token(self):
        self.register("secure", "Secure Demo Shop")
        response = self.client.post("/dashboard", data={"review_text": "text"})
        self.assertEqual(response.status_code, 400)

    def test_customer_cannot_select_another_shops_text(self):
        self.register("first-owner", "First Shop")
        self.add_text("First shop only")
        self.client.post("/logout", data={"csrf_token": self.token()})
        self.register("second-owner", "Second Shop")
        dashboard = self.client.get("/dashboard")
        match = re.search(rb'href="(http://localhost/customer/[^"]+)"', dashboard.data)
        self.assertIsNotNone(match)
        customer_path = match.group(1).decode().replace("http://localhost", "")
        response = self.client.post(
            customer_path + "/select",
            data={
                "csrf_token": self.token(),
                "review_id": "1",
                "rating": "5",
            },
            follow_redirects=True,
        )
        self.assertIn(b"There are no unused sample reviews", response.data)
        self.assertNotIn(b"First shop only", response.data)


if __name__ == "__main__":
    unittest.main()
