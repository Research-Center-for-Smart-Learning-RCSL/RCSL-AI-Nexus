# Sourced stage: broken services.
INCOMPLETE=0
[ -n "$MISSING" ] && INCOMPLETE=1

# A container is broken when it asked for a host binding and did not get one:
# HostConfig.PortBindings is non-empty while the matching NetworkSettings.Ports
# entry is an empty list. That signature is exactly the dropped forward, and it
# separates those containers from the ones that never published a port at all
# (whose Ports entries are null, not []).
#
# Prints one compose service name per line on stdout; commentary goes to stderr
# so the caller can capture the list cleanly.
broken_services() {
  local cid req act svc name
  for cid in $(docker compose ps -q 2>/dev/null); do
    req="$(docker inspect "$cid" --format '{{json .HostConfig.PortBindings}}' 2>/dev/null)"
    if [ -z "$req" ] || [ "$req" = "{}" ] || [ "$req" = "null" ]; then
      continue
    fi
    act="$(docker inspect "$cid" --format '{{json .NetworkSettings.Ports}}' 2>/dev/null)"
    case "$act" in
      *'[]'*)
        svc="$(docker inspect "$cid" --format '{{index .Config.Labels "com.docker.compose.service"}}' 2>/dev/null)"
        name="$(docker inspect "$cid" --format '{{.Name}}' 2>/dev/null)"
        log "  dropped binding: ${name:-$cid} requested $req" >&2
        [ -n "$svc" ] && printf '%s\n' "$svc"
        ;;
    esac
  done
}
