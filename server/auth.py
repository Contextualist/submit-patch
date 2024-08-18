from typing import Any
from urllib.parse import urlencode

import litestar
from litestar.connection import ASGIConnection
from litestar.exceptions import InternalServerException, NotAuthorizedException
from litestar.middleware import AuthenticationResult
from litestar.middleware.session.server_side import (
    ServerSideSessionBackend,
    ServerSideSessionConfig,
)
from litestar.response import Redirect
from litestar.security.session_auth import SessionAuth, SessionAuthMiddleware
from litestar.types import Empty

from config import BGM_TV_APP_ID, BGM_TV_APP_SECRET, SERVER_BASE_URL
from server.base import http_client
from server.model import User


CALLBACK_URL = f"{SERVER_BASE_URL}/oauth_callback"


async def retrieve_user_from_session(session: dict[str, Any], _: ASGIConnection) -> User | None:
    return User(user_id=session["user_id"], group_id=session["group_id"])


class MyAuthenticationMiddleware(SessionAuthMiddleware):
    async def authenticate_request(self, connection: ASGIConnection) -> AuthenticationResult:
        if not connection.session or connection.scope["session"] is Empty:
            # the assignment of 'Empty' forces the session middleware to clear session data.
            connection.scope["session"] = Empty
            return AuthenticationResult(user=None, auth=None)

        user = await retrieve_user_from_session(connection.session, connection)

        return AuthenticationResult(user=user, auth=user)


session_auth_config = SessionAuth[User, ServerSideSessionBackend](
    retrieve_user_handler=retrieve_user_from_session,
    session_backend_config=ServerSideSessionConfig(),
    authentication_middleware_class=MyAuthenticationMiddleware,
)


@litestar.get("/login", sync_to_thread=False)
def login() -> Redirect:
    return Redirect(
        "https://bgm.tv/oauth/authorize?"
        + urlencode(
            {
                "client_id": BGM_TV_APP_ID,
                "response_type": "code",
                "redirect_uri": CALLBACK_URL,
            }
        )
    )


@litestar.get("/oauth_callback")
async def callback(code: str, request: litestar.Request) -> Redirect:
    async with http_client.post(
        "https://bgm.tv/oauth/access_token",
        data={
            "code": code,
            "client_id": BGM_TV_APP_ID,
            "grant_type": "authorization_code",
            "redirect_uri": CALLBACK_URL,
            "client_secret": BGM_TV_APP_SECRET,
        },
    ) as res:
        if res.status >= 300:
            raise InternalServerException("api request error")
        data = await res.json()

    user_id = data["user_id"]
    access_token = data["access_token"]

    async with http_client.get(
        "https://api.bgm.tv/v0/me",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as res:
        if res.status >= 300:
            raise InternalServerException("api request error")
        user = await res.json()

    group_id = user["user_group"]

    request.set_session({"user_id": user_id, "group_id": group_id})

    return Redirect("/")


def require_user_editor(connection: ASGIConnection, _):
    if not connection.auth:
        raise NotAuthorizedException
    if not connection.auth.allow_edit:
        raise NotAuthorizedException
