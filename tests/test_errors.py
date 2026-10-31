import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from center_errors import classify_error, classify_failure


def jsonl(*records):
    return "\n".join(json.dumps(r) for r in records)


class ExistingBehaviour(unittest.TestCase):
    def test_plain_text_classes(self):
        self.assertEqual(classify_error("401 authentication failed"), "auth")
        self.assertEqual(classify_error("unknown model foo"), "invalid_model")
        self.assertEqual(classify_error("429 rate limit"), "rate_limit")
        self.assertEqual(classify_error("error: unknown option '--bad'"), "config")
        self.assertEqual(classify_error("something odd"), "worker_failure")
        self.assertEqual(classify_error(""), "worker_failure")
        self.assertEqual(classify_error(None), "worker_failure")

    def test_worker_reexport(self):
        import center_errors
        import center_worker
        self.assertIs(center_worker.classify_error, center_errors.classify_error)


class IncidentalDigits(unittest.TestCase):
    def test_session_id_with_401_and_quota(self):
        log = jsonl({"type": "system", "subtype": "init", "session_id": "s-401-429"},
                    {"type": "result", "is_error": True, "session_id": "s-401-429",
                     "result": "You've hit your limit · resets 3pm"})
        self.assertEqual(classify_error(log), "quota_exhausted")

    def test_success_usage_counters(self):
        log = jsonl({"type": "result", "is_error": False, "result": "done, status 401 handled in code",
                     "session_id": "x-403", "usage": {"input_tokens": 401, "output_tokens": 429}})
        self.assertEqual(classify_error(log), "worker_failure")

    def test_command_output_and_prompts_are_not_errors(self):
        log = jsonl({"type": "thread.started", "thread_id": "t-429"},
                    {"type": "item.completed", "item": {"type": "command_execution", "status": "completed",
                     "aggregated_output": "return 429  # HTTP 401 unauthorized sample", "exit_code": 0}},
                    {"type": "user", "content": "fix the quota exceeded handler for 403"})
        self.assertEqual(classify_failure(log)["class"], "worker_failure")

    def test_four_digit_numbers_are_not_http(self):
        self.assertEqual(classify_error("HTTP 4290 processed, status code 4011"), "worker_failure")


class ModelAndQuota(unittest.TestCase):
    def test_invalid_model_structured(self):
        log = jsonl({"type": "error", "error": {"type": "not_found_error", "message": "model: foo-9 does not exist"}})
        self.assertEqual(classify_error(log), "invalid_model")

    def test_temporary_429_vs_quota(self):
        temporary = {"error": {"status": 429, "type": "rate_limit_error", "message": "Too many requests"}}
        quota = {"error": {"status": 429, "type": "usage_limit_reached", "message": "The usage limit has been reached"}}
        bare = {"error": {"status": 429, "message": "slow down"}}
        self.assertEqual(classify_error(json.dumps(temporary)), "rate_limit")
        self.assertEqual(classify_error(json.dumps(quota)), "quota_exhausted")
        self.assertEqual(classify_error(json.dumps(bare)), "rate_limit")

    def test_quota_phrases(self):
        for text in ("usage_exhausted", "You've hit your limit", "subscription quota exceeded", "5-hour limit reached"):
            self.assertEqual(classify_error(text), "quota_exhausted", text)

    def test_retry_after_only_when_reported(self):
        reported = classify_failure(json.dumps({"error": {"status": 429, "message": "slow down", "retry_after": 30}}))
        self.assertEqual((reported["class"], reported["retry_after"]), ("rate_limit", 30))
        unreported = classify_failure("429 rate limit")
        self.assertIsNone(unreported["retry_after"])


class AuthFailures(unittest.TestCase):
    def test_structured_statuses(self):
        for status in (401, 403):
            log = json.dumps({"type": "error", "error": {"status_code": status, "message": "denied"}})
            self.assertEqual(classify_error(log), "auth", status)

    def test_envelope_login_text(self):
        log = json.dumps({"type": "result", "is_error": True, "result": "Invalid API key · Please run /login"})
        self.assertEqual(classify_error(log), "auth")

    def test_envelope_api_error_status(self):
        log = json.dumps({"type": "result", "is_error": True, "result": "request failed", "api_error_status": 401})
        self.assertEqual(classify_error(log), "auth")

    def test_clear_http_text(self):
        self.assertEqual(classify_error("Request failed with HTTP 401"), "auth")
        self.assertEqual(classify_error("status code: 429"), "rate_limit")


class StructuredNesting(unittest.TestCase):
    def test_json_inside_message_string(self):
        inner = json.dumps({"status": 429, "error": {"type": "usage_limit_reached"}})
        log = jsonl({"type": "thread.started", "thread_id": "t-401"},
                    {"type": "turn.failed", "error": {"message": inner}})
        result = classify_failure(log)
        self.assertEqual(result["class"], "quota_exhausted")
        self.assertEqual(result["source"], "structured")

    def test_doubly_nested_error(self):
        log = json.dumps({"error": {"error": {"type": "rate_limit_error", "message": "try later"}}})
        self.assertEqual(classify_error(log), "rate_limit")

    def test_explicit_error_precedes_is_error_result(self):
        log = json.dumps({"type": "result", "is_error": True, "result": "Not logged in",
                          "error": {"type": "rate_limit_error", "message": "slow"}})
        self.assertEqual(classify_error(log), "rate_limit")

    def test_truncated_first_line_still_uses_text(self):
        log = 'ssage":"partial"}\n' + jsonl({"type": "error", "message": "Unauthorized"})
        self.assertEqual(classify_error(log), "auth")


class Privacy(unittest.TestCase):
    def test_only_labels_are_returned(self):
        secret = "sk-private-token-12345"
        log = jsonl({"type": "result", "is_error": True, "result": f"hit your limit {secret}", "session_id": "abc"})
        result = classify_failure(log)
        self.assertEqual(set(result), {"class", "source", "retry_after"})
        self.assertNotIn(secret, repr(result))
        self.assertNotIn(secret, classify_error(log))


if __name__ == "__main__":
    unittest.main()


class CrossReviewRegressions(unittest.TestCase):
    def test_success_payload_never_overrides_actual_failure(self):
        success = {"type": "result", "is_error": False, "structured_output": {"error": {"status": 401}}}
        actual = {"type": "turn.failed", "error": {"message": "usage_exhausted"}}
        self.assertEqual(classify_error(json.dumps(success)), "worker_failure")
        self.assertEqual(classify_error(json.dumps(success) + "\n" + json.dumps(actual)), "quota_exhausted")

    def test_deep_or_oversized_input_returns_safely(self):
        self.assertEqual(classify_error("[" * 2000 + "0" + "]" * 2000), "worker_failure")
        self.assertEqual(classify_error("x" * 1048577), "worker_failure")
        self.assertEqual(classify_error(json.dumps({"error": {"message": "[" * 2000 + "0" + "]" * 2000}})), "worker_failure")
