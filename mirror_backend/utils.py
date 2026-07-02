import os
import sys
import subprocess

# Suppresses the console-window flash on Windows for every subprocess call
# (adb, taskkill, tasklist, ...) spawned from this -w/--noconsole packaged
# app. Without it, each console-subsystem child process briefly pops its own
# window because the parent GUI process has no console of its own.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0

def get_base_path():
    """Read-only bundle root. For a --onefile build this is the ephemeral
    per-launch extraction dir (sys._MEIPASS) -- anything written here does not
    survive to the next launch. Use get_user_config_path() for files that must
    persist (e.g. config.ini)."""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(__file__))

def get_user_config_path():
    """Persistent, writable location for config.ini: next to the .exe when
    frozen (survives restarts, unlike get_base_path()'s temp dir), or the
    project root in dev mode."""
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = get_base_path()
    return os.path.join(base, 'config.ini')

def get_adb_path():
    if sys.platform == 'win32':
        bundled_adb = os.path.join(get_base_path(), "scrcpy", "adb.exe")
        if os.path.exists(bundled_adb):
            return bundled_adb
    return "adb"

def get_scrcpy_path():
    if sys.platform == 'win32':
        bundled_scrcpy = os.path.join(get_base_path(), "scrcpy", "scrcpy.exe")
        if os.path.exists(bundled_scrcpy):
            return bundled_scrcpy
    return "scrcpy"

def check_process_alive(process):
    if process is None:
        return False
    return process.poll() is None
