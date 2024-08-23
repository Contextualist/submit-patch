from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

import litestar
import pydash
from asyncpg import Record
from asyncpg.pool import PoolConnectionProxy
from dacite import from_dict
from litestar import Controller, Response
from litestar.enums import RequestEncodingType
from litestar.exceptions import InternalServerException, NotAuthorizedException, NotFoundException
from litestar.params import Body
from litestar.response import Redirect
from loguru import logger

from config import UTC
from server.auth import require_user_editor
from server.base import AuthorizedRequest, BadRequestException, User, http_client, pg
from server.model import EpisodePatch, Patch, PatchState
from server.router import Router


router = Router()


class React(str, enum.Enum):
    Accept = "accept"
    Reject = "reject"


@dataclass
class ReviewPatch:
    react: React
    reject_reason: str = ""
    edited_name: str = ""
    edited_infobox: str = ""
    edited_summary: str = ""
    edited_nsfw: bool = False
    edited_reason: str = ""


def _strip_none(d: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in d.items() if value is not None}


@router
@litestar.post("/api/review-patch/{patch_id:str}", guards=[require_user_editor])
async def review_patch(
    patch_id: str,
    request: AuthorizedRequest,
    data: Annotated[ReviewPatch, Body(media_type=RequestEncodingType.URL_ENCODED)],
) -> Response[Any]:
    async with pg.acquire() as conn:
        async with conn.transaction():
            p = await pg.fetchrow(
                """select * from patch where id = $1 and deleted_at is NULL FOR UPDATE""", patch_id
            )
            if not p:
                raise NotFoundException()

            patch = Patch(**p)

            if patch.state != PatchState.Pending:
                raise BadRequestException("patch already reviewed")

            if data.react == React.Reject:
                return await __reject_patch(patch, conn, request.auth, data.reject_reason)

            if data.react == React.Accept:
                return await __accept_patch(patch, conn, request.auth, data)

    raise NotAuthorizedException("暂不支持")


async def __reject_patch(
    patch: Patch, conn: PoolConnectionProxy[Record], auth: User, reason: str
) -> Redirect:
    await conn.execute(
        """
        update patch set
            state = $1,
            wiki_user_id = $2,
            updated_at = $3,
            reject_reason = $4
        where id = $5 and deleted_at is NULL
        """,
        PatchState.Rejected,
        auth.user_id,
        datetime.now(tz=UTC),
        reason,
        patch.id,
    )
    return Redirect("/")


async def __accept_patch(
    patch: Patch, conn: PoolConnectionProxy[Record], auth: User, review: ReviewPatch
) -> Redirect:
    if not auth.is_access_token_fresh():
        return Redirect("/login")

    subject = _strip_none(
        {
            "infobox": review.edited_infobox,
            "name": review.edited_name,
            "summary": review.edited_summary,
            "nsfw": review.edited_nsfw,
        }
    )

    res = await http_client.patch(
        f"https://next.bgm.tv/p1/wiki/subjects/{patch.subject_id}",
        headers={"Authorization": f"Bearer {auth.access_token}"},
        json={
            "commitMessage": f"{patch.reason} [patch https://patch.bgm38.com/patch/{patch.id}]",
            "expectedRevision": pydash.pick(
                {
                    "infobox": patch.original_infobox,
                    "name": patch.original_name,
                    "summary": patch.original_summary,
                },
                *subject.keys(),
            ),
            "subject": subject,
        },
    )
    if res.status_code >= 300:
        data = res.json()
        if data.get("code") == "SUBJECT_CHANGED":
            await conn.execute(
                """
                            update patch set
                                state = $1,
                                wiki_user_id = $2,
                                updated_at = $3
                            where id = $4 and deleted_at is NULL
                            """,
                PatchState.Outdated,
                auth.user_id,
                datetime.now(tz=UTC),
                patch.id,
            )
            return Redirect(f"/patch/{patch.id}")

        logger.error("failed to apply patch {!r}", data)
        raise InternalServerException()

    await conn.execute(
        """
                update patch set
                    state = $1,
                    wiki_user_id = $2,
                    updated_at = $3
                    edited_name = $4,
                    edited_infobox = $5,
                    edited_summary = $6,
                    edited_nsfw = $7,
                    edited_reason = $8
                where id = $9 and deleted_at is NULL
                """,
        PatchState.Accept,
        auth.user_id,
        datetime.now(tz=UTC),
        (review.edited_name if review.edited_name != patch.name else None),
        (review.edited_infobox if review.edited_infobox != patch.infobox else None),
        (review.edited_summary if review.edited_summary != patch.summary else None),
        (review.edited_nsfw if review.edited_nsfw != patch.nsfw else None),
        (review.edited_reason if review.edited_reason else None),
        patch.id,
    )
    return Redirect(f"/patch/{patch.id}")


@router
class EpisodeReviewController(Controller):
    @litestar.post("/api/review-episode/{patch_id:uuid}")
    async def review_episode_patch(
        self,
        patch_id: uuid.UUID,
        request: AuthorizedRequest,
        data: Annotated[ReviewPatch, Body(media_type=RequestEncodingType.URL_ENCODED)],
    ) -> Response[Any]:
        async with pg.acquire() as conn:
            async with conn.transaction():
                p = await pg.fetchrow(
                    """select * from episode_patch where id = $1 and deleted_at is NULL FOR UPDATE""",
                    patch_id,
                )
                if not p:
                    raise NotFoundException()

                if p["state"] != PatchState.Pending:
                    raise BadRequestException("patch already reviewed")

                if data.react == React.Reject:
                    return await self.__reject_episode_patch(
                        patch_id, conn, request.auth, data.reject_reason
                    )

                if data.react == React.Accept:
                    patch = from_dict(EpisodePatch, p)  # type: ignore
                    return await self.__accept_episode_patch(patch, conn, request.auth)

        raise NotAuthorizedException("暂不支持")

    async def __reject_episode_patch(
        self, patch_id: uuid.UUID, conn: PoolConnectionProxy[Record], auth: User, reason: str
    ) -> Redirect:
        await conn.execute(
            """
            update episode_patch set
                state = $1,
                wiki_user_id = $2,
                updated_at = $3,
                reject_reason = $4
            where id = $5 and deleted_at is NULL
            """,
            PatchState.Rejected,
            auth.user_id,
            datetime.now(tz=UTC),
            reason,
            patch_id,
        )
        return Redirect("/")

    async def __accept_episode_patch(
        self, patch: EpisodePatch, conn: PoolConnectionProxy[Record], auth: User
    ) -> Redirect:
        if not auth.is_access_token_fresh():
            return Redirect("/login")

        episode = _strip_none(
            {
                "nameCN": patch.name_cn,
                "name": patch.name,
                "summary": patch.description,
                "duration": patch.duration,
                "airdate": patch.airdate,
            }
        )

        res = await http_client.patch(
            f"https://next.bgm.tv/p1/wiki/ep/{patch.episode_id}",
            headers={"Authorization": f"Bearer {auth.access_token}"},
            json={
                "commitMessage": f"{patch.description} [patch https://patch.bgm38.tv/patch/{patch.id}]",
                "expectedRevision": pydash.pick(
                    {
                        "nameCN": patch.original_name_cn,
                        "name": patch.original_name,
                        "summary": patch.original_description,
                        "duration": patch.original_duration,
                        "airdate": patch.original_airdate,
                    },
                    *episode.keys(),
                ),
                "episode": episode,
            },
        )
        if res.status_code >= 300:
            data = res.json()
            if data.get("code") == "SUBJECT_CHANGED":
                await conn.execute(
                    """
                    update episode_patch set
                        state = $1,
                        wiki_user_id = $2,
                        updated_at = $3
                    where id = $4 and deleted_at is NULL
                    """,
                    PatchState.Outdated,
                    auth.user_id,
                    datetime.now(tz=UTC),
                    patch.id,
                )
                return Redirect(f"/episode/{patch.id}")

            logger.error("failed to apply patch {!r}", data)
            raise InternalServerException()

        await conn.execute(
            """
            update episode_patch set
                state = $1,
                wiki_user_id = $2,
                updated_at = $3
            where id = $4 and deleted_at is NULL
            """,
            PatchState.Accept,
            auth.user_id,
            datetime.now(tz=UTC),
            patch.id,
        )
        return Redirect(f"/episode/{patch.id}")
