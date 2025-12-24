import os
import sys
import subprocess

def get_base_path():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(__file__))

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
