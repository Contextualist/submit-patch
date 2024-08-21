from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

import litestar
from litestar import Response
from litestar.enums import RequestEncodingType
from litestar.exceptions import (
    HTTPException,
    NotAuthorizedException,
    NotFoundException,
    PermissionDeniedException,
    ValidationException,
)
from litestar.params import Body
from litestar.response import Redirect, Template
from uuid6 import uuid7

from config import TURNSTILE_SECRET_KEY, TURNSTILE_SITE_KEY, UTC
from server.base import BadRequestException, Request, http_client, pg
from server.model import Patch, Wiki


@litestar.get("/suggest")
async def suggest_ui(request: Request, subject_id: int = 0) -> Response[Any]:
    if subject_id == 0:
        return Template("select-subject.html.jinja2")

    if not request.auth:
        request.set_session({"backTo": request.url.path + f"?subject_id={subject_id}"})
        return Redirect("/login")

    res = await http_client.get(f"https://next.bgm.tv/p1/wiki/subjects/{subject_id}")
    if res.status_code >= 300:
        raise NotFoundException()
    data = res.json()
    return Template(
        "suggest.html.jinja2",
        context={"data": data, "subject_id": subject_id, "CAPTCHA_SITE_KEY": TURNSTILE_SITE_KEY},
    )


@dataclass(frozen=True, slots=True)
class CreateSuggestion:
    name: str
    infobox: str
    summary: str
    desc: str
    cf_turnstile_response: str
    # HTML form will only include checkbox when it's checked,
    # so any input is true, default value is false.
    nsfw: str | None = None


@litestar.post("/suggest")
async def suggest_api(
    subject_id: int,
    data: Annotated[CreateSuggestion, Body(media_type=RequestEncodingType.URL_ENCODED)],
    request: Request,
) -> Redirect:
    if not request.auth:
        raise PermissionDeniedException
    if request.auth.allow_edit:
        raise PermissionDeniedException

    if not data.desc:
        raise ValidationException("missing suggestion description")

    res = await http_client.post(
        "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        data={
            "secret": TURNSTILE_SECRET_KEY,
            "response": data.cf_turnstile_response,
        },
    )
    if res.status_code > 300:
        raise BadRequestException("验证码无效")
    captcha_data = res.json()
    if captcha_data.get("success") is not True:
        raise BadRequestException("验证码无效")

    res = await http_client.get(f"https://next.bgm.tv/p1/wiki/subjects/{subject_id}")
    res.raise_for_status()
    original_wiki = res.json()

    original = Wiki(
        name=original_wiki["name"],
        infobox=original_wiki["infobox"],
        summary=original_wiki["summary"],
        nsfw=original_wiki["nsfw"],
    )

    name: str | None = None
    summary: str | None = None
    infobox: str | None = None

    original_summary: str | None = None
    original_infobox: str | None = None

    nsfw: bool | None = None

    if original.name != data.name:
        name = data.name

    if original.infobox != data.infobox:
        infobox = data.infobox
        original_infobox = original.infobox

    if original.summary != data.summary:
        summary = data.summary
        original_summary = original.summary

    if original.nsfw != (data.nsfw is not None):  # true case
        nsfw = not original.nsfw

    if (name is None) and (summary is None) and (infobox is None) and (nsfw is None):
        raise HTTPException("no changes found", status_code=400)

    pk = uuid7()

    await pg.execute(
        """
        insert into patch (id, subject_id, from_user_id, description, name, infobox, summary, nsfw,
                           original_name, original_infobox, original_summary, subject_type)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        returning patch.id
    """,
        pk,
        subject_id,
        request.auth.user_id,
        data.desc,
        name,
        infobox,
        summary,
        nsfw,
        original.name,
        original_infobox,
        original_summary,
        original_wiki["typeID"],
    )

    return Redirect(f"/patch/{pk}")


@litestar.post("/api/delete-patch/{patch_id:str}")
async def delete_patch(patch_id: str, request: Request) -> Redirect:
    if not request.auth:
        raise NotAuthorizedException

    async with pg.acquire() as conn:
        async with conn.transaction():
            p = await conn.fetchrow(
                """select * from patch where id = $1 and deleted_at is NULL""", patch_id
            )
            if not p:
                raise NotFoundException()

            patch = Patch(**p)

            if patch.from_user_id != request.auth.user_id:
                raise NotAuthorizedException

            await conn.execute(
                "update patch set deleted_at = $1 where id = $2 ",
                datetime.now(tz=UTC),
                patch_id,
            )

            return Redirect("/")
