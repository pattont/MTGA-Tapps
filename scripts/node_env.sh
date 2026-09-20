#!/usr/bin/env bash

# Make Node-based build scripts work from Finder, CI-style shells, and other
# noninteractive launchers that do not source ~/.zshrc. Homebrew installs are
# already found through PATH; when Node is managed by nvm, load its default.
ensure_node_tools() {
  if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    local nvm_home="${NVM_DIR:-$HOME/.nvm}"
    if [[ -s "$nvm_home/nvm.sh" ]]; then
      export NVM_DIR="$nvm_home"
      local restore_nounset=0
      if [[ $- == *u* ]]; then
        restore_nounset=1
        set +u
      fi
      # nvm is a shell function, so it must be sourced rather than executed.
      # shellcheck disable=SC1090
      source "$NVM_DIR/nvm.sh"
      nvm use --silent default >/dev/null 2>&1 || nvm use --silent node >/dev/null 2>&1 || true
      if [[ "$restore_nounset" == "1" ]]; then
        set -u
      fi
    fi
  fi

  if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    echo "Node.js 18+ and npm are required. Install Node or configure an nvm default." >&2
    return 1
  fi

  local node_major
  node_major="$(node -p 'Number(process.versions.node.split(".")[0])' 2>/dev/null || echo 0)"
  if [[ ! "$node_major" =~ ^[0-9]+$ ]] || (( node_major < 18 )); then
    echo "Node.js 18+ is required; found $(node --version 2>/dev/null || echo unknown)." >&2
    return 1
  fi
}
