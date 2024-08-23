import difflib
import uuid
from typing import Any

import litestar
from litestar.exceptions import InternalServerException, NotFoundException
from litestar.response import Template
from loguru import logger

from server.base import Request, pg
from server.model import Patch, PatchState
from server.router import Router


router = Router()


@router
@litestar.get("/patch/{patch_id:uuid}")
async def get_patch(patch_id: uuid.UUID, request: Request) -> Template:
    p = await pg.fetchrow(
        """select * from patch where id = $1 and deleted_at is NULL limit 1""", patch_id
    )
    if not p:
        raise NotFoundException()

    patch = Patch(**p)

    name_patch = __try_diff(patch_id, patch.original_name, patch.name, "name")
    infobox_patch = __try_diff(patch_id, patch.original_infobox, patch.infobox, "infobox", n=5)
    summary_patch = __try_diff(patch_id, patch.original_summary, patch.summary, "summary")

    reviewer = None
    edited = dict(name_patch="", infobox_patch="", summary_patch="")
    if patch.state != PatchState.Pending:
        reviewer = await pg.fetchrow(
            "select * from patch_users where user_id=$1", patch.wiki_user_id
        )
        edited = dict(
            name_patch=__try_diff(patch_id, patch.name, patch.edited_name, "name"),
            infobox_patch=__try_diff(patch_id, patch.infobox, patch.edited_infobox, "infobox", n=5),
            summary_patch=__try_diff(patch_id, patch.summary, patch.edited_summary, "summary"),
        )

    submitter = await pg.fetchrow("select * from patch_users where user_id=$1", patch.from_user_id)

    return Template(
        "patch.html.jinja2",
        context={
            "patch": p,
            "edited": edited,
            "auth": request.auth,
            "name_patch": name_patch,
            "infobox_patch": infobox_patch,
            "summary_patch": summary_patch,
            "reviewer": reviewer,
            "submitter": submitter,
        },
    )


def __try_diff(
    patch_id: uuid.UUID, before: str | None, after: str | None, name: str, **kwargs: Any
) -> str:
    if after is None:
        return ""
    if before is None:
        logger.error("broken patch {!r}", patch_id)
        raise InternalServerException
    return "".join(
        # need a tailing new line to generate correct diff
        difflib.unified_diff(
            (before + "\n").splitlines(True),
            (after + "\n").splitlines(True),
            name,
            name,
            **kwargs,
        )
    )


@router
@litestar.get("/episode/{patch_id:uuid}")
async def get_episode_patch(patch_id: uuid.UUID, request: Request) -> Template:
    p = await pg.fetchrow(
        """select * from episode_patch where id = $1 and deleted_at is NULL limit 1""", patch_id
    )
    if not p:
        raise NotFoundException()

    diff = {}

    keys = {
        "name": "标题",
        "name_cn": "简体中文标题",
        "duration": "时长",
        "airdate": "放送日期",
        "description": "简介",
    }

    for key, cn in keys.items():
        after = p[key]
        if after is None:
            continue

        original = p["original_" + key]

        if original != after:
            diff[(key, cn)] = "".join(
                # need a tailing new line to generate correct diff
                difflib.unified_diff(
                    (original + "\n").splitlines(True),
                    (after + "\n").splitlines(True),
                    key,
                    key,
                )
            )

    reviewer = None
    if p["state"] != PatchState.Pending:
        reviewer = await pg.fetchrow(
            "select * from patch_users where user_id=$1", p["wiki_user_id"]
        )

    submitter = await pg.fetchrow("select * from patch_users where user_id=$1", p["from_user_id"])

    return Template(
        "episode/patch.html.jinja2",
        context={
            "patch": p,
            "auth": request.auth,
            "diff": diff,
            "reviewer": reviewer,
            "submitter": submitter,
        },
    )
