import os
import sys
import subprocess
import uuid
import time
import threading
import ctypes
from ctypes import wintypes
from .base import MirrorBackend
from .utils import get_adb_path, check_process_alive


MQDH_PATH = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Meta Quest Developer Hub")
CASTING_EXE = os.path.join(MQDH_PATH, "resources", "bin", "Casting", "Casting.exe")
MQDH_ADB = os.path.join(MQDH_PATH, "resources", "bin", "adb.exe")

# Casting.exe can take several seconds to open its window while it negotiates
# with the headset. During this grace period we must not treat "no window yet"
# as "the user closed it", or we would kill a session that is still starting.
WINDOW_GRACE_SECONDS = 15.0
# The window scan (toolhelp snapshot + EnumWindows) is relatively expensive, so
# throttle it: the monitor polls once per second but we only re-scan this often.
WINDOW_CHECK_INTERVAL = 3.0


def get_casting_exe():
    if os.path.exists(CASTING_EXE):
        return CASTING_EXE
    return None


def get_casting_adb():
    """Return the adb the whole app uses.

    Casting.exe must talk to the *same* adb server as the rest of the app.
    The bundled adb (34.x) and MQDH's adb (35.x) are different versions, and
    adb kills+restarts any running server whose client version differs. If we
    hand Casting.exe a different adb than we use ourselves, the two clients
    fight over the server and the connection drops mid-cast. So we deliberately
    unify on the app's adb here, falling back to MQDH's only if that is all we
    have.
    """
    app_adb = get_adb_path()
    if app_adb == "adb" or os.path.exists(app_adb):
        return app_adb
    if os.path.exists(MQDH_ADB):
        return MQDH_ADB
    return "adb"


def _collect_process_tree_pids(root_pid):
    """Return {root_pid} plus all descendant PIDs via a toolhelp snapshot.

    Scoping the window check to this launch's own process tree (instead of
    every Casting.exe on the machine) is what makes multi-device mirroring
    reliable: closing device A's window must not look like device B is alive,
    and vice versa. Casting.exe may show its window from a child process, so we
    include the whole tree rather than just the launched PID.
    """
    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        return {root_pid}

    children = {}
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if not kernel32.Process32First(snapshot, ctypes.byref(entry)):
            return {root_pid}
        while True:
            children.setdefault(entry.th32ParentProcessID, []).append(entry.th32ProcessID)
            if not kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)

    result = set()
    stack = [root_pid]
    while stack:
        pid = stack.pop()
        if pid in result:
            continue
        result.add(pid)
        stack.extend(children.get(pid, []))
    return result


class CastingBackend(MirrorBackend):
    def __init__(self):
        self.process = None
        self.serial = None
        self._session_uuid = None
        self._lock = threading.RLock()
        self._start_time = None
        self._last_window_check = 0.0
        self._last_window_result = True

    def start(self, serial: str, options: dict) -> None:
        with self._lock:
            if check_process_alive(self.process):
                self._stop_locked()

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
            self._start_time = time.time()
            self._last_window_check = 0.0
            self._last_window_result = True

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
                code = self.process.returncode
                self.process = None
                self._start_time = None
                raise RuntimeError(
                    f"Casting.exe exited immediately with code {code}"
                )

    def _build_features(self, options: dict) -> list:
        features = []
        if options.get("panel_streaming"):
            features.append("panel_streaming")
        return features

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    self.process.kill()
                except Exception:
                    pass
            except Exception:
                pass
            self.process = None
        self._start_time = None

        if self.serial:
            try:
                adb = get_casting_adb()
                subprocess.run(
                    [adb, "-s", self.serial, "shell", "am", "broadcast",
                     "-a", "com.oculus.magicislandcastingservice.STOP_CASTING"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                )
            except Exception:
                pass
            self.serial = None

    def is_running(self) -> bool:
        with self._lock:
            if not check_process_alive(self.process):
                return False

            if sys.platform != 'win32':
                return True

            # While starting up, the window may not exist yet. Trust the
            # process during the grace period so we don't kill a live session.
            if self._start_time and (time.time() - self._start_time) < WINDOW_GRACE_SECONDS:
                return True

            now = time.time()
            if now - self._last_window_check < WINDOW_CHECK_INTERVAL:
                return self._last_window_result
            self._last_window_check = now

            if self._has_visible_window():
                self._last_window_result = True
                return True

            # Process alive but no visible window belonging to our tree: the
            # user closed the mirror window. With --exit-on-close it should
            # terminate on its own, but Casting.exe sometimes lingers, so we
            # tear it down explicitly here.
            self._stop_locked()
            self._last_window_result = False
            return False

    def _has_visible_window(self) -> bool:
        try:
            pids = _collect_process_tree_pids(self.process.pid)
        except Exception:
            # If we cannot enumerate processes, err on the side of "alive"
            # rather than killing a possibly-working session.
            return True

        EnumWindows = ctypes.windll.user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
        IsWindowVisible = ctypes.windll.user32.IsWindowVisible
        GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId

        found = {"value": False}

        def foreach_window(hwnd, lParam):
            if IsWindowVisible(hwnd):
                pid = wintypes.DWORD()
                GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value in pids and GetWindowTextLength(hwnd) > 0:
                    found["value"] = True
                    return False  # stop enumeration
            return True

        try:
            EnumWindows(EnumWindowsProc(foreach_window), 0)
        except Exception:
            return True

        return found["value"]
