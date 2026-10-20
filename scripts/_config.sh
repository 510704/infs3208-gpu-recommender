#!/usr/bin/env bash
# Shared configuration and discovery logic for the GCP scripts.
#
# Source this from the repository root, do not execute it:
#
#   . scripts/_config.sh
#
# The functions set plain shell variables in the caller, so the scripts keep
# one place for "where do settings come from?" instead of duplicating it.

# Read the gitignored .env file, if present. Environment variables already set
# by the caller win, because .env is only sourced when they are unset (the
# assignments use "${VAR:-${...}}" default expansion later). `tr -d '\r'`
# strips Windows line endings so an editor-saving .env still loads.
load_dotenv() {
  if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    . <(tr -d '\r' < .env)
    set +a
  fi
}

# Map settings to their sources: a plain environment variable, then the .env
# name, then a default. This is the only place defaults are written down.
resolve_config() {
  PROJECT="${PROJECT:-${GCP_PROJECT:-}}"
  BUCKET="${BUCKET:-${GCP_BUCKET:-}}"
  REGION="${REGION:-${GCP_REGION:-australia-southeast1}}"
  ZONE="${ZONE:-${GCP_ZONE:-${REGION}-a}}"
  CLUSTER="${CLUSTER:-${GKE_CLUSTER:-gpu-recsys}}"
  REPO="${REPO:-${GCP_AR_REPO:-gpu-recsys}}"
}

# A fresh clone has no .env (it is gitignored), so if PROJECT is still empty,
# use the project gcloud is currently pointed at. This is what lets the scripts
# run right after `git clone`, especially inside Cloud Shell.
resolve_project() {
  if [[ -z "$PROJECT" ]]; then
    PROJECT="$(gcloud config get-value project 2>/dev/null | tr -d '\r')"
    [[ -n "$PROJECT" && "$PROJECT" != "(unset)" ]] && echo "using the active gcloud project: $PROJECT"
  fi
}

# Fail loudly, and tell the user exactly how to fix it. When BUCKET is missing
# the script lists the project's buckets instead of just printing an error.
require_project_and_bucket() {
  if [[ -z "$PROJECT" ]]; then
    echo "set GCP_PROJECT in .env, or run: PROJECT=<id> BUCKET=<bucket> bash $0"
    exit 1
  fi
  if [[ -z "$BUCKET" ]]; then
    echo "BUCKET is not set. Buckets in ${PROJECT}:"
    gcloud storage buckets list --project "$PROJECT" --format="value(name)" 2>/dev/null | sed 's/^/  /'
    echo
    echo "then run: PROJECT=${PROJECT} BUCKET=<bucket> bash $0"
    exit 1
  fi
}