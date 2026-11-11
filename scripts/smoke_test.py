from __future__ import annotations

import argparse
import io
import sys
import time
import uuid
import zipfile

import httpx


def check(response: httpx.Response, label: str) -> httpx.Response:
    if response.status_code >= 400:
        print(f"FAIL {label}: HTTP {response.status_code} {response.text[:500]}")
        raise SystemExit(1)
    print(f"ok   {label}")
    return response


def main() -> int:
    parser = argparse.ArgumentParser(description="End-to-end smoke test against a running stack")
    parser.add_argument("--api", default="http://localhost:8000/api/v1")
    parser.add_argument("--source", default="mangapoisk")
    parser.add_argument(
        "--url", default="https://mangapoisk.me/manga/zombie-slasher"
    )
    parser.add_argument("--skip-export", action="store_true")
    args = parser.parse_args()
    api = args.api.rstrip("/")

    with httpx.Client(timeout=180.0) as client:
        check(client.get(f"{api}/health"), "health")
        sources = check(client.get(f"{api}/sources"), "sources").json()
        assert sources, "no sources returned"

        imported = check(
            client.post(
                f"{api}/manga/import",
                json={"source": args.source, "url": args.url, "refresh": True},
            ),
            "import manga",
        ).json()
        manga = imported["manga"]
        manga_id = manga["id"]
        assert manga["chapters"], "manga has no chapters"

        detail = check(client.get(f"{api}/manga/{manga_id}"), "manga detail").json()
        chapter = detail["chapters"][0]
        chapter_id = chapter["id"]

        chapter_detail = check(
            client.get(f"{api}/chapters/{chapter_id}"), "chapter pages"
        ).json()
        assert chapter_detail["pages"], "chapter has no pages"

        image = check(
            client.get(f"{api}/chapters/{chapter_id}/images/1"), "image proxy"
        )
        assert image.headers["content-type"].startswith("image/")
        assert len(image.content) > 1000

        email = f"smoke-{uuid.uuid4().hex[:10]}@example.com"
        tokens = check(
            client.post(
                f"{api}/auth/register",
                json={"email": email, "password": "smoke-password-123", "display_name": "Smoke"},
            ),
            "register",
        ).json()
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        check(client.get(f"{api}/auth/me", headers=headers), "me")

        check(
            client.post(f"{api}/library/bookmarks", json={"manga_id": manga_id}, headers=headers),
            "bookmark",
        )
        bookmarks = check(
            client.get(f"{api}/library/bookmarks", headers=headers), "bookmarks"
        ).json()
        assert bookmarks and bookmarks[0]["manga"]["id"] == manga_id

        check(
            client.put(
                f"{api}/library/progress",
                json={
                    "manga_id": manga_id,
                    "chapter_id": chapter_id,
                    "page": 2,
                    "total_pages": len(chapter_detail["pages"]),
                },
                headers=headers,
            ),
            "progress",
        )
        progress = check(
            client.get(f"{api}/library/progress", headers=headers), "progress list"
        ).json()
        assert progress[0]["manga"]["id"] == manga_id

        check(
            client.put(
                f"{api}/library/settings",
                json={
                    "theme": "midnight",
                    "reader_mode": "vertical",
                    "page_fit": "width",
                    "auto_scroll": False,
                    "auto_scroll_speed": 30,
                    "show_page_numbers": True,
                    "blur_adult_posters": True,
                },
                headers=headers,
            ),
            "settings",
        )

        if not args.skip_export:
            job = check(
                client.post(f"{api}/chapters/{chapter_id}/exports?format=cbz"),
                "export create",
            ).json()
            for _ in range(180):
                job = check(client.get(f"{api}/exports/{job['id']}"), "export status").json()
                if job["status"] in {"done", "failed"}:
                    break
                time.sleep(1)
            assert job["status"] == "done", job
            archive = check(
                client.get(f"{api}/exports/{job['id']}/download"), "export download"
            )
            with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
                names = bundle.namelist()
                assert "ComicInfo.xml" in names
                assert len(names) > 1

        search = check(
            client.get(f"{api}/manga/search", params={"q": "магия", "live": "true"}),
            "live search",
        ).json()
        assert search["items"], "live search returned no items"

    print("\nSMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
