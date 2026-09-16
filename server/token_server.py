"""Mints a LiveKit room-join JWT for the browser demo. LiveKit auto-dispatches
the running worker (worker.py) into any new room, so the browser client just
needs a token to join -- no explicit dispatch rule required for this path."""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from livekit import api
from pydantic import BaseModel

from receptionist.config import settings
from receptionist.db.engine import get_session_factory
from receptionist.db.repositories import lab_info as lab_info_repo

app = FastAPI(title="Receptionist token server")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class BrandingResponse(BaseModel):
    agent_name: str
    lab_name: str


@app.get("/api/branding", response_model=BrandingResponse)
async def get_branding() -> BrandingResponse:
    """The frontend never hardcodes the agent's or lab's name -- both are
    config/DB-driven, so re-skinning the demo is a data change, not a
    frontend code change."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        lab = await lab_info_repo.get_lab_info(session)

    return BrandingResponse(agent_name=settings.agent_name, lab_name=lab.name if lab else "the lab")


class TokenRequest(BaseModel):
    full_name: str | None = None
    phone_number: str | None = None


class TokenResponse(BaseModel):
    token: str
    url: str
    room: str


@app.post("/api/token", response_model=TokenResponse)
async def create_token(body: TokenRequest = TokenRequest()) -> TokenResponse:
    room = f"receptionist-demo-{uuid.uuid4().hex[:8]}"
    identity = f"caller-{uuid.uuid4().hex[:8]}"

    token_builder = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity)
        .with_name("Caller")
        .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True))
    )
    attributes = {}
    if body.full_name:
        attributes["full_name"] = body.full_name
    if body.phone_number:
        attributes["phone_number"] = body.phone_number
    if attributes:
        # Read by worker.py's entrypoint and seeded onto CallState, so the
        # agent greets the caller by name and doesn't re-ask for either.
        token_builder = token_builder.with_attributes(attributes)

    return TokenResponse(token=token_builder.to_jwt(), url=settings.livekit_url, room=room)
