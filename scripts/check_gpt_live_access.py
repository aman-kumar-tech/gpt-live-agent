"""Step 0 spike: confirm the OpenAI account has GPT-Live alpha access.

This must pass before any other build work is worth doing, since the whole
voice architecture in the plan is built around GPT-Live. Run with:

    OPENAI_API_KEY=sk-... python scripts/check_gpt_live_access.py

It makes a minimal, side-effect-free check against /v1/models to see whether
gpt-live-1 is listed for this account/key, then (if listed) attempts a
same-condition read on GPT-Live-specific session creation to surface any
403/gated-access error explicitly, without needing a real WebRTC/SDP offer.
"""

from __future__ import annotations

import os
import sys

import httpx

OPENAI_API_BASE = "https://api.openai.com/v1"
MODEL_ID = "gpt-live-1"


def main() -> int:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY is not set. Set it and re-run.", file=sys.stderr)
        return 2

    headers = {"Authorization": f"Bearer {api_key}"}

    with httpx.Client(base_url=OPENAI_API_BASE, headers=headers, timeout=15.0) as client:
        print(f"Checking model listing for '{MODEL_ID}'...")
        resp = client.get("/models")
        if resp.status_code != 200:
            print(f"FAIL: /v1/models returned {resp.status_code}: {resp.text}")
            return 1

        model_ids = {m.get("id") for m in resp.json().get("data", [])}
        if MODEL_ID in model_ids:
            print(f"OK: '{MODEL_ID}' is listed for this account.")
        else:
            print(
                f"'{MODEL_ID}' is NOT listed in /v1/models for this account "
                "(this endpoint doesn't always reflect gated/alpha models, so "
                "this alone isn't conclusive -- continuing to the session check)."
            )

        print("Checking /v1/live/sessions access (expect a validation error, not an auth/gate error)...")
        resp = client.post(
            "/live/sessions",
            json={"session": {"model": MODEL_ID, "instructions": "Be concise."}},
        )
        print(f"Status: {resp.status_code}")
        print(f"Body: {resp.text[:2000]}")

        if resp.status_code in (401, 403):
            print(
                "\nFAIL: account/key does not have GPT-Live access "
                "(401/403). This is the hard blocker flagged in the plan -- "
                "either request GPT-Live alpha access, or fall back to the "
                "standard LiveKit pipeline (STT -> LangGraph -> TTS) noted "
                "in the plan's risk #1."
            )
            return 1
        if resp.status_code == 404:
            print(
                "\nFAIL: /v1/live/sessions doesn't exist for this account -- "
                "GPT-Live is likely not enabled at all."
            )
            return 1

        print(
            "\nLikely OK: got a non-auth-gate response (probably a request "
            "validation error since no real transport/sdp was supplied, "
            "which is expected for this side-effect-free check). GPT-Live "
            "access appears to be available."
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
