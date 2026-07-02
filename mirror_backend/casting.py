import os
import subprocess
import uuid
import time
import threading
from .base import MirrorBackend
from .utils import get_adb_path, check_process_alive


MQDH_PATH = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Meta Quest Developer Hub")
CASTING_EXE = os.path.join(MQDH_PATH, "resources", "bin", "Casting", "Casting.exe")
MQDH_ADB = os.path.join(MQDH_PATH, "resources", "bin", "adb.exe")


def get_casting_exe():
    if os.path.exists(CASTING_EXE):
        return CASTING_EXE
    return None


def get_casting_adb():
    if os.path.exists(MQDH_ADB):
        return MQDH_ADB
    return get_adb_path()


class CastingBackend(MirrorBackend):
    def __init__(self):
        self.process = None
        self.serial = None
        self._session_uuid = None

    def start(self, serial: str, options: dict) -> None:
        if self.is_running():
            self.stop()

        self.serial = serial
        self._session_uuid = str(uuid.uuid4())

        casting_exe = get_casting_exe()
        if not casting_exe:
            raise FileNotFoundError(
                "Casting.exe not found. Meta Quest Developer Hub must be installed."
            )

        adb_path = get_casting_adb()
        cache_dir = os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Meta Quest Developer Hub",
            "MagicIsland",
            "Cache",
            serial,
        )
        os.makedirs(cache_dir, exist_ok=True)

        features = self._build_features(options)

        args = [
            casting_exe,
            "--adb", adb_path,
            "--application-caches-dir", cache_dir,
            "--exit-on-close",
            "--launch-surface", "MQDH",
            "--target-device", f'{{"id":"{serial}"}}',
            "--launch-surface-session-uuid", self._session_uuid,
        ]
        if features:
            args.append("--features")
            args.extend(features)

        print(f"[Casting] Launching: {' '.join(args)}")

        self.process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
        )

        def _log_output(stream, label):
            try:
                for line in stream:
                    text = line.decode("utf-8", errors="replace").strip()
                    if text:
                        print(f"[Casting/{label}] {text}")
            except Exception:
                pass

        threading.Thread(target=_log_output, args=(self.process.stdout, "out"), daemon=True).start()
        threading.Thread(target=_log_output, args=(self.process.stderr, "err"), daemon=True).start()

        time.sleep(1.0)
        if self.process.poll() is not None:
            raise RuntimeError(
                f"Casting.exe exited immediately with code {self.process.returncode}"
            )

    def _build_features(self, options: dict) -> list:
        features = []
        if options.get("panel_streaming"):
            features.append("panel_streaming")
        return features

    def stop(self) -> None:
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
            except Exception:
                pass
            self.process = None

        if self.serial:
            try:
                adb = get_adb_path()
                subprocess.run(
                    [adb, "-s", self.serial, "shell", "am", "broadcast",
                     "-a", "com.oculus.magicislandcastingservice.STOP_CASTING"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                    check=False,
                )
            except Exception:
                pass
            self.serial = None

    def is_running(self) -> bool:
        alive = check_process_alive(self.process)
        if not alive:
            return False
            
        import sys
        if sys.platform == 'win32':
            import ctypes
            import re
            
            # Find all PIDs for Casting.exe
            res = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Casting.exe", "/NH"], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
            pids = []
            for line in res.stdout.splitlines():
                m = re.search(r"Casting\.exe\s+(\d+)", line, re.IGNORECASE)
                if m:
                    pids.append(int(m.group(1)))
                    
            if not pids:
                return False
                
            EnumWindows = ctypes.windll.user32.EnumWindows
            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
            GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
            IsWindowVisible = ctypes.windll.user32.IsWindowVisible
            GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId

            found = False
            def foreach_window(hwnd, lParam):
                nonlocal found
                if IsWindowVisible(hwnd):
                    pid = ctypes.c_ulong()
                    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if pid.value in pids:
                        length = GetWindowTextLength(hwnd)
                        if length > 0:
                            found = True
                            return False # Stop
                return True

            EnumWindows(EnumWindowsProc(foreach_window), 0)
            if not found:
                # If alive but no window, force stop
                self.stop()
                return False
                
        return True
