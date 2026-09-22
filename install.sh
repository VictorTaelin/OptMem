#!/bin/sh
# OptMem installer. Run it again to update: it only replaces the tool, and
# `memo init` never touches memories that already exist.
#
#   curl -fsSL https://raw.githubusercontent.com/VictorTaelin/OptMem/main/install.sh | sh
#
# Pinned to a tag or a commit, the tool checked against the sha256 of its
# `memo` at that ref:
#
#   curl -fsSL https://raw.githubusercontent.com/VictorTaelin/OptMem/<ref>/install.sh |
#     OPTMEM_REF=<ref> OPTMEM_SHA256=<sha256 of memo> sh

set -e

# One function, called on the last line: `curl | sh` cut short by a dropped
# connection defines half a function and runs nothing.
main() {
  DIR="$HOME/.optmem"
  REF="${OPTMEM_REF:-main}"
  # a tag or a branch, spliced into a URL: nothing but what names one
  case "$REF" in
    "" | . | .. | -* | *[!A-Za-z0-9._-]*)
      echo "OPTMEM_REF must name a tag, a branch or a commit." >&2
      exit 1 ;;
  esac

  command -v python3 >/dev/null || {
    echo "OptMem is one Python file, and this machine has no python3." >&2
    echo "Install python3, then run this line again." >&2
    exit 1
  }

  mkdir -p "$DIR"
  curl -fsSL "https://raw.githubusercontent.com/VictorTaelin/OptMem/$REF/memo" -o "$DIR/memo.new"
  # A captive portal or a proxy answers 200 with a page of its own. Replace a
  # working tool only with a Python file that parses.
  if [ "$(head -n 1 "$DIR/memo.new")" != "#!/usr/bin/env python3" ] ||
     ! python3 -c 'import ast, sys; ast.parse(open(sys.argv[1], "rb").read())' \
       "$DIR/memo.new" 2>/dev/null; then
    rm -f "$DIR/memo.new"
    echo "The download is not the OptMem tool; nothing was changed." >&2
    echo "Check the network (a sign-in page?), then run this line again." >&2
    exit 1
  fi
  # python3 is here anyway, and hashes the same on every platform
  if [ -n "${OPTMEM_SHA256:-}" ]; then
    got=$(python3 -c 'import hashlib, sys
print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$DIR/memo.new")
    if [ "$got" != "$(printf %s "$OPTMEM_SHA256" | tr 'A-F' 'a-f')" ]; then
      rm -f "$DIR/memo.new"
      echo "The download's sha256 is $got, not $OPTMEM_SHA256; nothing was changed." >&2
      exit 1
    fi
  fi
  chmod +x "$DIR/memo.new"
  mv "$DIR/memo.new" "$DIR/memo"

  exec "$DIR/memo" init
}

main
