#!/bin/sh
# MasterAPI installer for macOS and Linux:
#
#   curl -fsSL https://raw.githubusercontent.com/Prateekiiitg56/MasterAPi/main/install.sh | sh
#
# Installs uv (if missing), MasterAPI as a uv tool, and Deno (the Code Mode sandbox),
# then runs `masterapi setup` to add keys and connect your coding agents.
# Skip parts with MASTERAPI_NO_DENO=1 or MASTERAPI_NO_SETUP=1.
set -eu

REPO="git+https://github.com/Prateekiiitg56/MasterAPi"
have() { command -v "$1" >/dev/null 2>&1; }

echo "Installing MasterAPI"

if ! have uv; then
  echo "-> installing uv (Python tool manager)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

echo "-> installing masterapi"
uv tool install --force --python 3.12 "$REPO"
uv tool update-shell >/dev/null 2>&1 || true

if [ -z "${MASTERAPI_NO_DENO:-}" ] && ! have deno; then
  echo "-> installing Deno (sandbox for Code Mode)"
  curl -fsSL https://deno.land/install.sh | sh -s -- -y
  export PATH="$HOME/.deno/bin:$PATH"
fi

if [ -n "${MASTERAPI_NO_SETUP:-}" ]; then
  echo "Installed. Run 'masterapi setup' to add keys and connect your coding agents."
elif [ -r /dev/tty ]; then
  # stdin is this script when piped from curl; talk to the terminal instead.
  masterapi setup < /dev/tty
else
  echo "Installed. Run 'masterapi setup' to add keys and connect your coding agents."
fi
