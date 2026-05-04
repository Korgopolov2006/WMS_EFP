import os
import re


USERNAME = os.getenv("LOCUST_USER", "admin")
PASSWORD = os.getenv("LOCUST_PASS", "admin")
API_TOKEN = os.getenv("LOCUST_API_TOKEN", "")


class WebUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        r = self.client.get("/accounts/login/")
        m = re.search(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"', r.text)
        token = m.group(1) if m else ""
        self.client.post(
            "/accounts/login/",
            data={
                "username": USERNAME,
                "password": PASSWORD,
                "csrfmiddlewaretoken": token,
            },
            headers={"Referer": self.client.base_url + "/accounts/login/"},
            allow_redirects=True,
        )

    @task(3)
    def dashboard(self):
        self.client.get("/", name="GET /")

    @task(2)
    def stock(self):
        self.client.get("/inventory/stock/", name="GET /inventory/stock/")

    @task(2)
    def movements(self):
        self.client.get("/inventory/movements/", name="GET /inventory/movements/")

    @task(2)
    def tasks_page(self):
        self.client.get("/tasks/", name="GET /tasks/")

    @task(1)
    def scanner(self):
        self.client.get("/catalog/codes/scan/", name="GET /catalog/codes/scan/")

    @task(1)
    def notifications(self):
        self.client.get("/notifications/", name="GET /notifications/")

    @task(2)
    def unread_count(self):
        self.client.get("/notifications/unread-count/", name="GET unread-count")


class ApiUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        if not API_TOKEN:
            self.environment.runner.quit()
            return
        self.client.headers.update({
            "Authorization": f"Bearer {API_TOKEN}",
            "Content-Type": "application/json",
        })

    @task(3)
    def list_products(self):
        self.client.get("/api/v1/products/", name="API GET /products/")

    @task(2)
    def list_orders(self):
        self.client.get("/api/v1/orders/", name="API GET /orders/")

    @task(2)
    def list_tasks(self):
        self.client.get("/api/v1/tasks/", name="API GET /tasks/")

    @task(1)
    def put_product(self):
        r = self.client.get("/api/v1/products/?limit=1", name="API GET first product")
        try:
            data = r.json()
            items = data.get("results") or data.get("items") or []
            if not items:
                return
            pk = items[0]["id"]
        except Exception:
            return
        self.client.put(
            f"/api/v1/products/{pk}/",
            json={"name": items[0].get("name", "Product")},
            name="API PUT /products/<id>/",
        )
