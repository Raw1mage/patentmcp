---
description: Configure Google BigQuery authentication for patent search (100M+ patents)
allowed-tools: Bash
---

# Configure BigQuery Authentication

Set up Google Cloud authentication to enable patent search across 100M+ worldwide patents.

## Instructions

1. Verify Google Cloud SDK is installed
2. Run BigQuery authentication setup
3. Authorize browser OAuth flow
4. Verify credentials are saved
5. Test BigQuery connection

## Command

```bash
cd ${CLAUDE_PLUGIN_ROOT}
python scripts/setup_bigquery_auth.py
```

Or using gcloud directly:

```bash
gcloud auth application-default login
```

## What This Does

- Opens browser for Google account authorization
- Saves credentials to:
  - Windows: `%APPDATA%\gcloud\application_default_credentials.json`
  - Mac/Linux: `~/.config/gcloud/application_default_credentials.json`
- Verifies access to patents-public-data dataset
- Tests connection with sample query

## Requirements

- Google account (free)
- Google Cloud project (free tier: 1TB queries/month)
- Internet connection

## Verification

After setup, test with:

```bash
python scripts/test_bigquery.py
```

Should return sample patent results.

## Environment Variable

Set your project ID:

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
```

Or add to `.env` file under ${CLAUDE_PLUGIN_ROOT}.
