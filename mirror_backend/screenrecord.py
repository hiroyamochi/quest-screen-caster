from .base import MirrorBackend
from .utils import get_adb_path, check_process_alive
import subprocess
import threading
import shlex
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
                
                # Check if process died immediately (e.g. INVALID_LAYER_STACK)
                time.sleep(0.8)
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
        device_online = False
        for _ in range(5): # Try for ~1s
            res = subprocess.run([get_adb_path(), "-s", serial, "get-state"], capture_output=True, text=True)
            if res.returncode == 0 and res.stdout.strip() == "device":
                device_online = True
                break
            time.sleep(0.2)
            
        if not device_online:
            raise RuntimeError(f"Device {serial} is not online or not found in ADB.")

        # Cleanup any zombie screenrecord processes on the device
        try:
            # 1. Try polite kill first
            subprocess.run(
                [get_adb_path(), "-s", serial, "shell", "killall", "screenrecord"], 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL,
                check=False
            )
            
            # 2. Check if any are still running and force kill
            res = subprocess.run(
                [get_adb_path(), "-s", serial, "shell", "pidof", "screenrecord"],
                capture_output=True, text=True
            )
            
            if res.returncode == 0 and res.stdout.strip():
                pids = res.stdout.strip().split()
                print(f"Found lingering screenrecord processes: {pids}. Killing...")
                for pid in pids:
                     subprocess.run(
                        [get_adb_path(), "-s", serial, "shell", "kill", "-9", pid],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
                    )
            
        except Exception as e:
            print(f"Warning: Failed to cleanup screenrecord processes: {e}")
            pass
            
        # Wake device and disable proximity sensor to prevent black screen/errors
        try:
            # Quick wake check - if already awake, skip expensive dumpsys loop
            res = subprocess.run(
                [get_adb_path(), "-s", serial, "shell", "dumpsys", "power"], 
                capture_output=True, text=True, timeout=1.0
            )
            is_awake = "mWakefulness=Awake" in res.stdout
            
            if not is_awake:
                # Only do wake loop if device is actually asleep
                for _ in range(3):  # Reduced from 5 to 3
                    subprocess.run(
                        [get_adb_path(), "-s", serial, "shell", "input", "keyevent", "WAKEUP"], 
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
                    )
                    time.sleep(0.3)  # Reduced from 0.5
                    res = subprocess.run(
                        [get_adb_path(), "-s", serial, "shell", "dumpsys", "power"], 
                        capture_output=True, text=True, timeout=1.0
                    )
                    if "mWakefulness=Awake" in res.stdout:
                        is_awake = True
                        break
            
            if not is_awake:
                print(f"Warning: Device {serial} did not report Awake state, trying to proceed anyway...")

            # Disable proximity sensor for always-on screen during mirroring
            subprocess.run([get_adb_path(), "-s", serial, "shell", "am", "broadcast", "-a", "com.oculus.vrpowermanager.automation_disable"], 
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            subprocess.run([get_adb_path(), "-s", serial, "shell", "am", "broadcast", "-a", "com.oculus.vrpowermanager.prox_close"], 
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            
            print(f"[{time.strftime('%H:%M:%S')}] Proximity sensor disabled for always-on screen during mirroring")
            
            # Keep screen on and clear locks
            subprocess.run([get_adb_path(), "-s", serial, "shell", "svc", "power", "stayon", "true"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            subprocess.run([get_adb_path(), "-s", serial, "shell", "wm", "dismiss-keyguard"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        except Exception as e:
            print(f"Wakeup sequence error: {e}")
            pass
            
        width = options.get('width', 1280)
        height = options.get('height', 720)
        bitrate = options.get('bitrate', 5) # Mbps
        display_id = self._resolve_display_id(serial, options.get('display_id')) if use_display_flag else None

        # Log display info for debugging invalid layer errors
        self._log_display_info(serial, display_id)
        
        # ADB Command
        adb_cmd = [
            get_adb_path(), "-s", serial, "exec-out", "screenrecord",
            f"--bit-rate={bitrate * 1000000}",
            "--output-format=h264", 
        ]
        if display_id is not None:
            adb_cmd.extend(["--display-id", str(display_id)])
        adb_cmd.extend(["--size", f"{width}x{height}", "-"])
        
        # Build FFmpeg/FFplay command
        mode = options.get('mode', 'window')
        eye = options.get('eye', 'both')
        
        # VF filters for cropping
        # Quest 2/3 default is SBS.
        # We assume input is the raw full SBS frame.
        # crop=width:height:x:y
        vf = []
        if eye == '左眼':
            vf.append(f"crop={width//2}:{height}:0:0")
        elif eye == '右眼':
            vf.append(f"crop={width//2}:{height}:{width//2}:0")
            
        # Get filter options
        rotation = options.get('rotation', 0)
        k1 = options.get('k1', 0.0)
        k2 = options.get('k2', 0.0)
        
        # 1. Rotation (rotate=angle*PI/180)
        if rotation != 0:
            vf.append(f"rotate={rotation}*PI/180")
            
        # 2. Lens Correction (lenscorrection=k1:k2)
        if k1 != 0.0 or k2 != 0.0:
            vf.append(f"lenscorrection=cx=0.5:cy=0.5:k1={k1}:k2={k2}")
            
        # Add setpts=0 to avoid buffering/sync issues
        vf.append("setpts=0")
            
        vf_str = ",".join(vf)
        
        if mode == 'window':
    
            # Use ffplay
            # Match user's working command flags
            player_cmd = [
                "ffplay", 
                "-f", "h264", 
                "-fflags", "nobuffer", 
                "-flags", "low_delay", 
                "-framedrop", 
                "-probesize", "256000", 
                "-analyzeduration", "200000",
                "-sync", "ext",
                "-i", "-"
            ]
            if vf_str:
                player_cmd.extend(["-vf", vf_str])
            
            # Add title
            title = options.get('window_title', f"Quest Stream ({serial})")
            self.window_title = title
            player_cmd.extend(["-window_title", title])
            
        elif mode == 'obs':
            # Use ffmpeg to UDP
            udp_port = options.get('udp_port', 12345)
            player_cmd = ["ffmpeg", "-f", "h264", "-fflags", "nobuffer", "-flags", "low_delay", "-i", "-"]
            if vf_str:
                player_cmd.extend(["-vf", vf_str])
            
            # Output to MPEG-TS UDP
            player_cmd.extend(["-f", "mpegts", f"udp://127.0.0.1:{udp_port}?pkt_size=1316"])
            
        else:
            raise ValueError(f"Unknown mode: {mode}")

        # Start Processes
        # 1. Start ADB
        self.adb_process = subprocess.Popen(
            adb_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )
        
        # --- GUARD: Check if screenrecord is actually running ---
        # Only check this if not windows? 'pidof' is standard on Android.
        time.sleep(0.5)
        
        # Check if adb process itself died (e.g. device not found)
        if self.adb_process.poll() is not None:
            adb_out, adb_err = self._collect_process_output(self.adb_process)
            detail = adb_err or adb_out
            if detail:
                detail = detail.strip()
            # Retry once without display-id if that might be the culprit
            if use_display_flag and detail and ("INVALID_LAYER_STACK" in detail or "Invalid physical display ID" in detail):
                print("Retrying screenrecord without --display-id due to display stack error...")
                return self._start_attempt(serial, options, use_display_flag=False)
            raise RuntimeError("ADB process terminated immediately (device disconnected?). " + (f"Details: {detail}" if detail else ""))

        # Check process on device
        is_screenrecord_running = False
        try:
            res = subprocess.run([get_adb_path(), "-s", serial, "shell", "pidof", "screenrecord"],
                               capture_output=True, text=True)
            if res.returncode == 0 and res.stdout.strip():
                is_screenrecord_running = True
        except:
            pass
             
        if not is_screenrecord_running:
            # Stop Start process
            self.adb_process.terminate()
            self.adb_process = None
            adb_out, adb_err = self._collect_process_output(self.adb_process)
            detail = adb_err or adb_out
            if detail:
                detail = detail.strip()
            if use_display_flag and detail and ("INVALID_LAYER_STACK" in detail or "Invalid physical display ID" in detail):
                print("Retrying screenrecord without --display-id due to display stack error...")
                return self._start_attempt(serial, options, use_display_flag=False)
            raise RuntimeError("screenrecord process failed to start on device (pidof verification failed). " + (f"Details: {detail}" if detail else ""))
        # --------------------------------------------------------

        
        # 2. Start Player (FFmpeg/FFplay) reading from ADB stdout
        self.player_process = subprocess.Popen(
            player_cmd, stdin=self.adb_process.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )
        self.player_pid = self.player_process.pid
        print(f"[{time.strftime('%H:%M:%S')}] Player process started (PID {self.player_pid}): {player_cmd}")
        
        # NOTE: We DO NOT close adb_process.stdout here anymore, 
        # because it might cause broken pipe or race conditions.
        # self.adb_process.stdout.close()

        # Debug logging threads
        def log_stderr(process, name):
            try:
                for line in process.stderr:
                    print(f"[{name}] {line.decode('utf-8', errors='replace').strip()}")
            except Exception as e:
                print(f"Error reading {name} stderr: {e}")

        threading.Thread(target=log_stderr, args=(self.adb_process, "ADB"), daemon=True).start()
        threading.Thread(target=log_stderr, args=(self.player_process, "Player"), daemon=True).start()

    def _log_display_info(self, serial: str, chosen_display_id):
        """Print available displays and chosen id to aid troubleshooting."""
        try:
            res = subprocess.run(
                [get_adb_path(), "-s", serial, "shell", "cmd", "display", "list"],
                capture_output=True, text=True, timeout=2.0
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
                capture_output=True, text=True, timeout=2.0
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
                    tl = subprocess.run(["tasklist", "/V", "/FI", "IMAGENAME eq ffplay.exe"], capture_output=True, text=True)
                    matched_pid = None
                    for line in tl.stdout.splitlines():
                        if self.window_title in line:
                            m = re.search(r"ffplay\.exe\s+(\d+)", line, re.IGNORECASE)
                            if m:
                                matched_pid = m.group(1)
                                break
                    if matched_pid:
                        print(f"[{time.strftime('%H:%M:%S')}] Found ffplay PID by title: {matched_pid}")
                        subprocess.run(["taskkill", "/F", "/T", "/PID", matched_pid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                except Exception as e:
                    print(f"[{time.strftime('%H:%M:%S')}] tasklist parse error: {e}")

            # On Windows, try killing by window title directly
            if sys.platform == 'win32' and self.window_title:
                try:
                    result = subprocess.run(
                        ["taskkill", "/F", "/FI", f"WINDOWTITLE eq {self.window_title}"],
                        capture_output=True, text=True, check=False
                    )
                    print(f"[{time.strftime('%H:%M:%S')}] taskkill by title result: rc={result.returncode}, out={result.stdout.strip()}, err={result.stderr.strip()}")
                except Exception as e:
                    print(f"[{time.strftime('%H:%M:%S')}] taskkill by title error: {e}")

            # Then try by PID and process tree
            if sys.platform == 'win32' and self.player_pid:
                try:
                    result = subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(self.player_pid)],
                        capture_output=True, text=True, check=False
                    )
                    print(f"[{time.strftime('%H:%M:%S')}] taskkill result: returncode={result.returncode}, stdout={result.stdout.strip()}, stderr={result.stderr.strip()}")
                    
                    # Double-check if process is really gone
                    time.sleep(0.2)
                    check_result = subprocess.run(
                        ["tasklist", "/FI", f"PID eq {self.player_pid}"],
                        capture_output=True, text=True
                    )
                    if str(self.player_pid) in check_result.stdout:
                        print(f"[{time.strftime('%H:%M:%S')}] WARNING: Process {self.player_pid} still running after taskkill!")
                        # Try one more time with absolute force
                        subprocess.run(["taskkill", "/F", "/PID", str(self.player_pid)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        
            # Last resort: kill any remaining ffplay.exe (may affect external ffplay instances)
            if sys.platform == 'win32':
                try:
                    subprocess.run(["taskkill", "/F", "/IM", "ffplay.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                    print(f"[{time.strftime('%H:%M:%S')}] taskkill /IM ffplay.exe issued as last resort")
                except Exception as e:
                    print(f"[{time.strftime('%H:%M:%S')}] taskkill by image failed: {e}")
            
            self.player_process = None
            self.player_pid = None
            self.window_title = None
            
        
        
        # Safe Device Cleanup
        if self.serial:
            try:
                # Check online first
                res = subprocess.run([get_adb_path(), "-s", self.serial, "get-state"], 
                                   capture_output=True, text=True, timeout=1.0)
                if res.returncode == 0 and res.stdout.strip() == "device":
                    # Device is online, try to cleanup
                    subprocess.run([get_adb_path(), "-s", self.serial, "shell", "killall", "screenrecord"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                    # Restore proximity sensor state
                    subprocess.run([get_adb_path(), "-s", self.serial, "shell", "am", "broadcast", "-a", "com.oculus.vrpowermanager.automation_disable"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            except Exception:
                # Ignore any errors during stop cleanup (device might be gone)
                pass
            self.serial = None

    def is_running(self) -> bool:
        return check_process_alive(self.player_process)
