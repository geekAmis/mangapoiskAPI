from __future__ import annotations

import argparse
import sys

import httpx

DEFAULT_TITLES = [
    ("mangapoisk", "https://mangapoisk.me/manga/zombie-slasher"),
    ("mangapoisk", "https://mangapoisk.me/manga/overgeared-abs3nSd"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Import demo titles through the public API")
    parser.add_argument("--api", default="http://localhost:8000/api/v1")
    parser.add_argument("--email", default="demo@example.com")
    parser.add_argument("--password", default="demo-password-123")
    parser.add_argument("--skip-user", action="store_true")
    args = parser.parse_args()

    api = args.api.rstrip("/")
    with httpx.Client(timeout=120.0) as client:
        try:
            health = client.get(f"{api}/health").json()
            print("health:", health.get("status"), health.get("checks"))
        except Exception as exc:
            print("API is not reachable:", exc)
            return 1

        for source, url in DEFAULT_TITLES:
            print(f"importing {source}: {url}")
            response = client.post(
                f"{api}/manga/import", json={"source": source, "url": url, "refresh": True}
            )
            if response.status_code >= 400:
                print("  failed:", response.status_code, response.text[:300])
                continue
            data = response.json()
            print(
                "  ok:",
                data["manga"]["title"],
                "chapters:",
                len(data["manga"].get("chapters", [])),
            )

        if not args.skip_user:
            response = client.post(
                f"{api}/auth/register",
                json={"email": args.email, "password": args.password, "display_name": "Demo"},
            )
            if response.status_code in (201, 409):
                print("demo user:", "ready" if response.status_code == 201 else "already exists")
            else:
                print("demo user failed:", response.status_code, response.text[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
