import sys, os, asyncio, atexit

# Redirect stdout/stderr to log file with UTF-8
log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run.log")
log_file = open(log_path, "w", encoding="utf-8", buffering=1)
sys.stdout = log_file
sys.stderr = log_file

os.environ["PYTHONIOENCODING"] = "utf-8"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auto_shopper import acquire_lock, main_loop, release_lock

acquire_lock()
atexit.register(release_lock)
try:
    asyncio.run(main_loop())
finally:
    release_lock()
    log_file.close()
