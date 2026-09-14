#!/usr/bin/env bash
# Daily pipeline: fetch card -> predict+tag -> report -> settle yesterday -> stats
set -euo pipefail
cd "$(dirname "$0")"
python -m overunder fetch-statarea || true
python -m overunder predict --statarea
python -m overunder report --telegram
python -m overunder settle
python -m overunder stats
