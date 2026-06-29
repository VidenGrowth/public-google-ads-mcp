#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage: $0 [--env-path PATH] [--no-browser]

Creates a temporary Google OAuth client_secrets JSON from the values in
.env and runs the existing Python helper to generate a refresh token.

Options:
  --env-path PATH   Path to .env (default: .env)
  --no-browser      Do not open a browser; print the auth URL instead
USAGE
  exit 1
}

env_path=".env"
no_browser=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-path)
      env_path="$2"
      shift 2
      ;;
    --no-browser)
      no_browser=1
      shift
      ;;
    -h|--help)
      usage
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      ;;
  esac
done

if [[ ! -f "$env_path" ]]; then
  echo "Error: .env not found at: $env_path" >&2
  exit 2
fi

get_dotenv_value() {
  local file="$1" key="$2"
  # Skip commented lines, extract first matching key, strip surrounding quotes
  local raw
  raw=$(grep -E "^\s*${key}\s*=" "$file" || true)
  if [[ -z "$raw" ]]; then
    return 1
  fi
  raw=${raw#*=}
  raw=${raw%%#*}
  raw=$(echo "$raw" | sed -E 's/^\s+//; s/\s+$//')
  if [[ ${raw:0:1} == '"' && ${raw: -1} == '"' ]] || [[ ${raw:0:1} == "'" && ${raw: -1} == "'" ]]; then
    raw=${raw:1:$((${#raw}-2))}
  fi
  printf "%s" "$raw"
}

client_id=$(get_dotenv_value "$env_path" "GOOGLE_ADS_CLIENT_ID" || true)
client_secret=$(get_dotenv_value "$env_path" "GOOGLE_ADS_CLIENT_SECRET" || true)

if [[ -z "$client_id" ]]; then
  echo "Error: GOOGLE_ADS_CLIENT_ID is missing in $env_path" >&2
  exit 3
fi
if [[ -z "$client_secret" ]]; then
  echo "Error: GOOGLE_ADS_CLIENT_SECRET is missing in $env_path" >&2
  exit 4
fi

json_escape() {
  local s="$1"
  s=${s//\\/\\\\}
  s=${s//"/\\"}
  s=${s//$'\n'/\\n}
  printf "%s" "$s"
}

cid_esc=$(json_escape "$client_id")
csec_esc=$(json_escape "$client_secret")

tempfile=$(mktemp /tmp/google-ads-client-secret.XXXXXX.json)
trap 'rm -f "$tempfile"' EXIT

cat > "$tempfile" <<EOF
{
  "web": {
    "client_id": "${cid_esc}",
    "client_secret": "${csec_esc}",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "redirect_uris": ["http://127.0.0.1:8080"]
  }
}
EOF

echo "Temporary OAuth client file created: $tempfile"

if ! command -v uv >/dev/null 2>&1; then
  echo "Error: 'uv' command not found in PATH. Install or add uv to PATH." >&2
  exit 5
fi

args=(run auth/generate_refresh_token.py -c "$tempfile" --env-file "$env_path")
if [[ $no_browser -eq 1 ]]; then
  args+=(--no-browser)
fi

uv "${args[@]}"

exit_code=$?
if [[ $exit_code -ne 0 ]]; then
  echo "Refresh token generation failed with exit code $exit_code" >&2
  exit $exit_code
fi

echo "Done. If successful, GOOGLE_ADS_REFRESH_TOKEN was written to $env_path"
