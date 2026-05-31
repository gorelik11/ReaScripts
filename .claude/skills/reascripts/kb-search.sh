#!/usr/bin/env bash
# kb-search.sh — token-cheap ReaScript knowledge lookup (section-level AND).
#
# Usage: kb-search.sh <terms...>
#   Returns every vault section (markdown heading block) that contains ALL of
#   the given terms (case-insensitive, any order), printed as:
#       <file>:<heading-line>
#         §  <heading>
#   so you can Read just that section instead of loading the whole file.
#
# Section-level AND (not a literal phrase): `kb-search.sh accessor sample rate`
# finds the section mentioning all three, regardless of order or adjacency.
#
# Extend SEARCH_DIRS to also index project script docstrings if wanted.
set -uo pipefail

SEARCH_DIRS=("$HOME/Knowledge/reascripts")
query="$*"
[ -z "$query" ] && { echo "usage: $(basename "$0") <terms...>"; exit 2; }

terms_lc=$(printf '%s' "$query" | tr 'A-Z' 'a-z')
found=0

for d in "${SEARCH_DIRS[@]}"; do
  [ -d "$d" ] || { echo "search dir not found: $d" >&2; exit 4; }
  while IFS= read -r f; do
    out=$(awk -v terms="$terms_lc" -v file="${f/#$HOME/~}" '
      function flush(   lc, n, i, T, ok) {
        if (heading == "") { buf = ""; return }
        lc = tolower(buf); n = split(terms, T, " "); ok = 1
        for (i = 1; i <= n; i++) if (index(lc, T[i]) == 0) { ok = 0; break }
        if (ok) printf "%s:%d\n  §  %s\n\n", file, hline, heading
        buf = ""
      }
      /^#/ { flush(); heading = $0; hline = NR; buf = $0 "\n"; next }
      { buf = buf $0 "\n" }
      END { flush() }
    ' "$f")
    if [ -n "$out" ]; then printf '%s\n' "$out"; found=1; fi
  done < <(find "$d" -name '*.md' -type f | sort)
done

[ "$found" -eq 0 ] && echo "no matches (all terms in one section) for: $query"
exit 0
