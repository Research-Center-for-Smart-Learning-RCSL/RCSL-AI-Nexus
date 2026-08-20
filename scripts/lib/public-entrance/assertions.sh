# Sourced stage: assertions.
PASS=0
FAIL=0
SKIP=0

pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; PASS=$((PASS + 1)); }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; printf '        %s\n' "$2"; FAIL=$((FAIL + 1)); }
skip() { printf '  \033[33mSKIP\033[0m  %s\n' "$1"; printf '        %s\n' "$2"; SKIP=$((SKIP + 1)); }
head_() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# A function because section 4 can end the run early, and the counts have to be
# reported the same way from both places.
summary() {
  printf '\n\033[1m%s passed, %s failed, %s skipped\033[0m\n' "$PASS" "$FAIL" "$SKIP"
  [ "$FAIL" -eq 0 ] || exit 1
  exit 0
}

# Status code only. --max-time so a hung proxy fails the check rather than the
# person running it.
status() { curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$@" 2>/dev/null; }
body() { curl -s --max-time 15 "$@" 2>/dev/null; }

# Why the entrance is not answering, as one word.
#
# The first version of this script read %{ssl_verify_result} and called anything
# non-zero an invalid certificate. That value is 1 whenever the handshake did
# not complete, so four unrelated states produced one message — and the hint it
# printed alongside ("a *.rcsl.online wildcard does not cover a two-label name")
# named a certificate-scope problem as the cause. On 2026-08-04 the actual cause
# was that both proxy hosts had been removed from NPM, and the script sent the
# reader to look at certificates. This is the same defect as the one section 4
# documents: one probe, several causes, and a confident message for the wrong
# one. Certificate scope is a real failure and its note belongs in `cert`, where
# the handshake got far enough for the certificate to be the thing at fault.
#
# curl's exit code carries the distinction the status code cannot: 000 is every
# one of these. `unrecognized name` is TLS alert 112, sent when no server block
# matches the SNI -- the name is not configured, which is not a TLS fault at all.
entrance_state() {
  local h="$1"
  local out
  local rc
  out="$(curl -sv -o /dev/null --max-time 15 "https://$h/" 2>&1)"
  rc=$?
  case "$rc" in
    0)  echo ok ;;
    6)  echo dns ;;
    7)  echo refused ;;
    28) echo timeout ;;
    35) if printf '%s' "$out" | grep -qi 'unrecognized name'; then
          echo unconfigured
        else
          echo handshake
        fi ;;
    51|60) echo cert ;;
    *)  echo "curl$rc" ;;
  esac
}

# Corroborates `unconfigured` from the other side. NPM answers port 80 for a
# name it does not know with its own stock welcome page, so seeing it means the
# proxy is running and this hostname has no host entry -- as opposed to nginx
# being down, which cannot answer anything. Distinguishing those two decides
# whether the administrator restores a host or starts a service.
serves_npm_default_site() {
  body "http://$1/" | grep -q 'successfully started the Nginx Proxy Manager'
}
