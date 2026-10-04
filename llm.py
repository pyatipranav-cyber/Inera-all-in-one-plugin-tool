"""AI engine adapter.

Supports a fully self-hosted engine (Ollama), any OpenAI-compatible endpoint
(OpenAI, Groq, Together, LM Studio, vLLM ...) and Anthropic. When no engine is
configured the platform still works: every plugin has an offline path built on
the extractive text engine in textkit.py.
"""
import json
import re
import threading
import time

import httpx

import config


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self):
        self._lock = threading.Lock()
        self._ollama_ok = None
        self._ollama_checked = 0.0
        self.last_error = ""

    # ------------------------------------------------------------ status
    def _ollama_available(self) -> bool:
        with self._lock:
            if time.time() - self._ollama_checked < 60 and self._ollama_ok is not None:
                return self._ollama_ok
            ok = False
            try:
                r = httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=2.5)
                ok = r.status_code == 200
            except httpx.HTTPError:
                ok = False
            self._ollama_ok, self._ollama_checked = ok, time.time()
            return ok

    def provider(self) -> str:
        p = config.LLM_PROVIDER
        if p == "none":
            return "none"
        if p == "anthropic":
            return "anthropic" if config.ANTHROPIC_API_KEY else "none"
        if p == "openai":
            return "openai" if config.OPENAI_API_KEY or "localhost" in config.OPENAI_BASE_URL else "none"
        if p == "ollama":
            return "ollama" if self._ollama_available() else "none"
        # auto
        if config.ANTHROPIC_API_KEY:
            return "anthropic"
        if config.OPENAI_API_KEY:
            return "openai"
        if self._ollama_available():
            return "ollama"
        return "none"

    def available(self) -> bool:
        return self.provider() != "none"

    def describe(self) -> dict:
        p = self.provider()
        model = {"anthropic": config.ANTHROPIC_MODEL, "openai": config.OPENAI_MODEL,
                 "ollama": config.OLLAMA_MODEL}.get(p, "")
        return {"provider": p, "model": model, "online": p != "none",
                "label": f"{p.title()} · {model}" if p != "none" else "Offline engine"}

    # ------------------------------------------------------------ calls
    def complete(self, prompt: str, system: str = "", max_tokens: int = 2000,
                 temperature: float = 0.5, json_mode: bool = False) -> str:
        p = self.provider()
        if p == "none":
            raise LLMError("No AI engine configured.")
        try:
            if p == "anthropic":
                return self._anthropic(prompt, system, max_tokens, temperature)
            if p == "openai":
                return self._openai(prompt, system, max_tokens, temperature, json_mode)
            return self._ollama(prompt, system, max_tokens, temperature, json_mode)
        except httpx.HTTPError as exc:
            self.last_error = str(exc)
            raise LLMError(f"AI engine request failed: {exc}") from exc

    def complete_json(self, prompt: str, system: str = "", max_tokens: int = 3000,
                      temperature: float = 0.3):
        sys = (system + "\n\n" if system else "") + (
            "Respond with ONE valid JSON value only. No markdown fences, no commentary.")
        text = self.complete(prompt, sys, max_tokens, temperature, json_mode=True)
        data = extract_json(text)
        if data is None:
            # one repair attempt
            text = self.complete("Convert the following into valid JSON only:\n\n" + text[:12000],
                                 "You fix JSON. Output JSON only.", max_tokens, 0, json_mode=True)
            data = extract_json(text)
        if data is None:
            raise LLMError("AI engine did not return valid JSON.")
        return data

    def _anthropic(self, prompt, system, max_tokens, temperature):
        body = {"model": config.ANTHROPIC_MODEL, "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}]}
        if system:
            body["system"] = system
        r = httpx.post("https://api.anthropic.com/v1/messages", json=body, timeout=config.LLM_TIMEOUT,
                       headers={"x-api-key": config.ANTHROPIC_API_KEY,
                                "anthropic-version": "2023-06-01",
                                "content-type": "application/json"})
        if r.status_code >= 400:
            raise LLMError(f"Anthropic error {r.status_code}: {r.text[:300]}")
        data = r.json()
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")

    def _openai(self, prompt, system, max_tokens, temperature, json_mode):
        msgs = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}]
        body = {"model": config.OPENAI_MODEL, "messages": msgs, "max_tokens": max_tokens,
                "temperature": temperature}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if config.OPENAI_API_KEY:
            headers["Authorization"] = f"Bearer {config.OPENAI_API_KEY}"
        r = httpx.post(f"{config.OPENAI_BASE_URL}/chat/completions", json=body, headers=headers,
                       timeout=config.LLM_TIMEOUT)
        if r.status_code == 400 and json_mode:  # some compatible servers reject response_format
            body.pop("response_format", None)
            r = httpx.post(f"{config.OPENAI_BASE_URL}/chat/completions", json=body, headers=headers,
                           timeout=config.LLM_TIMEOUT)
        if r.status_code >= 400:
            raise LLMError(f"OpenAI-compatible error {r.status_code}: {r.text[:300]}")
        return r.json()["choices"][0]["message"]["content"] or ""

    def _ollama(self, prompt, system, max_tokens, temperature, json_mode):
        msgs = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}]
        body = {"model": config.OLLAMA_MODEL, "messages": msgs, "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens}}
        if json_mode:
            body["format"] = "json"
        r = httpx.post(f"{config.OLLAMA_URL}/api/chat", json=body, timeout=config.LLM_TIMEOUT)
        if r.status_code >= 400:
            raise LLMError(f"Ollama error {r.status_code}: {r.text[:300]}")
        return r.json().get("message", {}).get("content", "")


def extract_json(text: str):
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except ValueError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start = text.find(open_c)
        end = text.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                continue
    return None


engine = LLM()
