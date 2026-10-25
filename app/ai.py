"""Ollama access restricted to a numeric loopback address and local model weights."""
import os
from urllib.parse import urlsplit
import httpx


def base_url():
    url = os.environ.get("SULTAN_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    parts = urlsplit(url)
    if parts.scheme != "http" or parts.hostname not in ("127.0.0.1", "::1") or parts.username or parts.password or parts.path or parts.query or parts.fragment:
        raise ValueError("SULTAN_OLLAMA_URL must be a numeric loopback HTTP address, such as http://127.0.0.1:11434.")
    return url


def _local(model):
    return bool(model.get("name")) and "cloud" not in model["name"].lower() and not model.get("remote_host") and not model.get("remote_model") and model.get("size", 0) > 0


def models():
    try:
        with httpx.Client(trust_env=False, timeout=4) as client:
            response = client.get(base_url() + "/api/tags")
            response.raise_for_status()
            return [m["name"] for m in response.json().get("models", []) if _local(m)]
    except (httpx.HTTPError, ValueError):
        return []


def generate(vault, messages, json_mode=False):
    vault.check_unlocked()
    model = vault.settings().get("model", "")
    if not model:
        raise RuntimeError("Choose an installed local model in Settings first. Install Ollama and run: ollama pull qwen3.5:4b")
    if model not in models():
        raise RuntimeError("The selected local model is unavailable. Start Ollama and choose an installed model in Settings.")
    try:
        with httpx.Client(trust_env=False, timeout=300) as client:
            shown = client.post(base_url() + "/api/show", json={"model": model})
            shown.raise_for_status()
            info = shown.json()
            if info.get("remote_host") or info.get("remote_model") or not info.get("model_info"):
                raise RuntimeError("Cloud or unverifiable models are blocked. Select a downloaded local model.")
            payload = {"model": model, "messages": messages, "stream": False, "keep_alive": 0,
                       "options": {"num_ctx": 16384, "num_predict": 2048, "temperature": 0.3}}
            if 'thinking' in info.get('capabilities',[]):
                payload['think'] = False
            if json_mode:
                payload["format"] = "json"
            response = client.post(base_url() + "/api/chat", json=payload)
            response.raise_for_status()
            reply = response.json().get("message", {}).get("content", "").strip()
            if not reply:
                raise RuntimeError("The model returned no text. Try a different local model.")
            vault.check_unlocked()
            return reply
    except httpx.TimeoutException:
        raise RuntimeError("The local model timed out. Try a smaller model or a shorter input.") from None
    except httpx.HTTPError:
        raise RuntimeError("Ollama could not complete this request. Check that it is running and the model fits your computer.") from None
