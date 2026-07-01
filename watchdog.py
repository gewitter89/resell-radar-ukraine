"""
Watchdog for Shopping Bot.
- Monitors if bot is running
- Restarts if it crashes
- Auto-kills conflicting processes on same bot token
- Runs as background process
"""
import os
import sys
import time
import subprocess
import signal
from pathlib import Path

BOT_SCRIPT = Path(__file__).parent / "shopping_bot.py"
LOG_FILE = Path(__file__).parent / "shopping_bot_watchdog.log"
LOCK_FILE = Path(__file__).parent / "shopper.lock"
CHECK_INTERVAL = 15

bot_process = None


def log(msg):
    t = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{t}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def kill_conflict_pids():
    """Kill any other process using resell_radar bot token polling."""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile",
             "Get-Process python*,pythonw* -ErrorAction SilentlyContinue | "
             "Select-Object -ExpandProperty Id"],
            capture_output=True, text=True, timeout=10,
        )
        my_pid = os.getpid()
        bot_pid = bot_process.pid if bot_process else -1
        for pid_str in result.stdout.strip().split():
            try:
                pid = int(pid_str)
                if pid in (my_pid, bot_pid):
                    continue
                # Check if it's OLX/radar or auto_shopper main_loop
                ps_cmd = f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"
                r = subprocess.run(
                    ["powershell.exe", "-NoProfile", ps_cmd],
                    capture_output=True, text=True, timeout=5,
                )
                cmdline = r.stdout.strip().lower()
                if "shopping_bot" in cmdline and pid != bot_pid:
                    log(f"🗑 Killing duplicate shopping_bot PID {pid}")
                    os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
    except Exception as e:
        log(f"⚠️ kill_conflict_pids error: {e}")


def start_bot():
    global bot_process
    log("🚀 Starting Shopping Bot...")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    bot_process = subprocess.Popen(
        [sys.executable, str(BOT_SCRIPT)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    log(f"✅ Bot started, PID={bot_process.pid}")
    return bot_process


def main():
    log("=" * 40)
    log("🛡️ Shopping Bot Watchdog starting")
    log(f"📜 Script: {BOT_SCRIPT}")
    log(f"📄 Lock: {LOCK_FILE}")

    # Write lock file
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))

    start_bot()
    last_health = time.time()

    try:
        while True:
            time.sleep(CHECK_INTERVAL)

            if bot_process is None:
                start_bot()
                continue

            retcode = bot_process.poll()
            if retcode is not None:
                log(f"💥 Bot exited with code {retcode}")
                # Drain output
                try:
                    stdout = bot_process.stdout.read().decode("utf-8", errors="replace")
                    stderr = bot_process.stderr.read().decode("utf-8", errors="replace")
                    if stdout:
                        log(f"STDOUT tail: {stdout[-500:]}")
                    if stderr:
                        log(f"STDERR tail: {stderr[-500:]}")
                except Exception:
                    pass
                time.sleep(3)
                start_bot()
                continue

            # Heartbeat
            if time.time() - last_health > 60:
                last_health = time.time()
                log(f"💚 Bot healthy, PID={bot_process.pid}")

    except KeyboardInterrupt:
        log("⏹ Watchdog stopped by user")
        if bot_process:
            bot_process.terminate()
            try:
                bot_process.wait(timeout=5)
            except Exception:
                bot_process.kill()
    finally:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
        log("🛡️ Watchdog shutdown")


if __name__ == "__main__":
    main()
