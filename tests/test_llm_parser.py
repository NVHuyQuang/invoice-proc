"""Tests for core/llm_parser.py.

All tests are 100% mocked:
- NO real invoice files read.
- NO live network calls or connections to 127.0.0.1:8045.
- API keys and tokens are never logged or leaked.
"""

import json
import logging
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from pydantic import ValidationError

from config import DEFAULT_MODEL, DEFAULT_PROXY_URL, LLM_CONCURRENCY, LLM_TIMEOUT_SECONDS
from core.llm_parser import (
    LLMClient,
    _format_validation_error,
    _is_retryable_http_error,
    find_env_file,
    load_api_key,
    parse_invoice,
)
from models.schema import Category, DocType, LLMInvoice


def _create_mock_chat_completion(content: str) -> ChatCompletion:
    """Helper to construct a typed OpenAI ChatCompletion response."""
    choice = Choice(
        finish_reason="stop",
        index=0,
        message=ChatCompletionMessage(content=content, role="assistant"),
    )
    return ChatCompletion(
        id="mock-chatcmpl-test",
        choices=[choice],
        created=1700000000,
        model=DEFAULT_MODEL,
        object="chat.completion",
    )


VALID_INVOICE_JSON = json.dumps({
    "doc_type": "goods_invoice",
    "vendor_name": "US Foods Inc.",
    "invoice_no_ref": "<ID_1>",
    "invoice_date_ref": "<D_1>",
    "due_date_ref": "<D_2>",
    "currency": "$",
    "category": Category.FOOD_INGREDIENTS.value,
    "line_items": [
        {
            "item_name": "BEEF FLANK STEAK",
            "qty_ref": "<N_1>",
            "unit_price_ref": "<N_2>",
            "line_total_ref": "<N_3>",
            "unit": "LB",
            "kind": "goods",
        }
    ],
    "charges": [],
    "summary": {
        "subtotal_ref": "<N_4>",
        "tax_ref": "<N_5>",
        "grand_total_ref": "<N_6>",
    },
    "unassigned": ["<N_7>"],
})


@pytest.fixture(autouse=True)
def guard_no_real_network(monkeypatch):
    """Invariant guard: prevent any unmocked socket connections in tests."""
    import socket

    def _forbidden_connect(*args, **kwargs):
        raise RuntimeError("TEST INVARIANT VIOLATION: Live network request attempted!")

    monkeypatch.setattr(socket, "create_connection", _forbidden_connect)


# -------------------------------------------------------------------------
# 1. Successful parsing
# -------------------------------------------------------------------------

def test_parse_invoice_success():
    """Verify normal parsing flow with valid JSON and token references."""
    client = LLMClient(api_key="test-key-mock", backoff_base=0.01)

    mock_resp = _create_mock_chat_completion(VALID_INVOICE_JSON)
    with patch.object(client._client.chat.completions, "create", return_value=mock_resp) as mock_create:
        invoice = client.parse_invoice(prompt="Extract invoice", masked_payload="Text with <N_1>")

        assert isinstance(invoice, LLMInvoice)
        assert invoice.doc_type == DocType.GOODS_INVOICE
        assert invoice.vendor_name == "US Foods Inc."
        assert invoice.invoice_no_ref == "<ID_1>"
        assert len(invoice.line_items) == 1
        assert invoice.line_items[0].qty_ref == "<N_1>"
        assert invoice.summary.grand_total_ref == "<N_6>"

        mock_create.assert_called_once()
        _, kwargs = mock_create.call_args
        assert kwargs["model"] == DEFAULT_MODEL
        assert kwargs["temperature"] == 0
        assert kwargs["response_format"] == {"type": "json_object"}
        assert kwargs["timeout"] == LLM_TIMEOUT_SECONDS


# -------------------------------------------------------------------------
# 2. Broken JSON / Schema errors & 1-time retry
# -------------------------------------------------------------------------

def test_parse_invoice_malformed_json_retry_success():
    """Verify 1-time retry on malformed JSON string, succeeding on second attempt."""
    client = LLMClient(api_key="test-key-mock", backoff_base=0.01)

    bad_resp = _create_mock_chat_completion('{"vendor_name": "US Foods", invalid_json')
    good_resp = _create_mock_chat_completion(VALID_INVOICE_JSON)

    with patch.object(client._client.chat.completions, "create", side_effect=[bad_resp, good_resp]) as mock_create:
        invoice = client.parse_invoice(prompt="Extract invoice", masked_payload="Masked payload text")

        assert isinstance(invoice, LLMInvoice)
        assert invoice.vendor_name == "US Foods Inc."
        assert mock_create.call_count == 2

        # Check second call included validation error message without invoice data
        second_call_messages = mock_create.call_args_list[1][1]["messages"]
        assert len(second_call_messages) == 4
        retry_prompt = second_call_messages[3]["content"]
        assert "validation error" in retry_prompt.lower() or "json decode error" in retry_prompt.lower()


def test_parse_invoice_malformed_json_retry_fails_terminates():
    """Verify retry is only attempted ONCE; if retry fails, error is raised."""
    client = LLMClient(api_key="test-key-mock", backoff_base=0.01)

    bad_resp1 = _create_mock_chat_completion('{"broken": 1,')
    bad_resp2 = _create_mock_chat_completion('{"still_broken": 2,')

    with patch.object(client._client.chat.completions, "create", side_effect=[bad_resp1, bad_resp2]) as mock_create:
        with pytest.raises((ValidationError, json.JSONDecodeError)):
            client.parse_invoice(prompt="Extract", masked_payload="Masked")

        assert mock_create.call_count == 2


def test_parse_invoice_raw_number_in_tokens_retry_without_data():
    """Verify that if LLM returns raw numbers in token refs, error message does NOT leak raw numbers."""
    client = LLMClient(api_key="test-key-mock", backoff_base=0.01)

    # First attempt: returns raw number "99.95" instead of token "<N_1>"
    bad_json = json.dumps({
        "doc_type": "goods_invoice",
        "vendor_name": "Vendor A",
        "line_items": [
            {
                "item_name": "Coffee Beans",
                "qty_ref": "<N_1>",
                "unit_price_ref": "99.95",  # VIOLATION: raw number!
                "line_total_ref": "<N_2>",
            }
        ],
    })
    bad_resp = _create_mock_chat_completion(bad_json)
    good_resp = _create_mock_chat_completion(VALID_INVOICE_JSON)

    with patch.object(client._client.chat.completions, "create", side_effect=[bad_resp, good_resp]) as mock_create:
        invoice = client.parse_invoice(prompt="Extract", masked_payload="Payload with <N_1>")
        assert isinstance(invoice, LLMInvoice)
        assert mock_create.call_count == 2

        # Check that the validation feedback does NOT contain the raw number "99.95"
        second_call_messages = mock_create.call_args_list[1][1]["messages"]
        assistant_retry_content = second_call_messages[2]["content"]
        user_retry_content = second_call_messages[3]["content"]

        assert "99.95" not in assistant_retry_content
        assert "99.95" not in user_retry_content
        assert "unit_price_ref" in user_retry_content


def test_parse_invoice_schema_violation_retry_fails():
    """Verify that if retry output still violates schema, ValidationError is raised."""
    client = LLMClient(api_key="test-key-mock", backoff_base=0.01)

    bad_json = json.dumps({
        "doc_type": "goods_invoice",
        "invoice_no_ref": "BAD_REF_WITHOUT_BRACKETS",
    })
    bad_resp = _create_mock_chat_completion(bad_json)

    with patch.object(client._client.chat.completions, "create", side_effect=[bad_resp, bad_resp]) as mock_create:
        with pytest.raises(ValidationError):
            client.parse_invoice(prompt="Extract", masked_payload="Payload")

        assert mock_create.call_count == 2


# -------------------------------------------------------------------------
# 3. HTTP 429 RateLimitError & Exponential backoff
# -------------------------------------------------------------------------

def test_parse_invoice_429_rate_limit_backoff_recovery():
    """Verify HTTP 429 retries up to 3 times with exponential backoff and succeeds."""
    client = LLMClient(api_key="test-key-mock", backoff_base=0.1, max_retries=3)

    req = httpx.Request("POST", DEFAULT_PROXY_URL)
    resp_429 = httpx.Response(429, request=req)
    err_429 = RateLimitError("Rate limit reached", response=resp_429, body=None)

    good_resp = _create_mock_chat_completion(VALID_INVOICE_JSON)

    # 2 failures then 1 success
    with patch.object(client._client.chat.completions, "create", side_effect=[err_429, err_429, good_resp]) as mock_create:
        with patch("time.sleep") as mock_sleep:
            invoice = client.parse_invoice(prompt="Prompt", masked_payload="Text")

            assert isinstance(invoice, LLMInvoice)
            assert mock_create.call_count == 3
            # Exponential backoff checks: base * 2^0 = 0.1, base * 2^1 = 0.2
            assert mock_sleep.call_count == 2
            mock_sleep.assert_any_call(pytest.approx(0.1))
            mock_sleep.assert_any_call(pytest.approx(0.2))


def test_parse_invoice_429_exceeds_max_retries():
    """Verify HTTP 429 fails after max 3 retries (4 calls total)."""
    client = LLMClient(api_key="test-key-mock", backoff_base=0.01, max_retries=3)

    req = httpx.Request("POST", DEFAULT_PROXY_URL)
    resp_429 = httpx.Response(429, request=req)
    err_429 = RateLimitError("Rate limit reached", response=resp_429, body=None)

    with patch.object(client._client.chat.completions, "create", side_effect=err_429) as mock_create:
        with patch("time.sleep") as mock_sleep:
            with pytest.raises(RateLimitError):
                client.parse_invoice(prompt="Prompt", masked_payload="Text")

            # 1 initial call + 3 retries = 4 calls total
            assert mock_create.call_count == 4
            assert mock_sleep.call_count == 3


# -------------------------------------------------------------------------
# 4. Timeout & 5xx error backoff
# -------------------------------------------------------------------------

def test_parse_invoice_timeout_backoff_recovery():
    """Verify APITimeoutError retries with exponential backoff and recovers."""
    client = LLMClient(api_key="test-key-mock", backoff_base=0.05, max_retries=3)

    req = httpx.Request("POST", DEFAULT_PROXY_URL)
    err_timeout = APITimeoutError(request=req)
    good_resp = _create_mock_chat_completion(VALID_INVOICE_JSON)

    with patch.object(client._client.chat.completions, "create", side_effect=[err_timeout, good_resp]) as mock_create:
        with patch("time.sleep") as mock_sleep:
            invoice = client.parse_invoice(prompt="P", masked_payload="M")

            assert isinstance(invoice, LLMInvoice)
            assert mock_create.call_count == 2
            mock_sleep.assert_called_once_with(pytest.approx(0.05))


def test_parse_invoice_timeout_exhausted():
    """Verify APITimeoutError exhausts max retries and raises."""
    client = LLMClient(api_key="test-key-mock", backoff_base=0.01, max_retries=3)

    req = httpx.Request("POST", DEFAULT_PROXY_URL)
    err_timeout = APITimeoutError(request=req)

    with patch.object(client._client.chat.completions, "create", side_effect=err_timeout) as mock_create:
        with patch("time.sleep"):
            with pytest.raises(APITimeoutError):
                client.parse_invoice(prompt="P", masked_payload="M")

            assert mock_create.call_count == 4


def test_parse_invoice_5xx_server_error_backoff():
    """Verify 5xx internal server errors are retried with backoff."""
    client = LLMClient(api_key="test-key-mock", backoff_base=0.01, max_retries=3)

    req = httpx.Request("POST", DEFAULT_PROXY_URL)
    resp_500 = httpx.Response(500, request=req)
    err_500 = InternalServerError("Internal Server Error", response=resp_500, body=None)

    resp_503 = httpx.Response(503, request=req)
    err_503 = APIStatusError("Service Unavailable", response=resp_503, body=None)

    good_resp = _create_mock_chat_completion(VALID_INVOICE_JSON)

    with patch.object(client._client.chat.completions, "create", side_effect=[err_500, err_503, good_resp]) as mock_create:
        with patch("time.sleep") as mock_sleep:
            invoice = client.parse_invoice(prompt="P", masked_payload="M")

            assert isinstance(invoice, LLMInvoice)
            assert mock_create.call_count == 3
            assert mock_sleep.call_count == 2


def test_non_retryable_400_error_fails_immediately():
    """Verify client 400 Bad Request error does not retry and fails immediately."""
    client = LLMClient(api_key="test-key-mock", backoff_base=0.01, max_retries=3)

    req = httpx.Request("POST", DEFAULT_PROXY_URL)
    resp_400 = httpx.Response(400, request=req)
    err_400 = APIStatusError("Bad Request", response=resp_400, body=None)

    with patch.object(client._client.chat.completions, "create", side_effect=err_400) as mock_create:
        with patch("time.sleep") as mock_sleep:
            with pytest.raises(APIStatusError):
                client.parse_invoice(prompt="P", masked_payload="M")

            assert mock_create.call_count == 1
            mock_sleep.assert_not_called()


# -------------------------------------------------------------------------
# 5. Concurrency Semaphore
# -------------------------------------------------------------------------

def test_concurrency_semaphore_limits_parallel_executions():
    """Verify Semaphore limits concurrent calls to specified concurrency limit."""
    concurrency_limit = 2
    client = LLMClient(api_key="test-key-mock", concurrency=concurrency_limit, backoff_base=0.01)

    active_count = 0
    max_active = 0
    lock = threading.Lock()

    def _slow_mock_create(*args, **kwargs):
        nonlocal active_count, max_active
        with lock:
            active_count += 1
            if active_count > max_active:
                max_active = active_count
        time.sleep(0.05)
        with lock:
            active_count -= 1
        return _create_mock_chat_completion(VALID_INVOICE_JSON)

    with patch.object(client._client.chat.completions, "create", side_effect=_slow_mock_create):
        threads = [
            threading.Thread(target=client.parse_invoice, args=("P", "M"))
            for _ in range(6)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert max_active <= concurrency_limit


# -------------------------------------------------------------------------
# 6. API Key Security (Never Logged / Leaked)
# -------------------------------------------------------------------------

def test_api_key_not_in_repr_or_str():
    """Verify API key is never exposed via repr or str of LLMClient."""
    secret = "sk-TOPSECRET-KEY-1234567890"
    client = LLMClient(api_key=secret)

    assert secret not in repr(client)
    assert secret not in str(client)


def test_api_key_not_leaked_in_logs(caplog):
    """Verify that logger outputs during retries and failures never contain the API key."""
    secret = "sk-CRITICAL-DO-NOT-LOG-ABCDEF"
    client = LLMClient(api_key=secret, backoff_base=0.01, max_retries=2)

    req = httpx.Request("POST", DEFAULT_PROXY_URL)
    resp_429 = httpx.Response(429, request=req)
    err_429 = RateLimitError("Rate limit hit", response=resp_429, body=None)

    with caplog.at_level(logging.DEBUG):
        with patch.object(client._client.chat.completions, "create", side_effect=err_429):
            with pytest.raises(RateLimitError):
                client.parse_invoice(prompt="P", masked_payload="M")

    # Assert secret is never present in log records
    for record in caplog.records:
        assert secret not in record.message
        assert secret not in str(record.args)


def test_load_api_key_from_bare_token_file(tmp_path):
    """Verify load_api_key reads bare token file without '=' sign."""
    token = "sk-921abc456def789"
    env_file = tmp_path / ".env.ggproproxyserver"
    env_file.write_text(f"{token}\n", encoding="utf-8")

    loaded = load_api_key(env_path=env_file)
    assert loaded == token


def test_load_api_key_from_env_var_syntax_file(tmp_path):
    """Verify load_api_key reads standard KEY=VALUE format."""
    token = "sk-standard-var-001"
    env_file = tmp_path / ".env.ggproproxyserver"
    env_file.write_text(f"OPENAI_API_KEY={token}\n", encoding="utf-8")

    loaded = load_api_key(env_path=env_file)
    assert loaded == token


def test_load_api_key_from_os_environ(monkeypatch):
    """Verify load_api_key priority from os.environ."""
    token = "sk-environ-token-999"
    monkeypatch.setenv("OPENAI_API_KEY", token)

    loaded = load_api_key()
    assert loaded == token


# -------------------------------------------------------------------------
# 7. Module-level parse_invoice & utilities
# -------------------------------------------------------------------------

def test_module_level_parse_invoice():
    """Verify the standalone module-level parse_invoice function."""
    mock_client = MagicMock(spec=LLMClient)
    expected_invoice = LLMInvoice(vendor_name="Acme Corp")
    mock_client.parse_invoice.return_value = expected_invoice

    res = parse_invoice(prompt="Prompt", masked_payload="Payload", client=mock_client)
    assert res == expected_invoice
    mock_client.parse_invoice.assert_called_once_with("Prompt", "Payload")


def test_format_validation_error_scrubs_data_cleanly():
    """Verify _format_validation_error produces clean descriptions without numbers or input data."""
    try:
        LLMInvoice.model_validate_json('{"doc_type": "goods_invoice", "invoice_no_ref": "123456"}')
    except ValidationError as err:
        formatted = _format_validation_error(err)
        assert "123456" not in formatted
        assert "invoice_no_ref" in formatted


def test_is_retryable_http_error():
    """Verify classification of retryable vs non-retryable errors."""
    req = httpx.Request("POST", DEFAULT_PROXY_URL)
    assert _is_retryable_http_error(RateLimitError("429", response=httpx.Response(429, request=req), body=None)) is True
    assert _is_retryable_http_error(InternalServerError("500", response=httpx.Response(500, request=req), body=None)) is True
    assert _is_retryable_http_error(APITimeoutError(request=req)) is True
    assert _is_retryable_http_error(APIConnectionError(request=req)) is True
    assert _is_retryable_http_error(APIStatusError("400", response=httpx.Response(400, request=req), body=None)) is False
    assert _is_retryable_http_error(ValueError("random value error")) is False
