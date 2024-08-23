create table if not exists patch_scheme_rev
(
    version text primary key
);

create table if not exists patch
(
    id               uuid PRIMARY KEY     DEFAULT gen_random_uuid(),
    subject_id       int         not null,
    -- 0 pending
    -- 1 approved
    -- 2 rejected
    -- 3 out-dated
    state            int         not null default 0,
    from_user_id     int         not null,           -- from user XXX
    wiki_user_id     int         not null default 0, -- approved/rejected by user XXX
    -- why we should make this change
    description      text        not null,
    name             TEXT                 default null,
    original_name    TEXT                 default null,
    edited_name      TEXT                 default null,
    infobox          TEXT                 default null,
    original_infobox TEXT                 default null,
    edited_infobox   TEXT                 default null,
    summary          TEXT                 default null,
    original_summary TEXT                 default null,
    edited_summary   TEXT                 default null,
    nsfw             bool                 default null,
    edited_nsfw      bool                 default null,
    edited_reason    TEXT                 default null,
    created_at       timestamptz not null default current_timestamp,
    updated_at       timestamptz not null default current_timestamp,
    deleted_at       timestamptz          default null
);

create index idx_subject_id on patch (subject_id);

create index idx_deleted_at on patch (deleted_at);

alter table patch
    add column reject_reason varchar(255) not null default '';

alter table patch
    add column subject_type int8 not null default 0;

alter table patch
    ALTER column original_name set default '';
    
alter table patch
    add column edited_name TEXT;
alter table patch
    add column edited_infobox TEXT;
alter table patch
    add column edited_summary TEXT;
alter table patch
    add column edited_nsfw bool;
alter table patch
    add column edited_reason varchar(255);

update patch
set original_name = ''
where original_name is NULL;

alter table patch
    ALTER column original_name set not null;

create table if not exists patch_users
(
    user_id  int PRIMARY KEY not null,
    username varchar(255)    not null,
    nickname varchar(255)    not null
);

alter table patch
    RENAME column description to reason;

create table if not exists patch_db_migration
(
    key   text primary key,
    value text
)
