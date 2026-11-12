from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from manga_common.config import get_settings
from services.comments.app.config import CommentsSettings
from services.comments.app.main import create_app

INTERNAL_TOKEN = "test-internal-token"
USER_A = "11111111-1111-4111-8111-111111111111"
USER_B = "22222222-2222-4222-8222-222222222222"
USER_C = "33333333-3333-4333-8333-333333333333"
ADMIN = "44444444-4444-4444-8444-444444444444"
MANGA = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER_MANGA = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def make_client(db_path: Path, **overrides: object) -> TestClient:
    values: dict[str, object] = {
        "service_name": "comments-test",
        "environment": "test",
        "log_level": "WARNING",
        "log_json": False,
        "comments_database_url": f"sqlite+aiosqlite:///{db_path.as_posix()}",
        "internal_token": INTERNAL_TOKEN,
        "jwt_secret": "comments-test-jwt-secret",
        "comments_create_cooldown_seconds": 0,
        "comments_create_daily_limit": 1000,
        "comments_duplicate_window_seconds": 0,
        "comments_edit_window_minutes": 15,
        "comments_max_body_length": 2000,
        "comments_reply_preview_limit": 3,
    }
    values.update(overrides)
    settings = CommentsSettings(**values)  # type: ignore[arg-type]
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


@pytest.fixture()
def client(tmp_path: Path):
    with make_client(tmp_path / "comments.db") as test_client:
        yield test_client


def headers(
    user_id: str = USER_A,
    name: str = "Alice",
    role: str = "user",
    *,
    token: str = INTERNAL_TOKEN,
) -> dict[str, str]:
    return {
        "X-Internal-Token": token,
        "X-User-Id": user_id,
        "X-User-Name": name,
        "X-User-Role": role,
    }


def internal_headers(*, token: str = INTERNAL_TOKEN) -> dict[str, str]:
    return {"X-Internal-Token": token}


def create_comment(
    client: TestClient,
    *,
    manga: str = MANGA,
    body: str = "Комментарий",
    user_id: str = USER_A,
    name: str = "Alice",
    role: str = "user",
    parent_id: str | None = None,
    spoiler: bool = False,
):
    payload: dict[str, object] = {"body": body, "spoiler": spoiler}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    return client.post(
        f"/internal/manga/{manga}/comments",
        json=payload,
        headers=headers(user_id, name, role),
    )


def test_create_reply_listing_and_one_level_validation(client: TestClient) -> None:
    root = create_comment(client, body="Первый комментарий", user_id=USER_A, name="Alice")
    assert root.status_code == 201, root.text
    root_data = root.json()
    assert root_data["body"] == "Первый комментарий"
    assert root_data["user_name"] == "Alice"
    assert root_data["parent_id"] is None
    assert root_data["likes_count"] == 0
    assert root_data["replies_count"] == 0
    assert root_data["is_own"] is True
    assert root_data["can_edit"] is True

    reply = create_comment(
        client,
        body="Ответ",
        user_id=USER_B,
        name="Bob",
        parent_id=root_data["id"],
    )
    assert reply.status_code == 201, reply.text
    reply_data = reply.json()
    assert reply_data["parent_id"] == root_data["id"]
    assert reply_data["user_id"] == USER_B

    listing = client.get(
        f"/internal/manga/{MANGA}/comments",
        headers=headers(USER_B, "Bob"),
    )
    assert listing.status_code == 200, listing.text
    data = listing.json()
    assert data["total"] == 1
    assert data["page"] == 1
    assert data["limit"] == 20
    assert data["has_next"] is False
    item = data["items"][0]
    assert item["id"] == root_data["id"]
    assert item["replies_count"] == 1
    assert len(item["replies"]) == 1
    assert item["is_own"] is False
    assert item["replies"][0]["is_own"] is True
    assert item["replies"][0]["body"] == "Ответ"

    replies = client.get(
        f"/internal/comments/{root_data['id']}/replies",
        headers=headers(USER_A, "Alice"),
    )
    assert replies.status_code == 200
    assert replies.json()["total"] == 1
    assert replies.json()["items"][0]["id"] == reply_data["id"]

    other_root = create_comment(
        client, manga=OTHER_MANGA, body="Другой тайтл", user_id=USER_A
    )
    assert other_root.status_code == 201

    wrong_manga = create_comment(
        client,
        body="Ответ не туда",
        user_id=USER_B,
        parent_id=other_root.json()["id"],
    )
    assert wrong_manga.status_code == 422
    assert wrong_manga.json()["error"]["code"] == "parent_manga_mismatch"

    nested = create_comment(
        client,
        body="Ответ на ответ",
        user_id=USER_B,
        parent_id=reply_data["id"],
    )
    assert nested.status_code == 422
    assert nested.json()["error"]["code"] == "reply_depth_exceeded"

    missing = create_comment(
        client,
        body="Ответ на призрак",
        user_id=USER_B,
        parent_id=str(uuid.uuid4()),
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "parent_not_found"


def test_edit_window_permissions_and_fields(client: TestClient, tmp_path: Path) -> None:
    root = create_comment(client, body="До редактирования", user_id=USER_A)
    assert root.status_code == 201
    comment_id = root.json()["id"]

    other = client.patch(
        f"/internal/comments/{comment_id}",
        json={"body": "Чужое изменение"},
        headers=headers(USER_B, "Bob"),
    )
    assert other.status_code == 403
    assert other.json()["error"]["code"] == "not_author"

    admin = client.patch(
        f"/internal/comments/{comment_id}",
        json={"body": "Модератор тоже не редактирует"},
        headers=headers(ADMIN, "Admin", "admin"),
    )
    assert admin.status_code == 403

    edited = client.patch(
        f"/internal/comments/{comment_id}",
        json={"body": "После редактирования", "spoiler": True},
        headers=headers(USER_A),
    )
    assert edited.status_code == 200, edited.text
    data = edited.json()
    assert data["body"] == "После редактирования"
    assert data["spoiler"] is True
    assert data["edited_at"] is not None

    empty = client.patch(
        f"/internal/comments/{comment_id}",
        json={"body": "   \n\t  "},
        headers=headers(USER_A),
    )
    assert empty.status_code == 422
    assert empty.json()["error"]["code"] == "empty_body"

    with make_client(tmp_path / "expired.db", comments_edit_window_minutes=0) as expired:
        created = create_comment(expired, body="Очень старое")
        expired_edit = expired.patch(
            f"/internal/comments/{created.json()['id']}",
            json={"body": "Поздно"},
            headers=headers(USER_A),
        )
        assert expired_edit.status_code == 403
        assert expired_edit.json()["error"]["code"] == "edit_window_expired"


def test_delete_permissions_soft_delete_and_reply_hiding(client: TestClient) -> None:
    root = create_comment(client, body="Удаляемый", user_id=USER_A)
    root_id = root.json()["id"]
    reply = create_comment(
        client, body="Ответ", user_id=USER_B, name="Bob", parent_id=root_id
    )
    reply_id = reply.json()["id"]

    foreign = client.delete(
        f"/internal/comments/{root_id}", headers=headers(USER_B, "Bob")
    )
    assert foreign.status_code == 403
    assert foreign.json()["error"]["code"] == "not_allowed"

    deleted = client.delete(f"/internal/comments/{root_id}", headers=headers(USER_A))
    assert deleted.status_code == 204

    listing = client.get(f"/internal/manga/{MANGA}/comments", headers=headers(USER_A))
    assert listing.json()["total"] == 0
    replies = client.get(
        f"/internal/comments/{root_id}/replies", headers=headers(USER_A)
    )
    assert replies.status_code == 404

    deleted_list = client.get(
        "/internal/admin/comments",
        params={"status": "deleted"},
        headers=headers(ADMIN, "Admin", "admin"),
    )
    assert deleted_list.status_code == 200
    assert [item["id"] for item in deleted_list.json()["items"]] == [root_id]
    assert deleted_list.json()["items"][0]["status"] == "deleted"
    assert deleted_list.json()["items"][0]["deleted_at"] is not None

    hidden_list = client.get(
        "/internal/admin/comments",
        params={"status": "hidden"},
        headers=headers(ADMIN, "Admin", "admin"),
    )
    assert hidden_list.status_code == 200
    assert [item["id"] for item in hidden_list.json()["items"]] == [reply_id]

    second_root = create_comment(client, body="Второй корень", user_id=USER_A)
    second_id = second_root.json()["id"]
    second_reply = create_comment(
        client, body="Удаляемый ответ", user_id=USER_B, parent_id=second_id
    )
    own_delete = client.delete(
        f"/internal/comments/{second_reply.json()['id']}",
        headers=headers(USER_B, "Bob"),
    )
    assert own_delete.status_code == 204
    second_listing = client.get(
        f"/internal/manga/{MANGA}/comments", headers=headers(USER_A)
    )
    assert second_listing.json()["items"][0]["replies_count"] == 0

    admin_target = create_comment(client, body="Удаление модератором", user_id=USER_A)
    admin_delete = client.delete(
        f"/internal/comments/{admin_target.json()['id']}",
        headers=headers(ADMIN, "Admin", "admin"),
    )
    assert admin_delete.status_code == 204


def test_likes_notifications_and_read_state(client: TestClient) -> None:
    root = create_comment(client, body="Лайкаемый", user_id=USER_A)
    root_id = root.json()["id"]

    liked = client.post(
        f"/internal/comments/{root_id}/like", headers=headers(USER_B, "Bob")
    )
    assert liked.status_code == 200
    assert liked.json() == {"liked": True, "likes_count": 1}

    unliked = client.post(
        f"/internal/comments/{root_id}/like", headers=headers(USER_B, "Bob")
    )
    assert unliked.json() == {"liked": False, "likes_count": 0}

    reliked = client.post(
        f"/internal/comments/{root_id}/like", headers=headers(USER_B, "Bob")
    )
    assert reliked.json() == {"liked": True, "likes_count": 1}

    notifications = client.get(
        "/internal/notifications",
        params={"unread_only": True},
        headers=headers(USER_A, "Alice"),
    )
    assert notifications.status_code == 200
    first_page = notifications.json()
    assert first_page["total"] == 1
    assert first_page["unread_count"] == 1
    like_notification = first_page["items"][0]
    assert like_notification["type"] == "like"
    assert like_notification["comment_id"] == root_id
    assert like_notification["comment"]["body"] == "Лайкаемый"
    assert like_notification["read_at"] is None

    self_like = client.post(
        f"/internal/comments/{root_id}/like", headers=headers(USER_A, "Alice")
    )
    assert self_like.json() == {"liked": True, "likes_count": 2}
    still_one = client.get(
        "/internal/notifications",
        params={"unread_only": True},
        headers=headers(USER_A, "Alice"),
    )
    assert still_one.json()["total"] == 1

    marked = client.post(
        "/internal/notifications/read",
        json={"ids": [like_notification["id"]]},
        headers=headers(USER_A, "Alice"),
    )
    assert marked.status_code == 200
    assert marked.json() == {"updated": 1}
    no_unread = client.get(
        "/internal/notifications",
        params={"unread_only": True},
        headers=headers(USER_A, "Alice"),
    )
    assert no_unread.json()["total"] == 0
    assert no_unread.json()["unread_count"] == 0
    all_notifications = client.get(
        "/internal/notifications", headers=headers(USER_A, "Alice")
    )
    assert all_notifications.json()["total"] == 1

    reply = create_comment(
        client, body="Ответ с уведомлением", user_id=USER_B, parent_id=root_id
    )
    assert reply.status_code == 201
    reply_notifications = client.get(
        "/internal/notifications",
        params={"unread_only": True},
        headers=headers(USER_A, "Alice"),
    )
    reply_page = reply_notifications.json()
    assert reply_page["total"] == 1
    assert reply_page["items"][0]["type"] == "reply"
    assert reply_page["items"][0]["comment_id"] == reply.json()["id"]
    reply_notification_id = reply_page["items"][0]["id"]

    self_reply = create_comment(
        client, body="Ответ самому себе", user_id=USER_A, parent_id=root_id
    )
    assert self_reply.status_code == 201
    after_self = client.get(
        "/internal/notifications",
        params={"unread_only": True},
        headers=headers(USER_A, "Alice"),
    )
    assert after_self.json()["total"] == 1

    foreign_read = client.post(
        "/internal/notifications/read",
        json={"ids": [reply_notification_id]},
        headers=headers(USER_B, "Bob"),
    )
    assert foreign_read.json() == {"updated": 0}


def test_reports_dedupe_admin_hide_restore_and_resolve(client: TestClient) -> None:
    root = create_comment(client, body="Жалоба", user_id=USER_A)
    root_id = root.json()["id"]

    first = client.post(
        f"/internal/comments/{root_id}/report",
        json={"reason": "  spam\x00  "},
        headers=headers(USER_B, "Bob"),
    )
    assert first.status_code == 201, first.text
    report_b = first.json()
    assert report_b["reason"] == "spam"
    assert report_b["status"] == "open"

    duplicate = client.post(
        f"/internal/comments/{root_id}/report",
        json={"reason": "Ещё раз"},
        headers=headers(USER_B, "Bob"),
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "report_exists"

    second = client.post(
        f"/internal/comments/{root_id}/report",
        json={"reason": "Тоже спам"},
        headers=headers(USER_C, "Carol"),
    )
    assert second.status_code == 201
    report_c = second.json()

    non_admin = client.get(
        "/internal/admin/reports", headers=headers(USER_A, "Alice")
    )
    assert non_admin.status_code == 403
    assert non_admin.json()["error"]["code"] == "moderator_required"

    admin_headers = headers(ADMIN, "Admin", "admin")
    reports = client.get(
        "/internal/admin/reports", params={"status": "open"}, headers=admin_headers
    )
    assert reports.status_code == 200
    assert reports.json()["total"] == 2

    reported_comments = client.get(
        "/internal/admin/comments",
        params={"reported": "true"},
        headers=admin_headers,
    )
    assert reported_comments.status_code == 200
    assert reported_comments.json()["total"] == 1
    assert reported_comments.json()["items"][0]["report_count"] == 2

    hidden = client.post(
        f"/internal/admin/comments/{root_id}/hide", headers=admin_headers
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["status"] == "hidden"

    public_after_hide = client.get(
        f"/internal/manga/{MANGA}/comments", headers=headers(USER_A)
    )
    assert public_after_hide.json()["total"] == 0

    notifications = client.get(
        "/internal/notifications",
        params={"unread_only": True},
        headers=headers(USER_A),
    )
    assert notifications.json()["total"] == 1
    assert notifications.json()["items"][0]["type"] == "moderation"

    hidden_report = client.post(
        f"/internal/comments/{root_id}/report",
        json={"reason": "Поздняя жалоба"},
        headers=headers(USER_B, "Bob"),
    )
    assert hidden_report.status_code == 404

    restored = client.post(
        f"/internal/admin/comments/{root_id}/restore", headers=admin_headers
    )
    assert restored.status_code == 200
    assert restored.json()["status"] == "visible"
    public_after_restore = client.get(
        f"/internal/manga/{MANGA}/comments", headers=headers(USER_A)
    )
    assert public_after_restore.json()["total"] == 1

    resolved_b = client.post(
        f"/internal/admin/reports/{report_b['id']}/resolve", headers=admin_headers
    )
    assert resolved_b.status_code == 200
    assert resolved_b.json()["status"] == "resolved"
    assert resolved_b.json()["comment"]["status"] == "visible"

    open_after_one = client.get(
        "/internal/admin/reports", params={"status": "open"}, headers=admin_headers
    )
    assert open_after_one.json()["total"] == 1

    dismissed_c = client.post(
        f"/internal/admin/reports/{report_c['id']}/resolve",
        json={"status": "dismissed"},
        headers=admin_headers,
    )
    assert dismissed_c.status_code == 200
    assert dismissed_c.json()["status"] == "dismissed"
    open_after_all = client.get(
        "/internal/admin/reports", params={"status": "open"}, headers=admin_headers
    )
    assert open_after_all.json()["total"] == 0


def test_pagination_sort_and_reply_preview(client: TestClient) -> None:
    roots = [
        create_comment(client, body=f"Комментарий {index}", user_id=USER_A).json()
        for index in range(1, 6)
    ]

    for manager, user_id, name in ((USER_B, USER_B, "Bob"), (USER_C, USER_C, "Carol")):
        for index in (0, 1) if manager == USER_C else (0,):
            response = client.post(
                f"/internal/comments/{roots[index]['id']}/like",
                headers=headers(user_id, name),
            )
            assert response.status_code == 200

    top_page_one = client.get(
        f"/internal/manga/{MANGA}/comments",
        params={"sort": "top", "limit": 2, "page": 1},
        headers=headers(USER_A),
    )
    top_data = top_page_one.json()
    assert top_data["total"] == 5
    assert top_data["has_next"] is True
    assert [item["id"] for item in top_data["items"]] == [
        roots[0]["id"],
        roots[1]["id"],
    ]

    top_page_two = client.get(
        f"/internal/manga/{MANGA}/comments",
        params={"sort": "top", "limit": 2, "page": 2},
        headers=headers(USER_A),
    )
    assert [item["id"] for item in top_page_two.json()["items"]] == [
        roots[4]["id"],
        roots[3]["id"],
    ]

    newest = client.get(
        f"/internal/manga/{MANGA}/comments",
        params={"sort": "new", "limit": 2},
        headers=headers(USER_A),
    )
    assert [item["id"] for item in newest.json()["items"]] == [
        roots[4]["id"],
        roots[3]["id"],
    ]

    for index in range(4):
        reply = create_comment(
            client,
            body=f"Ответ {index}",
            user_id=USER_B,
            name="Bob",
            parent_id=roots[4]["id"],
        )
        assert reply.status_code == 201

    listing = client.get(
        f"/internal/manga/{MANGA}/comments",
        params={"sort": "new", "limit": 100},
        headers=headers(USER_A),
    )
    newest_root = next(
        item for item in listing.json()["items"] if item["id"] == roots[4]["id"]
    )
    assert newest_root["replies_count"] == 4
    assert len(newest_root["replies"]) == 3

    first_replies = client.get(
        f"/internal/comments/{roots[4]['id']}/replies",
        params={"page": 1, "limit": 2},
        headers=headers(USER_A),
    )
    assert first_replies.status_code == 200
    assert first_replies.json()["total"] == 4
    assert len(first_replies.json()["items"]) == 2
    assert first_replies.json()["has_next"] is True
    second_replies = client.get(
        f"/internal/comments/{roots[4]['id']}/replies",
        params={"page": 2, "limit": 2},
        headers=headers(USER_A),
    )
    assert second_replies.json()["has_next"] is False
    assert len(second_replies.json()["items"]) == 2


def test_rate_limits_and_duplicate_guard(tmp_path: Path) -> None:
    with make_client(
        tmp_path / "cooldown.db", comments_create_cooldown_seconds=10
    ) as client:
        first = create_comment(client, body="Первый")
        assert first.status_code == 201
        too_fast = create_comment(client, body="Второй")
        assert too_fast.status_code == 429
        assert too_fast.json()["error"]["code"] == "comment_cooldown"
        assert int(too_fast.headers["Retry-After"]) >= 1
        other_user = create_comment(
            client, body="Другой пользователь", user_id=USER_B, name="Bob"
        )
        assert other_user.status_code == 201

    with make_client(
        tmp_path / "duplicate.db", comments_duplicate_window_seconds=60
    ) as client:
        first = create_comment(client, body="Повтор")
        assert first.status_code == 201
        duplicate = create_comment(client, body="Повтор")
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "duplicate_comment"
        different = create_comment(client, body="Не повтор")
        assert different.status_code == 201

    with make_client(
        tmp_path / "daily.db", comments_create_daily_limit=1
    ) as client:
        first = create_comment(client, body="Лимит")
        assert first.status_code == 201
        over_limit = create_comment(client, body="Сверх лимита")
        assert over_limit.status_code == 429
        assert over_limit.json()["error"]["code"] == "comment_daily_limit"


def test_auth_validation_plain_text_and_xss(client: TestClient) -> None:
    assert (
        client.get(f"/internal/manga/{MANGA}/comments").status_code == 401
    )
    assert (
        client.get(
            f"/internal/manga/{MANGA}/comments",
            headers=internal_headers(token="wrong-token"),
        ).status_code
        == 401
    )

    missing_user = client.post(
        f"/internal/manga/{MANGA}/comments",
        json={"body": "Без пользователя"},
        headers=internal_headers(),
    )
    assert missing_user.status_code == 401
    assert missing_user.json()["error"]["code"] == "missing_user"

    invalid_user = client.post(
        f"/internal/manga/{MANGA}/comments",
        json={"body": "Плохой id"},
        headers=headers("not-a-uuid"),
    )
    assert invalid_user.status_code == 401

    banned = client.post(
        f"/internal/manga/{MANGA}/comments",
        json={"body": "Заблокирован"},
        headers=headers(USER_B, "Bob", "banned"),
    )
    assert banned.status_code == 403
    assert banned.json()["error"]["code"] == "user_blocked"

    blank = create_comment(client, body="   \n\t ")
    assert blank.status_code == 422
    assert blank.json()["error"]["code"] == "empty_body"

    long_body = create_comment(client, body="x" * 2001)
    assert long_body.status_code == 422
    assert long_body.json()["error"]["code"] == "body_too_long"

    control = create_comment(client, body="he\x00llo\x07\nworld\t!")
    assert control.status_code == 201, control.text
    assert control.json()["body"] == "hello\nworld\t!"

    xss_body = '<script>alert("xss")</script><b>bold</b>'
    xss = create_comment(client, body=xss_body)
    assert xss.status_code == 201
    assert xss.json()["body"] == xss_body
    assert "text/html" not in xss.headers["content-type"]

    listed = client.get(
        f"/internal/manga/{MANGA}/comments", headers=headers(USER_A)
    )
    stored = next(item for item in listed.json()["items"] if item["id"] == xss.json()["id"])
    assert stored["body"] == xss_body
    assert "&lt;script&gt;" not in stored["body"]

    anonymous_name = client.post(
        f"/internal/manga/{MANGA}/comments",
        json={"body": "Без имени"},
        headers={
            "X-Internal-Token": INTERNAL_TOKEN,
            "X-User-Id": USER_C,
        },
    )
    assert anonymous_name.status_code == 201
    assert anonymous_name.json()["user_name"] == "Пользователь"
