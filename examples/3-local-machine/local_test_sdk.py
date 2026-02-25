"""
Local test using Databricks SDK (databricks auth login).

This uses the CLI's OAuth token (all-apis scope). The app will identify
the user but queries run as the service principal since the token lacks
the specific scopes required by User Authorization.

Prerequisites:
  databricks auth login --host <workspace-url> --profile <profile>

Usage:
  python local_test_sdk.py --profile sandboxAws --app-url https://<your-app-url>
"""

import argparse
import json
import sys

import requests
from databricks.sdk.core import Config


def get_oauth_token(profile: str) -> str:
    cfg = Config(profile=profile)
    print(f"Auth type:    {cfg.auth_type}")
    print(f"Host:         {cfg.host}")

    if cfg.auth_type in ("pat", "basic"):
        print(f"\nERROR: Profile '{profile}' uses {cfg.auth_type} auth, but OAuth is required.")
        print(f"Fix:   databricks auth login --host {cfg.host} --profile {profile}")
        sys.exit(1)

    token = cfg.oauth_token().access_token
    print(f"Token prefix: {token[:20]}...")
    return token


def call_endpoint(url: str, headers: dict, label: str):
    print(f"\n--- {label} ---")
    resp = requests.get(url, headers=headers, timeout=30)
    print(f"Status: {resp.status_code}")
    if resp.headers.get("content-type", "").startswith("application/json"):
        print(json.dumps(resp.json(), indent=2, default=str))
    else:
        print(resp.text)


def main():
    parser = argparse.ArgumentParser(description="Test app using Databricks SDK OAuth")
    parser.add_argument("--profile", default="sandboxAws", help="Databricks CLI profile")
    parser.add_argument("--app-url", required=True, help="Deployed FastAPI app URL")
    args = parser.parse_args()

    app_url = args.app_url.rstrip("/")
    print(f"App URL:  {app_url}")
    print(f"Profile:  {args.profile}\n")

    token = get_oauth_token(args.profile)
    headers = {"Authorization": f"Bearer {token}"}

    call_endpoint(f"{app_url}/api/v1/healthcheck", headers, "Healthcheck")
    call_endpoint(f"{app_url}/api/v1/me", headers, "Who Am I")
    call_endpoint(f"{app_url}/api/v1/trips", headers, "NYC Taxi Trips")


if __name__ == "__main__":
    main()
