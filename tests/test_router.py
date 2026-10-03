import unittest


class RouterContractTests(unittest.TestCase):
    def test_dispatch_extracts_named_path_parameters(self):
        from app.responses import success_response
        from app.router import Request, Router

        router = Router()
        router.add(
            "GET",
            r"/api/v1/items/(?P<item_id>[^/]+)",
            lambda request: success_response(
                {"itemId": request.path_params["item_id"]}, request.request_id
            ),
        )

        response = router.dispatch(
            Request(method="GET", path="/api/v1/items/item-1", request_id="req-1")
        )

        self.assertEqual(200, response.status)
        self.assertEqual("item-1", response.body["data"]["itemId"])
        self.assertEqual("req-1", response.body["requestId"])

    def test_dispatch_distinguishes_not_found_and_method_not_allowed(self):
        from app.router import MethodNotAllowed, Request, RouteNotFound, Router

        router = Router()
        router.add("GET", r"/api/v1/items", lambda request: None)

        with self.assertRaises(MethodNotAllowed):
            router.dispatch(Request(method="POST", path="/api/v1/items", request_id="r"))
        with self.assertRaises(RouteNotFound):
            router.dispatch(Request(method="GET", path="/api/v1/missing", request_id="r"))

    def test_response_envelopes_never_require_raw_exception_details(self):
        from app.responses import error_response, success_response

        success = success_response({"ok": True}, "req-success", status=201)
        failure = error_response(
            "VALIDATION_ERROR", "Invalid input", "req-error", status=422
        )

        self.assertEqual(201, success.status)
        self.assertEqual(
            {"success": True, "data": {"ok": True}, "requestId": "req-success"},
            success.body,
        )
        self.assertEqual(422, failure.status)
        self.assertEqual("VALIDATION_ERROR", failure.body["error"]["code"])
        self.assertNotIn("exception", failure.body["error"])


if __name__ == "__main__":
    unittest.main()
