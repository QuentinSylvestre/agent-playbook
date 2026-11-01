#!/usr/bin/env bash
# Claude Code status line
# Layout:  <folder>:<branch>  |  <model> - <effort>  |  Context: <Xk> - <ctx%>  |  Quota 5h: <%> - <reset> / 7d: <%> - <reset>
# Receives JSON on stdin per the Claude Code statusLine command contract.

input=$(cat)

# --- PowerAtlas quota snapshot --------------------------------------------
# Claude Code gives its live rate-limit percentages only to this command. When PowerAtlas has made its
# folder, keep the latest payload there so its dashboard can show them. No extra process (a shell
# pattern and one write; `mv` or `jq` would each add one, ~60-150 ms on Windows), and a payload without
# a `rate_limits` object leaves the last reading in place. PowerAtlas copes with reading the file
# mid-write. It owns the file's format and the wording of these lines: `STATUSLINE_SNIPPET` in its
# `src/power_atlas/quota.py` is the same text, and its tests run it.
pa_dir="${LOCALAPPDATA:+$LOCALAPPDATA/power-atlas}"
if [ -n "$pa_dir" ] && [ -d "$pa_dir" ]; then
  case "$input" in
    *'"rate_limits":{'*|*'"rate_limits": {'*)
      printf '%s' "$input" > "$pa_dir/claude-statusline.json"
      ;;
  esac
fi

# --- Parse everything in a single jq pass --------------------------------
# One process spawn instead of one per field. We emit one field per line and
# read with `readarray`: unlike `read` with a whitespace IFS, this preserves
# empty fields positionally (consecutive tabs would otherwise collapse and
# shift every later field left by one).
readarray -t F < <(
  printf '%s' "$input" | jq -r '
    [
      (.model.display_name              // "unknown model"),
      (.workspace.project_dir // .workspace.current_dir // ""),
      (.output_style.name               // ""),
      (.context_window.total_input_tokens // 0),
      (.context_window.used_percentage  // ""),
      (.rate_limits.five_hour.used_percentage // ""),
      (.rate_limits.seven_day.used_percentage // ""),
      (.rate_limits.five_hour.resets_at  // .rate_limits.five_hour.reset_at  // .rate_limits.five_hour.resets  // ""),
      (.rate_limits.seven_day.resets_at  // .rate_limits.seven_day.reset_at  // .rate_limits.seven_day.resets  // ""),
      (.effort | if type == "object" then (.level // .name // "") else (. // "") end)
    ] | map(tostring) | .[]
  ' | tr -d '\r'   # jq.exe on Windows emits CRLF; strip CR so values stay numeric
)
model=${F[0]};    proj_dir=${F[1]};  ostyle=${F[2]};     total_tok=${F[3]}
used_pct=${F[4]}; five_pct=${F[5]};  week_pct=${F[6]}
five_reset=${F[7]}; week_reset=${F[8]}; effort=${F[9]}

# --- Colors (ANSI; the status line interprets escape sequences) ----------
esc=$'\033'
C_RESET="${esc}[0m"; C_BOLD="${esc}[1m"; C_DIM="${esc}[2m"
C_GREEN="${esc}[32m"; C_YELLOW="${esc}[33m"; C_RED="${esc}[31m"
C_CYAN="${esc}[36m"; C_BLUE="${esc}[34m"; C_MAGENTA="${esc}[35m"

color_for() {  # arg: integer percent -> prints a color code (green<50, yellow<80, red>=80)
  local p=$1
  if   [ "$p" -ge 80 ]; then printf '%s' "$C_RED"
  elif [ "$p" -ge 50 ]; then printf '%s' "$C_YELLOW"
  else                       printf '%s' "$C_GREEN"
  fi
}

fmt_reset() {  # arg: raw reset value (epoch s, epoch ms, or ISO) -> prints "2h13m" relative, or nothing
  local raw="$1" now reset delta d h m
  [ -z "$raw" ] && return
  now=$(date +%s)
  if [[ "$raw" =~ ^[0-9]+$ ]]; then
    reset=$raw
    [ "$reset" -gt 100000000000 ] && reset=$(( reset / 1000 ))   # ms -> s
  else
    reset=$(date -d "$raw" +%s 2>/dev/null) || return            # ISO 8601
  fi
  delta=$(( reset - now ))
  [ "$delta" -le 0 ] && { printf 'now'; return; }
  d=$(( delta / 86400 )); h=$(( (delta % 86400) / 3600 )); m=$(( (delta % 3600) / 60 ))
  if   [ "$d" -gt 0 ]; then printf '%dd%dh' "$d" "$h"
  elif [ "$h" -gt 0 ]; then printf '%dh%dm' "$h" "$m"
  else                      printf '%dm' "$m"
  fi
}

# --- Fast mode (read from disk; NOT exposed in the statusline JSON) -------
# Claude Code's /fast toggle persists as "fastMode": true in settings.json.
# The stdin payload never carries it (feature request #24279, closed
# not-planned), so we read it ourselves. settings.local.json overrides
# settings.json, matching Claude Code's own settings precedence.
fast_mode=""
cfg_dir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
for sf in "$cfg_dir/settings.json" "$cfg_dir/settings.local.json"; do
  [ -f "$sf" ] || continue
  v=$(jq -r '.fastMode // empty' "$sf" 2>/dev/null | tr -d '\r')
  [ -n "$v" ] && fast_mode="$v"
done

# --- Project name --------------------------------------------------------
project=""
[ -n "$proj_dir" ] && project=$(basename "$proj_dir")

# --- Git branch + dirty marker (the JSON has no git info; we ask git) -----
branch_disp=""
if [ -n "$proj_dir" ]; then
  branch=$(git -C "$proj_dir" rev-parse --abbrev-ref HEAD 2>/dev/null)
  if [ -n "$branch" ]; then
    dirty=""
    if ! git -C "$proj_dir" diff --quiet 2>/dev/null || \
       ! git -C "$proj_dir" diff --cached --quiet 2>/dev/null; then
      dirty="*"
    fi
    branch_disp="${C_MAGENTA}${branch}${dirty}${C_RESET}"
  fi
fi

# --- Group 1: "<folder>:<branch>" ----------------------------------------
folder_seg=""
if [ -n "$project" ]; then
  folder_seg="${C_BOLD}${project}${C_RESET}"
  [ -n "$branch_disp" ] && folder_seg="${folder_seg}:${branch_disp}"
fi

# --- Group 2: model (cyan) + readable effort suffix ----------------------
model_seg="${C_CYAN}${model}${C_RESET}"
if [ -n "$effort" ] && [ "$effort" != "null" ]; then
  case "$effort" in
    low)    eff="lo"  ;;
    medium) eff="med" ;;
    high)   eff="hi"  ;;
    xhigh)  eff="xhi" ;;
    *)      eff="${effort:0:4}" ;;   # graceful fallback for unknown values
  esac
  model_seg="${model_seg} ${C_RESET}- ${eff}${C_RESET}"
fi
# Fast-mode suffix: "<model> - <eff> / Fast" (shown only when enabled).
if [ "$fast_mode" = "true" ]; then
  model_seg="${model_seg} ${C_RESET}/ ${C_BOLD}Fast${C_RESET}"
fi

# --- Tokens (compact "Xk") -----------------------------------------------
tok_disp=""
tok_int=${total_tok%.*}; [ -z "$tok_int" ] && tok_int=0
if [ "$tok_int" -gt 0 ]; then
  if [ "$tok_int" -ge 1000 ]; then
    tok_disp=$(awk "BEGIN { printf \"%.0fk\", $tok_int/1000 }")
  else
    tok_disp="$tok_int"
  fi
fi

# --- Context fill percent (threshold-colored) ----------------------------
ctx_disp=""
if [ -n "$used_pct" ]; then
  used_int=$(printf '%.0f' "$used_pct")
  col=$(color_for "$used_int")
  ctx_disp="${col}${used_int}%${C_RESET}"
fi

# --- Group 3: "Context: <Xk> <ctx%>" -------------------------------------
ctx_seg=""
if [ -n "$tok_disp" ] || [ -n "$ctx_disp" ]; then
  ctx_seg="${C_RESET}Context:"
  [ -n "$tok_disp" ] && ctx_seg="${ctx_seg} ${C_RESET}${tok_disp}"
  if [ -n "$ctx_disp" ]; then
    # " - " only when a token count precedes it; otherwise just a space.
    [ -n "$tok_disp" ] && ctx_seg="${ctx_seg} ${C_RESET}-" || ctx_seg="${ctx_seg}"
    ctx_seg="${ctx_seg} ${ctx_disp}"
  fi
fi

# --- Rate limits ("<label>: <pct>-<renewal>") ----------------------------
five_int=""; [ -n "$five_pct" ] && five_int=$(printf '%.0f' "$five_pct")
week_int=""; [ -n "$week_pct" ] && week_int=$(printf '%.0f' "$week_pct")

render_quota() {  # args: label pct_int reset_raw
  local label=$1 pi=$2 reset=$3
  [ -z "$pi" ] && return
  local col rel txt
  col=$(color_for "$pi")
  txt="${C_RESET}${label}: ${col}${pi}%${C_RESET}"
  rel=$(fmt_reset "$reset")
  [ -n "$rel" ] && txt="${txt} ${C_RESET}- ${rel}"
  printf '%s' "$txt"
}

# --- Group 4: "Quota 5h: <..> 7d: <..>" ----------------------------------
five_render=$(render_quota "5h" "$five_int" "$five_reset")
week_render=$(render_quota "7d" "$week_int" "$week_reset")
quota_body=""
[ -n "$five_render" ] && quota_body="$five_render"
[ -n "$week_render" ] && quota_body="${quota_body:+$quota_body ${C_RESET}/ }$week_render"
quota_seg=""
[ -n "$quota_body" ] && quota_seg="${C_RESET}Quota ${quota_body}"

# --- Assemble ------------------------------------------------------------
parts=()
[ -n "$folder_seg" ] && parts+=("$folder_seg")
[ -n "$model_seg" ]  && parts+=("$model_seg")
[ -n "$ctx_seg" ]    && parts+=("$ctx_seg")
[ -n "$quota_seg" ]  && parts+=("$quota_seg")

sep="  ${C_RESET}|${C_RESET}  "
result=""
for part in "${parts[@]}"; do
  if [ -z "$result" ]; then result="$part"; else result="${result}${sep}${part}"; fi
done

printf '%s' "$result"
