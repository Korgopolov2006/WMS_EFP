import json

from django.test import RequestFactory, SimpleTestCase

from .utils import json_error, json_ok, parse_json


class ApiUtilsTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_json_ok_response_shape(self):
        response = json_ok({"value": 1})
        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["value"], 1)

    def test_json_error_response_shape(self):
        response = json_error("Bad input", status=422, code="validation_error")
        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(response.status_code, 422)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["message"], "Bad input")
        self.assertEqual(payload["error"]["code"], "validation_error")

    def test_parse_json_success(self):
        request = self.factory.post(
            "/api/v1/test/",
            data=json.dumps({"a": 1, "b": "x"}),
            content_type="application/json",
        )
        parsed = parse_json(request)
        self.assertEqual(parsed, {"a": 1, "b": "x"})

    def test_parse_json_rejects_wrong_content_type(self):
        request = self.factory.post("/api/v1/test/", data="a=1", content_type="application/x-www-form-urlencoded")
        with self.assertRaisesMessage(ValueError, "Content-Type must be application/json"):
            parse_json(request)

    def test_parse_json_rejects_invalid_json(self):
        request = self.factory.post("/api/v1/test/", data="{bad-json", content_type="application/json")
        with self.assertRaisesMessage(ValueError, "Invalid JSON body"):
            parse_json(request)
