from .base import MirrorBackend
from .utils import get_adb_path, check_process_alive, NO_WINDOW
import subprocess
import threading
import re
import sys
import time

class ScreenRecordBackend(MirrorBackend):
    def __init__(self):
        self.adb_process = None
        self.player_process = None
        self.window_title = None
        self.player_pid = None
        self.serial = None

    def start(self, serial: str, options: dict) -> None:
        self.serial = serial
        if self.is_running():
            self.stop()
            
        max_retries = 3
        import time
        
        for attempt in range(max_retries):
            try:
                self._start_attempt(serial, options)

                # Check if process died immediately (e.g. INVALID_LAYER_STACK).
                # _start_attempt already polls until screenrecord appears on the
                # device, so a short confirm here is enough (was a fixed 0.8s).
                time.sleep(0.3)
                if self.adb_process and self.adb_process.poll() is not None:
                     # It died, likely checking stderr would confirm INVALID_LAYER_STACK
                     raise RuntimeError("Screenrecord process terminated early.")
                
                # If still running, we assume success
                return
            except Exception as e:
                print(f"Mirror start attempt {attempt+1} failed: {e}")
                self.stop()
                if attempt < max_retries - 1:
                    print(f"Retrying in 1s...")
                    time.sleep(1.0)
                    
        raise RuntimeError(f"Failed to start mirror after {max_retries} attempts")

    def _start_attempt(self, serial: str, options: dict, use_display_flag: bool = True) -> None:
        # 0. Check if device is ADB-online
        import time
        adb = get_adb_path()
        device_online = False
        for _ in range(5): # Try for ~1s
            res = subprocess.run([adb, "-s", serial, "get-state"], capture_output=True, text=True, timeout=3, creationflags=NO_WINDOW)
            if res.returncode == 0 and res.stdout.strip() == "device":
                device_online = True
                break
            time.sleep(0.2)

        if not device_online:
            raise RuntimeError(f"Device {serial} is not online or not found in ADB.")

        # --- CRITICAL prep, one round-trip ---
        # Only the things that must happen *before* screenrecord starts:
        #  - kill any stale screenrecord (device allows only one at a time)
        #  - WAKEUP (a sleeping display captures a black/invalid frame)
        # Batching into a single `adb shell` avoids ~5 separate adb.exe spawns.
        try:
            subprocess.run(
                [adb, "-s", serial, "shell",
                 "killall screenrecord 2>/dev/null; input keyevent WAKEUP"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=5,
                creationflags=NO_WINDOW
            )
        except Exception as e:
            print(f"Warning: critical prep failed: {e}")

        # --- NON-CRITICAL prep, off the critical path ---
        # Proximity-off (always-on screen), stay-on and dismiss-keyguard don't
        # need to complete before the window appears. `svc power stayon` alone
        # takes ~1s on Quest, so running these in the background shaves that off
        # the perceived startup latency.
        def _bg_prep():
            try:
                subprocess.run(
                    [adb, "-s", serial, "shell",
                     "am broadcast -a com.oculus.vrpowermanager.automation_disable; "
                     "am broadcast -a com.oculus.vrpowermanager.prox_close; "
                     "svc power stayon true; wm dismiss-keyguard"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=15,
                    creationflags=NO_WINDOW
                )
            except Exception as e:
                print(f"Background prep error: {e}")
        threading.Thread(target=_bg_prep, daemon=True).start()

        width = options.get('width', 1280)
        height = options.get('height', 720)
        bitrate = options.get('bitrate', 5) # Mbps
        display_id = self._resolve_display_id(serial, options.get('display_id')) if use_display_flag else None

        # (Display list was already queried inside _resolve_display_id; avoid a
        # second `cmd display list` round-trip here.)
        if display_id is not None:
            print(f"[{time.strftime('%H:%M:%S')}] Using display-id {display_id}")
        else:
            print(f"[{time.strftime('%H:%M:%S')}] Using default display (no display-id flag)")

        # ADB Command
        adb_cmd = [
            get_adb_path(), "-s", serial, "exec-out", "screenrecord",
            f"--bit-rate={bitrate * 1000000}",
            "--output-format=h264", 
        ]
        if display_id is not None:
            adb_cmd.extend(["--display-id", str(display_id)])
        adb_cmd.extend(["--size", f"{width}x{height}", "-"])
        
        # Build ffplay command
        eye = options.get('eye', 'both')
        
        # VF filters.
        # The Quest screenrecord feed is a raw stereo *fisheye* passthrough
        # image (side-by-side, one circular fisheye per eye). We crop a SQUARE
        # centered on the selected eye's optical center, then rectify it.
        #
        # Cropping a centered square (rather than the full eye-half) matters:
        # `v360 input=fisheye` assumes the fisheye fills a square frame. Feeding
        # an off-center / non-square crop makes the flat projection sample the
        # black region *outside* the fisheye circle at one edge, which showed up
        # as the "broken periphery". crop_size / eye_cx / eye_cy are per-device
        # (config [Filters.*]) and describe that circle.
        half = width // 2
        crop_size = int(options.get('crop_size', half))
        eye_cx = float(options.get('eye_cx', half / 2))   # fisheye center x within a half
        eye_cy = float(options.get('eye_cy', height / 2))  # fisheye center y

        center_x = None
        if eye == '左眼':
            center_x = eye_cx
        elif eye == '右眼':
            center_x = half + eye_cx

        vf = []
        if center_x is not None:
            x0 = int(round(center_x - crop_size / 2))
            y0 = int(round(eye_cy - crop_size / 2))
            x0 = max(0, min(x0, width - crop_size))
            y0 = max(0, min(y0, height - crop_size))
            vf.append(f"crop={crop_size}:{crop_size}:{x0}:{y0}")

            # Distortion correction. A 2-coefficient `lenscorrection` only
            # partly flattens such a wide fisheye and leaves the edges warped
            # (why barrel correction "looked broken"). `v360` (fisheye->flat)
            # is purpose-built for this; `roll` levels the eye tilt.
            correction = options.get('correction', 'v360')
            if correction == 'v360':
                fov_in = options.get('fov_in', 150)   # input fisheye FOV (deg)
                fov_out = options.get('fov_out', 95)  # output flat FOV (deg)
                roll = options.get('roll', 0)         # tilt correction (deg)
                out = int(options.get('out_size', 720))
                vf.append(
                    "v360=input=fisheye:output=flat"
                    f":ih_fov={fov_in}:iv_fov={fov_in}"
                    f":h_fov={fov_out}:v_fov={fov_out}"
                    f":roll={roll}:w={out}:h={out}"
                )
            elif correction == 'lens':
                # Legacy path (rotate + polynomial lens correction).
                rotation = options.get('rotation', 0)
                k1 = options.get('k1', 0.0)
                k2 = options.get('k2', 0.0)
                if rotation != 0:
                    vf.append(f"rotate={rotation}*PI/180")
                if k1 != 0.0 or k2 != 0.0:
                    vf.append(f"lenscorrection=cx=0.5:cy=0.5:k1={k1}:k2={k2}")
            # correction == 'none' -> cropped eye without geometric correction
        # else: 両眼 (both) -> show the raw SBS frame (v360 is per-eye only)

        # Add setpts=0 to avoid buffering/sync issues
        vf.append("setpts=0")

        vf_str = ",".join(vf)
        
        # Use ffplay.
        # IMPORTANT: do NOT pass `-fflags nobuffer`. Despite its name, on this
        # raw-h264-over-pipe input it makes ffplay/ffmpeg spend ~11s before the
        # first frame is decoded (measured), which was the "window takes 10s+ to
        # appear" bug. `-flags low_delay` keeps latency low without that stall.
        player_cmd = [
            "ffplay",
            "-f", "h264",
            "-flags", "low_delay",
            "-framedrop",
            "-probesize", "32",
            "-sync", "ext",
            "-i", "-"
        ]
        if vf_str:
            player_cmd.extend(["-vf", vf_str])

        # Add title
        title = options.get('window_title', f"Quest Stream ({serial})")
        self.window_title = title
        player_cmd.extend(["-window_title", title])

        # Start Processes
        # 1. Start ADB
        self.adb_process = subprocess.Popen(
            adb_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=NO_WINDOW
        )
        
        # --- GUARD: Check if screenrecord is actually running ---
        # Poll for screenrecord to appear on the device instead of a fixed
        # 0.5s sleep. It normally shows up in ~50ms, so this returns almost
        # immediately on a healthy device, while still waiting up to ~2s on a
        # slow one (which avoids spurious "failed to start" retries that used
        # to add several seconds to startup).
        is_screenrecord_running = False
        adb_died = False
        for _ in range(20):  # up to ~2s
            if self.adb_process.poll() is not None:
                adb_died = True
                break
            try:
                res = subprocess.run([get_adb_path(), "-s", serial, "shell", "pidof", "screenrecord"],
                                   capture_output=True, text=True, timeout=2, creationflags=NO_WINDOW)
                if res.returncode == 0 and res.stdout.strip():
                    is_screenrecord_running = True
                    break
            except Exception:
                pass
            time.sleep(0.1)

        # Check if adb process itself died (e.g. device not found)
        if adb_died:
            adb_out, adb_err = self._collect_process_output(self.adb_process)
            detail = adb_err or adb_out
            if detail:
                detail = detail.strip()
            # Retry once without display-id if that might be the culprit
            if use_display_flag and detail and ("INVALID_LAYER_STACK" in detail or "Invalid physical display ID" in detail):
                print("Retrying screenrecord without --display-id due to display stack error...")
                return self._start_attempt(serial, options, use_display_flag=False)
            raise RuntimeError("ADB process terminated immediately (device disconnected?). " + (f"Details: {detail}" if detail else ""))

        if not is_screenrecord_running:
            # Collect output *before* tearing the process down, otherwise we
            # pass None to _collect_process_output and the INVALID_LAYER_STACK
            # retry below can never trigger.
            adb_out, adb_err = self._collect_process_output(self.adb_process)
            try:
                self.adb_process.terminate()
            except Exception:
                pass
            self.adb_process = None
            detail = adb_err or adb_out
            if detail:
                detail = detail.strip()
            if use_display_flag and detail and ("INVALID_LAYER_STACK" in detail or "Invalid physical display ID" in detail):
                print("Retrying screenrecord without --display-id due to display stack error...")
                return self._start_attempt(serial, options, use_display_flag=False)
            raise RuntimeError("screenrecord process failed to start on device (pidof verification failed). " + (f"Details: {detail}" if detail else ""))
        # --------------------------------------------------------

        
        # 2. Start Player (ffplay)
        self.player_process = subprocess.Popen(
            player_cmd, stdin=self.adb_process.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=NO_WINDOW
        )
        self.player_pid = self.player_process.pid
        print(f"[{time.strftime('%H:%M:%S')}] Player process started (PID {self.player_pid}): {player_cmd}")

        # Debug logging threads
        def log_stderr(process, name):
            try:
                for line in process.stderr:
                    print(f"[{name}] {line.decode('utf-8', errors='replace').strip()}")
            except Exception as e:
                print(f"Error reading {name} stderr: {e}")

        threading.Thread(target=log_stderr, args=(self.adb_process, "ADB"), daemon=True).start()
        if self.player_process:
            threading.Thread(target=log_stderr, args=(self.player_process, "Player"), daemon=True).start()

    def _log_display_info(self, serial: str, chosen_display_id):
        """Print available displays and chosen id to aid troubleshooting."""
        try:
            res = subprocess.run(
                [get_adb_path(), "-s", serial, "shell", "cmd", "display", "list"],
                capture_output=True, text=True, timeout=2.0, creationflags=NO_WINDOW
            )
            summary = res.stdout.strip().splitlines()
            if len(summary) > 10:
                summary = summary[:10] + ["..."]
            print(f"[{time.strftime('%H:%M:%S')}] Displays (cmd display list): {summary}")
        except Exception as e:
            print(f"Warning: failed to log display list: {e}")

        if chosen_display_id is not None:
            print(f"[{time.strftime('%H:%M:%S')}] Using display-id {chosen_display_id}")
        else:
            print(f"[{time.strftime('%H:%M:%S')}] Using default display (no display-id flag)")

    def _resolve_display_id(self, serial: str, requested_id):
        """Pick a valid display id; if none, return None to skip the flag."""
        available = self._list_display_ids(serial)
        if not available:
            return None

        primary = min(available)

        if requested_id is None:
            # If only one display is reported and it's primary, we can skip the flag
            if len(available) == 1:
                return None
            return primary

        try:
            requested_int = int(requested_id)
        except Exception:
            print(f"Warning: display_id '{requested_id}' is not an integer; using primary {primary}")
            return primary

        if requested_int in available:
            return requested_int

        print(f"Warning: requested display_id {requested_int} not in available displays {available}; using primary {primary}")
        return primary

    def _list_display_ids(self, serial: str):
        """Parse display ids from `cmd display list`; fallback to [0] on error."""
        try:
            res = subprocess.run(
                [get_adb_path(), "-s", serial, "shell", "cmd", "display", "list"],
                capture_output=True, text=True, timeout=2.0, creationflags=NO_WINDOW
            )
            if res.returncode != 0:
                return [0]

            ids = set()
            for line in res.stdout.splitlines():
                m = re.search(r"Display\s+(\d+)", line)
                if m:
                    ids.add(int(m.group(1)))
            if ids:
                return sorted(ids)
        except Exception as e:
            print(f"Warning: failed to list display ids: {e}")
        return [0]

    def _collect_process_output(self, process):
        """Drain short-lived process output for better error messages."""
        stdout_data = b""
        stderr_data = b""
        try:
            stdout_data, stderr_data = process.communicate(timeout=0.2)
        except Exception:
            try:
                if process.stdout:
                    stdout_data = process.stdout.read() or b""
            except Exception:
                pass
            try:
                if process.stderr:
                    stderr_data = process.stderr.read() or b""
            except Exception:
                pass
        return stdout_data.decode(errors="replace"), stderr_data.decode(errors="replace")

    def stop(self) -> None:
        # 1) Stop ADB first so ffplay gets EOF
        if self.adb_process:
            print(f"[{time.strftime('%H:%M:%S')}] Stopping adb screenrecord...")
            try:
                self.adb_process.terminate()
                self.adb_process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.adb_process.kill()
            except Exception:
                pass
            self.adb_process = None
            time.sleep(0.3)

        # 2) Then stop ffplay/ffmpeg player
        if self.player_process:
            print(f"[{time.strftime('%H:%M:%S')}] Stopping player process (PID {self.player_pid})...")

            # Try to resolve PID by window title via tasklist /V (more reliable)
            if sys.platform == 'win32' and self.window_title:
                try:
                    tl = subprocess.run(["tasklist", "/V", "/FI", "IMAGENAME eq ffplay.exe"], capture_output=True, text=True, creationflags=NO_WINDOW)
                    matched_pid = None
                    for line in tl.stdout.splitlines():
                        if self.window_title in line:
                            m = re.search(r"ffplay\.exe\s+(\d+)", line, re.IGNORECASE)
                            if m:
                                matched_pid = m.group(1)
                                break
                    if matched_pid:
                        print(f"[{time.strftime('%H:%M:%S')}] Found ffplay PID by title: {matched_pid}")
                        subprocess.run(["taskkill", "/F", "/T", "/PID", matched_pid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, creationflags=NO_WINDOW)
                except Exception as e:
                    print(f"[{time.strftime('%H:%M:%S')}] tasklist parse error: {e}")

            # On Windows, try killing by window title directly
            if sys.platform == 'win32' and self.window_title:
                try:
                    result = subprocess.run(
                        ["taskkill", "/F", "/FI", f"WINDOWTITLE eq {self.window_title}"],
                        capture_output=True, text=True, check=False, creationflags=NO_WINDOW
                    )
                    print(f"[{time.strftime('%H:%M:%S')}] taskkill by title result: rc={result.returncode}, out={result.stdout.strip()}, err={result.stderr.strip()}")
                except Exception as e:
                    print(f"[{time.strftime('%H:%M:%S')}] taskkill by title error: {e}")

            # Then try by PID and process tree
            if sys.platform == 'win32' and self.player_pid:
                try:
                    result = subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(self.player_pid)],
                        capture_output=True, text=True, check=False, creationflags=NO_WINDOW
                    )
                    print(f"[{time.strftime('%H:%M:%S')}] taskkill result: returncode={result.returncode}, stdout={result.stdout.strip()}, stderr={result.stderr.strip()}")

                    # Double-check if process is really gone
                    time.sleep(0.2)
                    check_result = subprocess.run(
                        ["tasklist", "/FI", f"PID eq {self.player_pid}"],
                        capture_output=True, text=True, creationflags=NO_WINDOW
                    )
                    if str(self.player_pid) in check_result.stdout:
                        print(f"[{time.strftime('%H:%M:%S')}] WARNING: Process {self.player_pid} still running after taskkill!")
                        # Try one more time with absolute force
                        subprocess.run(["taskkill", "/F", "/PID", str(self.player_pid)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
                    else:
                        print(f"[{time.strftime('%H:%M:%S')}] Successfully killed player process {self.player_pid}")
                        
                except Exception as e:
                    print(f"[{time.strftime('%H:%M:%S')}] taskkill error: {e}")
            
            # Fallback termination
            try:
                if self.player_process.poll() is None:
                    self.player_process.terminate()
                    self.player_process.wait(timeout=1)
            except:
                pass

            # NOTE: We deliberately do NOT `taskkill /IM ffplay.exe` here. That
            # would kill *every* ffplay instance on the machine, which breaks
            # multi-device mirroring (stopping one device closes all the others)
            # and any unrelated ffplay the user has open. The title/PID-scoped
            # kills above are sufficient to stop this backend's own player.

            self.player_process = None
            self.player_pid = None
            self.window_title = None
            
        
        
        # Safe Device Cleanup
        if self.serial:
            try:
                # Check online first
                res = subprocess.run([get_adb_path(), "-s", self.serial, "get-state"],
                                   capture_output=True, text=True, timeout=1.0, creationflags=NO_WINDOW)
                if res.returncode == 0 and res.stdout.strip() == "device":
                    # Device is online, try to cleanup
                    subprocess.run([get_adb_path(), "-s", self.serial, "shell", "killall", "screenrecord"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, creationflags=NO_WINDOW)
                    # Restore proximity sensor state
                    subprocess.run([get_adb_path(), "-s", self.serial, "shell", "am", "broadcast", "-a", "com.oculus.vrpowermanager.automation_disable"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, creationflags=NO_WINDOW)
            except Exception:
                # Ignore any errors during stop cleanup (device might be gone)
                pass
            self.serial = None

    def is_running(self) -> bool:
        if not check_process_alive(self.player_process):
            return False
        # The player (ffplay) keeps its window open showing the last frame even
        # after the device-side screenrecord/adb feed dies (e.g. screenrecord's
        # ~3 minute limit, or the headset going to sleep). Treat a dead feed as
        # "not running" so the monitor can clean up instead of leaving a frozen
        # window that still looks connected.
        if self.adb_process is not None and not check_process_alive(self.adb_process):
            return False
        return True
