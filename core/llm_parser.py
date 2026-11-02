"""LLM client and structured JSON extractor module.

PLAN 4.1:
- OpenAI-compatible client targeting configured proxy (e.g. http://127.0.0.1:8045/v1).
- Token read securely from .env.ggproproxyserver via python-dotenv or env var. Never logged or leaked.
- temperature=0, JSON mode / structured output.
- Timeout (60s default), retry up to 3 times with exponential backoff on 429/5xx/timeout.
- On structural JSON / schema error: retry 1 time with validation error info (without data).
- Concurrency limiting via Semaphore.
"""

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Union, cast
from openai.types.chat import ChatCompletionMessageParam

import dotenv
import httpx
from openai import (
    OpenAI,
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
    InternalServerError,
    APIStatusError,
)
from pydantic import ValidationError

from config import (
    DEFAULT_PROXY_URL,
    DEFAULT_MODEL,
    LLM_TIMEOUT_SECONDS,
    LLM_MAX_RETRIES,
    LLM_CONCURRENCY,
)
from models.schema import LLMInvoice

logger = logging.getLogger(__name__)


def find_env_file() -> Optional[Path]:
    """Find the .env.ggproproxyserver file by walking up from cwd and module location."""
    candidates = [
        Path.cwd() / ".env.ggproproxyserver",
        Path(__file__).resolve().parent.parent / ".env.ggproproxyserver",
    ]
    for p in candidates:
        if p.is_file():
            return p

    # Walk up from current working directory
    cur = Path.cwd().resolve()
    while cur.parent != cur:
        p = cur / ".env.ggproproxyserver"
        if p.is_file():
            return p
        cur = cur.parent

    # Walk up from module directory
    cur = Path(__file__).resolve().parent
    while cur.parent != cur:
        p = cur / ".env.ggproproxyserver"
        if p.is_file():
            return p
        cur = cur.parent

    return None


def load_api_key(
    custom_key: Optional[str] = None,
    env_path: Optional[Union[str, Path]] = None,
) -> str:
    """Read API key securely from argument, env vars, or .env.ggproproxyserver.

    Never logs or leaks the secret key.
    """
    if custom_key and custom_key.strip():
        return custom_key.strip()

    # 1. Check environment variables
    for var_name in ("OPENAI_API_KEY", "GGPRO_API_KEY", "GEMINI_API_KEY", "API_KEY"):
        val = os.getenv(var_name)
        if val and val.strip():
            return val.strip()

    # 2. Look for .env.ggproproxyserver
    target_path = Path(env_path) if env_path else find_env_file()
    if target_path and target_path.is_file():
        try:
            # Parse with python-dotenv first
            env_vars = dotenv.dotenv_values(target_path)
            for var_name in ("OPENAI_API_KEY", "GGPRO_API_KEY", "GEMINI_API_KEY", "API_KEY"):
                val = env_vars.get(var_name)
                if val and str(val).strip():
                    return str(val).strip()

            for k, v in env_vars.items():
                if v and str(v).strip():
                    return str(v).strip()

            # Handle bare tokens or single un-keyed lines (e.g. sk-...)
            with open(target_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        _, v = line.split("=", 1)
                        v = v.strip().strip("'\"")
                        if v:
                            return v
                    else:
                        return line
        except Exception as e:
            logger.debug("Failed reading env file: %s", type(e).__name__)

    return ""


def _format_validation_error(err: Exception) -> str:
    """Extract clean schema validation error information without any data/payload values."""
    if isinstance(err, ValidationError):
        lines = []
        for e in err.errors():
            loc = " -> ".join(str(part) for part in e.get("loc", []))
            msg = e.get("msg", "Invalid value")
            err_type = e.get("type", "")
            # Scrub any specific input values, quotes, or numbers from msg
            cleaned_msg = re.sub(r":\s*(['\"][^'\"]*['\"])", "", msg)
            cleaned_msg = re.sub(r"\b\d+(?:\.\d+)?\b", "[number]", cleaned_msg)
            lines.append(f"- Field '{loc}': {cleaned_msg} (type: {err_type})")
        return "Pydantic schema validation errors:\n" + "\n".join(lines)
    elif isinstance(err, json.JSONDecodeError):
        return f"JSON decode error: {err.msg} at line {err.lineno}, column {err.colno}."
    else:
        return f"Schema validation error: {type(err).__name__}."


def _filter_raw_numbers(content: str) -> str:
    """Filter out unmasked real numbers from LLM response before resending in retry."""
    def repl(m: re.Match) -> str:
        tok = m.group(0)
        if tok.startswith("<") and tok.endswith(">"):
            return tok
        return "[REDACTED]"

    token_or_number_pattern = re.compile(
        r'<(?:N|D|ID)_\d+(?::neg)?>|\b\d+(?:[.,]\d+)*\b'
    )
    return token_or_number_pattern.sub(repl, content)


def _is_retryable_http_error(err: Exception) -> bool:
    """Check if exception is a 429, 5xx, timeout, or network connection error."""
    if isinstance(err, (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError, TimeoutError)):
        return True
    if isinstance(err, APIStatusError):
        return err.status_code == 429 or err.status_code >= 500
    if isinstance(err, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    return False


class LLMClient:
    """Client for querying LLM proxy with masked invoice texts."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        concurrency: Optional[int] = None,
        backoff_base: float = 1.0,
        env_file: Optional[Union[str, Path]] = None,
        semaphore: Optional[threading.Semaphore] = None,
    ) -> None:
        self.base_url = base_url or DEFAULT_PROXY_URL
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout if timeout is not None else LLM_TIMEOUT_SECONDS
        self.max_retries = max_retries if max_retries is not None else LLM_MAX_RETRIES
        self.concurrency = concurrency if concurrency is not None else LLM_CONCURRENCY
        self.backoff_base = backoff_base

        self._api_key = load_api_key(custom_key=api_key, env_path=env_file)
        self._client = OpenAI(
            base_url=self.base_url,
            api_key=self._api_key or "EMPTY",
            timeout=self.timeout,
            max_retries=0,  # We manage retries with backoff and error formatting explicitly
        )
        self._semaphore = semaphore or threading.Semaphore(self.concurrency)

    @property
    def semaphore(self) -> threading.Semaphore:
        """Concurrency semaphore."""
        return self._semaphore

    def __repr__(self) -> str:
        # Guarantee API key is never leaked via repr
        return f"LLMClient(base_url={self.base_url!r}, model={self.model!r}, concurrency={self.concurrency})"

    def __str__(self) -> str:
        return self.__repr__()

    def _call_with_network_retries(self, messages: List[Dict[str, Any]]) -> str:
        """Execute OpenAI chat completion with exponential backoff on 429/5xx/timeout."""
        attempt = 0
        while True:
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=cast(List[ChatCompletionMessageParam], messages),
                    temperature=0,
                    response_format={"type": "json_object"},
                    timeout=self.timeout,
                )
                if not response.choices or not response.choices[0].message:
                    raise ValueError("Empty response choices received from LLM proxy")
                content = response.choices[0].message.content
                if content is None:
                    raise ValueError("LLM proxy returned null content")
                return content
            except Exception as err:
                if _is_retryable_http_error(err) and attempt < self.max_retries:
                    delay = self.backoff_base * (2 ** attempt)
                    logger.warning(
                        "Retryable error on attempt %d/%d (%s). Backing off for %.2fs...",
                        attempt + 1,
                        self.max_retries,
                        type(err).__name__,
                        delay,
                    )
                    time.sleep(delay)
                    attempt += 1
                    continue
                logger.error(
                    "LLM request failed (attempt %d/%d): %s",
                    attempt + 1,
                    self.max_retries,
                    type(err).__name__,
                )
                raise

    def parse_invoice(self, prompt: str, masked_payload: str) -> LLMInvoice:
        """Call LLM with masked payload and parse structured output into LLMInvoice.

        Args:
            prompt: System instruction prompt.
            masked_payload: Sanitized and masked document text.

        Returns:
            Validated LLMInvoice instance containing only token references.

        Raises:
            Exception: On fatal network, parsing, or timeout error after retries.
        """
        with self._semaphore:
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": masked_payload},
            ]

            raw_content = self._call_with_network_retries(messages)

            try:
                return LLMInvoice.model_validate_json(raw_content)
            except (ValidationError, json.JSONDecodeError, ValueError) as val_err:
                logger.warning(
                    "Structural error in LLM response: %s. Retrying once with error feedback.",
                    type(val_err).__name__,
                )
                val_feedback = _format_validation_error(val_err)
                assistant_payload = _filter_raw_numbers(raw_content)
                retry_messages = list(messages) + [
                    {"role": "assistant", "content": assistant_payload},
                    {
                        "role": "user",
                        "content": (
                            f"The previous output had validation errors:\n{val_feedback}\n\n"
                            "Please correct the JSON output to strictly match the required schema. Output valid JSON only."
                        ),
                    },
                ]

                retry_raw_content = self._call_with_network_retries(retry_messages)
                try:
                    return LLMInvoice.model_validate_json(retry_raw_content)
                except Exception as second_err:
                    logger.error(
                        "LLM output validation failed again on retry: %s",
                        type(second_err).__name__,
                    )
                    raise second_err


def parse_invoice(
    prompt: str,
    masked_payload: str,
    client: Optional[LLMClient] = None,
) -> LLMInvoice:
    """Parse a masked invoice payload into LLMInvoice.

    Args:
        prompt: System instruction prompt.
        masked_payload: Sanitized and masked document text.
        client: Optional LLMClient instance. Defaults to a new LLMClient().

    Returns:
        Validated LLMInvoice instance.
    """
    if client is None:
        client = LLMClient()
    return client.parse_invoice(prompt, masked_payload)
