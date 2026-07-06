"""
Shared LLM client for the Financial Due-Diligence system.
Central gateway for all Gemini API calls with structured output support,
token/latency logging, and retry logic.
"""

import os
import time
from typing import Any, Type

from google import genai
# pyrefly: ignore [missing-import]
from google.genai import errors, types
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
from pydantic import BaseModel

# Load environment variables
load_dotenv()


class LLMClient:
    """
    A shared client wrapper for the Google Gen AI SDK.
    Supports both free-form and structured (JSON schema) generation.
    Logs token usage and latency for every call.
    """

    def __init__(self, api_key: str = None, default_model: str = "gemini-2.5-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.default_model = default_model
        self._usage_log: list[dict] = []  # In-memory log; also persisted to SQLite

        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)
        else:
            self.client = genai.Client()

    def is_configured(self) -> bool:
        """Checks if the Gemini API Key is configured."""
        return bool(self.api_key or os.getenv("GEMINI_API_KEY"))

    def generate_content(
        self,
        message: str,
        model: str = None,
        agent_name: str = "unknown",
        **kwargs
    ) -> str:
        """
        Send a free-form text generation request to Gemini.
        Returns the text response.
        """
        if not self.is_configured():
            raise ValueError(
                "Gemini API key is not configured. Please set the GEMINI_API_KEY "
                "environment variable."
            )

        target_model = model or self.default_model
        start_time = time.time()

        try:
            response = self.client.models.generate_content(
                model=target_model,
                contents=message,
                **kwargs
            )

            latency_ms = (time.time() - start_time) * 1000
            self._log_usage(
                agent_name=agent_name,
                model=target_model,
                response=response,
                latency_ms=latency_ms
            )

            return response.text

        except errors.APIError as e:
            latency_ms = (time.time() - start_time) * 1000
            print(f"[LLM] API Error in {agent_name} after {latency_ms:.0f}ms: {e}")
            raise

    def generate_structured(
        self,
        message: str,
        response_schema: Type[BaseModel],
        model: str = None,
        agent_name: str = "unknown",
        system_instruction: str = None,
        max_retries: int = 3,
    ) -> Any:
        """
        Send a structured output request to Gemini.
        Uses response_mime_type='application/json' and response_schema
        to get typed, parseable responses.

        Returns the parsed Pydantic model instance (via response.parsed).
        Falls back to raw JSON parsing on failure.
        """
        if not self.is_configured():
            raise ValueError(
                "Gemini API key is not configured. Please set the GEMINI_API_KEY "
                "environment variable."
            )

        target_model = model or self.default_model
        last_error = None

        for attempt in range(max_retries):
            start_time = time.time()
            try:
                config = types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=response_schema,
                )

                if system_instruction:
                    config.system_instruction = system_instruction

                response = self.client.models.generate_content(
                    model=target_model,
                    contents=message,
                    config=config,
                )

                latency_ms = (time.time() - start_time) * 1000
                self._log_usage(
                    agent_name=agent_name,
                    model=target_model,
                    response=response,
                    latency_ms=latency_ms
                )

                # Try parsed first (Pydantic model), fall back to raw text
                if hasattr(response, 'parsed') and response.parsed is not None:
                    return response.parsed
                else:
                    # Fallback: parse the JSON text manually
                    import json
                    data = json.loads(response.text)
                    return response_schema.model_validate(data)

            except errors.APIError as e:
                latency_ms = (time.time() - start_time) * 1000
                last_error = e
                print(f"[LLM] Structured output attempt {attempt + 1}/{max_retries} "
                      f"failed for {agent_name} after {latency_ms:.0f}ms: {e}")
                if attempt < max_retries - 1:
                    # Exponential backoff
                    time.sleep(2 ** attempt)
                continue

            except Exception as e:
                latency_ms = (time.time() - start_time) * 1000
                last_error = e
                print(f"[LLM] Unexpected error in structured output for {agent_name} "
                      f"after {latency_ms:.0f}ms: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                continue

        # All retries exhausted
        raise last_error or RuntimeError(f"All {max_retries} retries failed for {agent_name}")

    def _log_usage(self, agent_name: str, model: str, response, latency_ms: float):
        """Log token usage and latency for a completed API call."""
        input_tokens = 0
        output_tokens = 0

        # Extract token counts from response metadata if available
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            meta = response.usage_metadata
            input_tokens = getattr(meta, 'prompt_token_count', 0) or 0
            output_tokens = getattr(meta, 'candidates_token_count', 0) or 0

        usage_entry = {
            "agent_name": agent_name,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": round(latency_ms, 1),
            "timestamp": time.time(),
        }

        self._usage_log.append(usage_entry)

        print(f"[LLM] {agent_name} | {model} | "
              f"in={input_tokens} out={output_tokens} | "
              f"{latency_ms:.0f}ms")

        # Async persistence to SQLite happens separately (called by agents)
        return usage_entry

    def get_recent_usage(self, n: int = 20) -> list[dict]:
        """Get the N most recent usage log entries (in-memory)."""
        return self._usage_log[-n:]

    def get_total_tokens(self) -> dict:
        """Get aggregate token counts."""
        total_in = sum(e.get("input_tokens", 0) for e in self._usage_log)
        total_out = sum(e.get("output_tokens", 0) for e in self._usage_log)
        return {
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "total_calls": len(self._usage_log),
        }


# Shared singleton instance
_llm_client_instance = None


def get_llm_client() -> LLMClient:
    """Returns the shared LLMClient singleton instance."""
    global _llm_client_instance
    if _llm_client_instance is None:
        _llm_client_instance = LLMClient()
    return _llm_client_instance
