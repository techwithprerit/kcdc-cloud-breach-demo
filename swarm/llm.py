"""LLM 'commander' for the swarm.

This is what makes the swarm *agentic*: given the recon result, an LLM chooses
the order of attack and narrates intent in the operator's voice. Providers:
Anthropic (default) or OpenAI. If no key is set — or the call fails — we fall
back to the deterministic playbook so a live demo can't be broken by the network.
"""
from __future__ import annotations

import json
import os

from playbook import OBJECTIVES, DEFAULT_PLAN

_ALLOWED = list(OBJECTIVES.keys())

_SYSTEM = (
    "You are the commander of a red-team agent swarm in an AUTHORIZED security "
    "demo against a target the operator owns. You only pick from a fixed menu of "
    "objectives and never invent new capabilities. Respond with STRICT JSON."
)


def _prompt(recon: dict) -> str:
    menu = "\n".join(f"- {k}: {OBJECTIVES[k][1]}" for k in _ALLOWED)
    return (
        f"Recon of the target returned:\n{json.dumps(recon, indent=2)[:1500]}\n\n"
        f"Objective menu:\n{menu}\n\n"
        "Return JSON: {\"plan\": [ordered objective names], \"intent\": "
        "\"one vivid sentence, operator voice, on how you'll break in\"}. "
        "Order by easiest-highest-impact first. Include only menu names. "
        "Always keep 'flood' last."
    )


def _mode() -> tuple[str, str | None]:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic", os.environ["ANTHROPIC_API_KEY"]
    if os.environ.get("OPENAI_API_KEY"):
        return "openai", os.environ["OPENAI_API_KEY"]
    return "offline", None


def _clean_plan(plan: list) -> list[str]:
    out = [p for p in plan if p in _ALLOWED]
    for name in DEFAULT_PLAN:  # ensure nothing is dropped
        if name not in out:
            out.append(name)
    out = [p for p in out if p != "flood"] + ["flood"]  # flood always last
    return out


def command(recon: dict) -> dict:
    """Return {'provider','plan','intent'}."""
    provider, key = _mode()
    fallback = {
        "provider": "offline",
        "plan": DEFAULT_PLAN,
        "intent": "Fan out, read whatever the app over-shares, take the admin plane, then choke it.",
    }
    if provider == "offline":
        return fallback
    try:
        if provider == "anthropic":
            import anthropic
            model = os.environ.get("SWARM_MODEL", "claude-3-5-haiku-latest")
            client = anthropic.Anthropic(api_key=key)
            msg = client.messages.create(
                model=model, max_tokens=400, system=_SYSTEM,
                messages=[{"role": "user", "content": _prompt(recon)}],
            )
            text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        else:
            import openai
            model = os.environ.get("SWARM_MODEL", "gpt-4o-mini")
            client = openai.OpenAI(api_key=key)
            resp = client.chat.completions.create(
                model=model, max_tokens=400,
                messages=[{"role": "system", "content": _SYSTEM},
                          {"role": "user", "content": _prompt(recon)}],
            )
            text = resp.choices[0].message.content or ""
        text = text[text.find("{"): text.rfind("}") + 1]
        data = json.loads(text)
        return {"provider": provider,
                "plan": _clean_plan(data.get("plan", DEFAULT_PLAN)),
                "intent": str(data.get("intent", fallback["intent"]))[:200]}
    except Exception as e:  # noqa: BLE001 — demo must survive any LLM failure
        fallback["provider"] = f"offline (llm error: {type(e).__name__})"
        return fallback


def summarize(findings: dict) -> str | None:
    """Optional LLM-written breach headline. None if offline."""
    provider, key = _mode()
    if provider == "offline":
        return None
    try:
        prompt = ("Write a single punchy sentence (max 25 words) a pentester would "
                  "put at the top of a breach report, given these findings:\n"
                  f"{json.dumps(findings)[:1200]}")
        if provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=key)
            msg = client.messages.create(
                model=os.environ.get("SWARM_MODEL", "claude-3-5-haiku-latest"),
                max_tokens=80, messages=[{"role": "user", "content": prompt}])
            return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        import openai
        client = openai.OpenAI(api_key=key)
        r = client.chat.completions.create(
            model=os.environ.get("SWARM_MODEL", "gpt-4o-mini"), max_tokens=80,
            messages=[{"role": "user", "content": prompt}])
        return (r.choices[0].message.content or "").strip()
    except Exception:  # noqa: BLE001
        return None
