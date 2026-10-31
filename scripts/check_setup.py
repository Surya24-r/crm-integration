"""Verifies the database and Zoho credentials. Run: python -m scripts.check_setup"""
import httpx

from app.config import settings
from app.db import close_pool, fetch_one, open_pool


def check_db() -> None:
    open_pool()
    row = fetch_one("select 1 as ok")
    print("DB OK:", row)
    close_pool()


def check_zoho() -> None:
    # 1) refresh token -> access token
    r = httpx.post(
        f"{settings.zoho_accounts_url}/oauth/v2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": settings.zoho_refresh_token,
            "client_id": settings.zoho_client_id,
            "client_secret": settings.zoho_client_secret,
        },
        timeout=30,
    )
    body = r.json()
    if "access_token" not in body:
        print("Zoho token refresh FAILED:", body)
        return
    print("Zoho token refresh OK")

    # 2) call Books with that token
    r = httpx.get(
        f"{settings.zoho_api_url}/organizations",
        headers={"Authorization": f"Zoho-oauthtoken {body['access_token']}"},
        timeout=30,
    )
    data = r.json()
    if data.get("code") != 0:
        print("Zoho Books call FAILED:", data)
        return
    for org in data["organizations"]:
        print("Zoho org:", org["organization_id"], org["name"], org["currency_code"])
    ids = [o["organization_id"] for o in data["organizations"]]
    if settings.zoho_org_id not in ids:
        print("WARNING: ZOHO_ORG_ID not found in your orgs:", ids)


if __name__ == "__main__":
    check_db()
    check_zoho()