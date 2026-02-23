"""
Local test script for calling the Databricks App endpoints.

Uses the PKCE OAuth flow (via getOAuth.py) to obtain a token with the
correct scopes for User Authorization.

Prerequisites:
  1. pip install databricks-sdk requests
  2. Provide the app URL via --app-url

Usage:
  python local_test.py --app-url https://<your-app-url>
  python local_test.py --app-url https://<your-app-url> --host https://<workspace-url> --scopes "sql iam.current-user:read catalog.tables:read iam.access-control:read"
"""

import argparse
import json
import sys

import requests

from getOAuth import (
    CLIENT_ID,
    exchange_code_for_token,
    generate_pkce_pair,
    get_authorization_code,
)


def get_oauth_token(host: str, scopes: str, redirect_uri: str) -> str:
    """Run the PKCE flow to get a properly scoped OAuth token."""
    code_verifier, code_challenge = generate_pkce_pair()
    authorization_code = get_authorization_code(
        host, CLIENT_ID, redirect_uri, scopes, code_challenge
    )
    token_response = exchange_code_for_token(
        host, CLIENT_ID, redirect_uri, code_verifier, authorization_code, scopes
    )
    token = token_response["access_token"]
    print(f"Token type:    {token_response.get('token_type')}", file=sys.stderr)
    print(f"Scope:         {token_response.get('scope')}", file=sys.stderr)
    print(f"Expires in:    {token_response.get('expires_in')}s", file=sys.stderr)
    print(f"Token prefix:  {token[:20]}...", file=sys.stderr)
    return token


def call_endpoint(url: str, headers: dict, label: str):
    print(f"\n--- {label} ---")
    print(f"GET {url}")
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        print(f"Status: {resp.status_code}")
        if resp.headers.get("content-type", "").startswith("application/json"):
            print(json.dumps(resp.json(), indent=2, default=str))
        else:
            print(resp.text)
    except requests.RequestException as e:
        print(f"ERROR: {e}")


def main():
    parser = argparse.ArgumentParser(description="Test Databricks App endpoints locally")
    parser.add_argument(
        "--app-url", required=True,
        help="Deployed FastAPI app URL (e.g. https://my-app.aws.databricksapps.com)",
    )
    parser.add_argument(
        "--host", default=None,
        help="Databricks workspace URL (reads from ../../.env if not provided)",
    )
    parser.add_argument(
        "--scopes",
        default="sql iam.current-user:read catalog.tables:read iam.access-control:read",
        help="OAuth scopes (space-separated)",
    )
    parser.add_argument(
        "--redirect-uri", default="http://localhost:8020",
        help="Redirect URI for OAuth callback (default: http://localhost:8020)",
    )
    args = parser.parse_args()

    app_url = args.app_url.rstrip("/")
    host = args.host

    if not host:
        import os
        env_file = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
        if os.path.exists(env_file):
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("WORKSPACE_URL="):
                        host = line.split("=", 1)[1].strip().strip('"').rstrip("/")
                        break
        if not host:
            print("ERROR: --host not provided and WORKSPACE_URL not found in .env")
            sys.exit(1)

    print(f"App URL:    {app_url}")
    print(f"Workspace:  {host}")
    print(f"Scopes:     {args.scopes}")
    print()

    token = get_oauth_token(host, args.scopes, args.redirect_uri)
    headers = {"Authorization": f"Bearer {token}"}

    call_endpoint(f"{app_url}/api/v1/healthcheck", headers, "Healthcheck")
    call_endpoint(f"{app_url}/api/v1/me", headers, "Who Am I")
    call_endpoint(f"{app_url}/api/v1/trips", headers, "NYC Taxi Trips")


if __name__ == "__main__":
    main()
