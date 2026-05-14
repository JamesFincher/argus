#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

REPO_ROOT="$PWD"
ARGUS_HOME="${ARGUS_HOME:-$HOME/Library/Application Support/Argus}"
ARGUS_ENV_FILE="${ARGUS_ENV_FILE:-$ARGUS_HOME/argus.env}"

if [[ -f "$ARGUS_ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ARGUS_ENV_FILE"
fi

ARGUS_HOME="${ARGUS_HOME:-$HOME/Library/Application Support/Argus}"
ARGUS_TIMELINE_DB_PATH="${ARGUS_TIMELINE_DB_PATH:-$ARGUS_HOME/timeline.db}"
ARGUS_LANCEDB_PATH="${ARGUS_LANCEDB_PATH:-}"
ARGUS_APPROVAL_TOKEN="${ARGUS_APPROVAL_TOKEN:-}"
ARGUS_CONFIGURE_HERMES="${ARGUS_CONFIGURE_HERMES:-1}"
ARGUS_PACKAGE_MACOS_APP="${ARGUS_PACKAGE_MACOS_APP:-1}"
ARGUS_INSTALL_NATIVE_HOST="${ARGUS_INSTALL_NATIVE_HOST:-auto}"
ARGUS_NATIVE_BROWSER="${ARGUS_NATIVE_BROWSER:-chrome}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

shell_quote() {
  printf "%q" "$1"
}

generate_token() {
  if command -v uuidgen >/dev/null 2>&1; then
    uuidgen | tr '[:upper:]' '[:lower:]'
  else
    openssl rand -hex 16
  fi
}

write_env_file() {
  mkdir -p "$ARGUS_HOME"
  if [[ -z "$ARGUS_APPROVAL_TOKEN" ]]; then
    ARGUS_APPROVAL_TOKEN="$(generate_token)"
  fi

  {
    echo "export ARGUS_HOME=$(shell_quote "$ARGUS_HOME")"
    echo "export ARGUS_TIMELINE_DB_PATH=$(shell_quote "$ARGUS_TIMELINE_DB_PATH")"
    if [[ -n "$ARGUS_LANCEDB_PATH" ]]; then
      echo "export ARGUS_LANCEDB_PATH=$(shell_quote "$ARGUS_LANCEDB_PATH")"
    else
      echo "# Optional: export ARGUS_LANCEDB_PATH=$(shell_quote "$ARGUS_HOME/notes.lancedb")"
    fi
    echo "export ARGUS_APPROVAL_TOKEN=$(shell_quote "$ARGUS_APPROVAL_TOKEN")"
  } > "$ARGUS_ENV_FILE"
  chmod 600 "$ARGUS_ENV_FILE"
}

configure_hermes_mcp() {
  if [[ "$ARGUS_CONFIGURE_HERMES" == "0" ]]; then
    echo "Skipping Hermes MCP config because ARGUS_CONFIGURE_HERMES=0."
    return
  fi
  if ! command -v hermes >/dev/null 2>&1; then
    echo "Skipping Hermes MCP config because hermes is not on PATH."
    return
  fi

  local command=(
    hermes mcp add argus-sensor
    --command "$REPO_ROOT/scripts/dev/run_argus_sensor_mcp.sh" \
    --env "ARGUS_HOME=$ARGUS_HOME" \
    --env "ARGUS_TIMELINE_DB_PATH=$ARGUS_TIMELINE_DB_PATH" \
    --env "ARGUS_APPROVAL_TOKEN=$ARGUS_APPROVAL_TOKEN"
  )
  if [[ -n "$ARGUS_LANCEDB_PATH" ]]; then
    command+=(--env "ARGUS_LANCEDB_PATH=$ARGUS_LANCEDB_PATH")
  fi

  printf 'y\nY\n' | "${command[@]}"
  hermes mcp test argus-sensor
}

install_native_host_if_configured() {
  if [[ "$ARGUS_INSTALL_NATIVE_HOST" == "0" ]]; then
    echo "Skipping browser native host install because ARGUS_INSTALL_NATIVE_HOST=0."
    return
  fi
  if [[ -z "${ARGUS_NATIVE_ALLOWED_ORIGIN:-}" ]]; then
    echo "Skipping browser native host install; set ARGUS_NATIVE_ALLOWED_ORIGIN=chrome-extension://<extension-id>/ to enable it."
    return
  fi

  local host_path="$REPO_ROOT/.venv/bin/argus-native-host"
  if [[ ! -x "$host_path" ]]; then
    host_path="$(command -v argus-native-host || true)"
  fi
  if [[ -z "$host_path" ]]; then
    echo "argus-native-host is not installed on PATH or in .venv." >&2
    exit 1
  fi

  python3 scripts/install_native_messaging_host.py install \
    --host-path "$host_path" \
    --allowed-origin "$ARGUS_NATIVE_ALLOWED_ORIGIN" \
    --browser "$ARGUS_NATIVE_BROWSER"
}

package_macos_app_if_enabled() {
  if [[ "$ARGUS_PACKAGE_MACOS_APP" == "0" ]]; then
    echo "Skipping macOS app packaging because ARGUS_PACKAGE_MACOS_APP=0."
    return
  fi
  require_command swift
  ARGUS_CREATE_DMG="${ARGUS_CREATE_DMG:-1}" scripts/dev/package_macos_app.sh release
}

main() {
  require_command uv
  require_command docker
  require_command curl
  require_command python3

  if ! docker info >/dev/null 2>&1; then
    echo "Docker is required for Argus Mesh but is not running or is unavailable." >&2
    exit 1
  fi

  write_env_file
  export ARGUS_HOME ARGUS_TIMELINE_DB_PATH ARGUS_LANCEDB_PATH ARGUS_APPROVAL_TOKEN

  uv sync
  uv pip install -e "$REPO_ROOT"

  python3 scripts/verify_spec.py
  scripts/dev/verify_local_infra.py

  scripts/dev/start_mesh.sh
  scripts/dev/start_event_gateway.sh
  scripts/dev/start_storage_worker.sh
  install_native_host_if_configured
  package_macos_app_if_enabled
  configure_hermes_mcp
  uv run python scripts/verify_hermes_runtime.py
  scripts/dev/status_stack.sh

  echo
  echo "Argus setup complete."
  echo "Environment file: $ARGUS_ENV_FILE"
  echo "Dashboard: http://127.0.0.1:8765/dashboard"
  echo "Timeline DB: $ARGUS_TIMELINE_DB_PATH"
}

main "$@"
