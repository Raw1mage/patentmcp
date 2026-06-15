#!/usr/bin/env python3
"""
Simple script to set up BigQuery authentication using browser OAuth flow
"""
import json
import os
import platform
import sys
from pathlib import Path

try:
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]
except ImportError:
    print("Installing required packages...")
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "google-auth-oauthlib"])
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]

# Scopes needed for BigQuery
SCOPES = [
    "https://www.googleapis.com/auth/bigquery",
    "https://www.googleapis.com/auth/cloud-platform",
]


def get_gcloud_credentials_path():
    """
    Get the correct gcloud application default credentials path for the current OS

    Returns:
        Path: Platform-specific credentials path
    """
    if platform.system() == "Windows":
        # Windows: %APPDATA%\gcloud\application_default_credentials.json
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "gcloud" / "application_default_credentials.json"
        else:
            return (
                Path.home()
                / "AppData"
                / "Roaming"
                / "gcloud"
                / "application_default_credentials.json"
            )
    else:
        # Linux/macOS: $HOME/.config/gcloud/application_default_credentials.json
        return Path.home() / ".config" / "gcloud" / "application_default_credentials.json"


def main():
    print("BigQuery Authentication Setup")
    print("=" * 60)
    print()

    creds = None
    creds_path = get_gcloud_credentials_path()
    creds_path.parent.mkdir(parents=True, exist_ok=True)

    # OAuth client configuration (public client ID for gcloud)
    # NOTE: Avoid shipping credentials in public repositories.
    # If you want to use a client ID/secret here, provide them via env variables
    # or a local client_secrets.json file. Using gcloud auth is preferred.
    client_config = {
        "installed": {
            "client_id": "<YOUR_CLIENT_ID>",
            "client_secret": "<YOUR_CLIENT_SECRET>",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    print("Opening browser for authentication...")
    print("(If browser doesn't open, copy the URL from terminal)")
    print()

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0)

    # Get project ID from user
    print()
    print("To use BigQuery, we need your Google Cloud project ID.")
    print("Find it at: https://console.cloud.google.com/bigquery")
    print("(Look for 'SANDBOX' at top left, project ID is in the top bar)")
    print()

    project_id = input("Enter your project ID: ").strip()

    # Save credentials
    creds_data = {
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "refresh_token": creds.refresh_token,
        "type": "authorized_user",
        "quota_project_id": project_id,
    }

    with creds_path.open("w") as f:
        json.dump(creds_data, f, indent=2)

    print()
    print("[OK] Authentication successful!")
    print(f"[OK] Credentials saved to: {creds_path}")
    print(f"[OK] Project ID: {project_id}")
    print()
    print("BigQuery is now ready to use!")

    return 0


if __name__ == "__main__":
    sys.exit(main())
