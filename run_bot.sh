#!/usr/bin/env bash
#
# atlas_run.sh
# Atlas canlı izleme botu için süpervizör.
# - Botu nohup + arka planda başlatır.
# - Crash/exit sonrası RESTART_DELAY saniye sonra otomatik yeniden başlatır.
# - PID ve log dosyalarını yönetir.
#
# Kullanım:
#   ./atlas_run.sh start          # botu arka planda başlat (süpervizör döngüsü)
#   ./atlas_run.sh start-foreground
#   ./atlas_run.sh stop
#   ./atlas_run.sh status
#   ./atlas_run.sh restart
#   ./atlas_run.sh logs [-f]
#
set -uo pipefail

cd "$(dirname "$(readlink -f "$0")")"

PYTHON="${PYTHON:-venv/bin/python}"
MAIN="${MAIN:-main.py}"
RUN_DIR="${RUN_DIR:-run}"
PID_FILE="${RUN_DIR}/atlas_bot.pid"
LOG_FILE="${LOG_DIR:-${RUN_DIR}/atlas_bot.log}"
RESTART_DELAY="${RESTART_DELAY:-10}"

# Süper döngü öncesi ortam ayarları (env veya boştaki ayarlarla ezilebilir)
DEFAULT_SCAN_INTERVAL="${ATLAS_SCAN_INTERVAL_SECONDS:-900}"
DEFAULT_MAX_SYMBOLS="${ATLAS_MAX_SYMBOLS:-100}"

mkdir -p "$RUN_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

run_bot() {
  log "Atlas baslatiliyor: ${MAIN} (interval=${DEFAULT_SCAN_INTERVAL}s, max_symbols=${DEFAULT_MAX_SYMBOLS})"
  env \
    ATLAS_SCAN_INTERVAL_SECONDS="$DEFAULT_SCAN_INTERVAL" \
    ATLAS_MAX_SYMBOLS="$DEFAULT_MAX_SYMBOLS" \
    "$PYTHON" "$MAIN" >>"$LOG_FILE" 2>&1
}

is_running() {
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
  fi
  return 1
}

start() {
  if is_running; then
    log "Zaten calisiyor (pid=$(cat "$PID_FILE")). Once 'stop' yapin."
    return 1
  fi

  # Alt subshell için gerekli değişkenleri dışa aktar (declare -f fonksiyon
  # gövdelerinde $DEĞİŞKEN referansları olduğundan bunlar subshell'de dolu olmalı).
  export PYTHON MAIN RUN_DIR PID_FILE LOG_FILE RESTART_DELAY
  export DEFAULT_SCAN_INTERVAL DEFAULT_MAX_SYMBOLS

  detached() {
    while :; do
      run_bot
      local code=$?
      log "Bot cikti (exit=${code}). ${RESTART_DELAY}s sonra yeniden baslatiliyor..."
      sleep "$RESTART_DELAY"
    done
  }
  nohup bash -c "$(declare -f detached run_bot log); detached" >/dev/null 2>&1 &
  echo $! > "$PID_FILE"
  log "Supervizor baslatildi (pid=$(cat "$PID_FILE"), log=${LOG_FILE})."
}

stop() {
  if is_running; then
    local pid
    pid="$(cat "$PID_FILE")"
    # Süper döngü ve tüm alt süreçleri kapat
    pkill -P "$pid" 2>/dev/null || true
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 10); do
      if ! kill -0 "$pid" 2>/dev/null; then break; fi
      sleep 0.5
    done
    rm -f "$PID_FILE"
    log "Durduruldu."
  else
    log "Calisan bot yok."
  fi
}

status() {
  if is_running; then
    log "Calisiyor (pid=$(cat "$PID_FILE")) | log=${LOG_FILE}"
  else
    log "Durmus."
  fi
  return 0
}

restart() {
  stop
  sleep 1
  start
}

start-foreground() {
  if is_running; then
    log "Zaten calisiyor (pid=$(cat "$PID_FILE")). Once 'stop' yapin."
    return 1
  fi
  run_bot
}

case "${1:-status}" in
  start) start ;;
  start-foreground) start-foreground ;;
  stop) stop ;;
  restart) restart ;;
  status) status ;;
  logs)
    [[ "$#" -ge 2 && "$2" = "-f" ]] && tail -f "$LOG_FILE" || tail -n 50 "$LOG_FILE"
    ;;
  *)
    echo "Kullanim: $0 {start|start-foreground|stop|restart|status|logs [-f]}"
    ;;
esac