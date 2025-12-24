from .base import MirrorBackend
from .utils import get_adb_path, check_process_alive
import subprocess
import threading
import shlex

class ScreenRecordBackend(MirrorBackend):
    def __init__(self):
        self.adb_process = None
        self.player_process = None
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

    def _start_attempt(self, serial: str, options: dict) -> None:
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
            
            # 3. Wait a moment for hardware encoder to be released
            time.sleep(0.5)
            
        except Exception as e:
            print(f"Warning: Failed to cleanup screenrecord processes: {e}")
            pass
            
        # Wake device and disable proximity sensor to prevent black screen/errors
        try:
            # Explicitly check for Awake state
            is_awake = False
            for _ in range(10): # Try for ~5 seconds
                res = subprocess.run(
                    [get_adb_path(), "-s", serial, "shell", "dumpsys", "power"], 
                    capture_output=True, text=True
                )
                if "mWakefulness=Awake" in res.stdout:
                    is_awake = True
                    break
                
                # If not Awake, send WAKEUP
                subprocess.run(
                    [get_adb_path(), "-s", serial, "shell", "input", "keyevent", "WAKEUP"], 
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
                )
                time.sleep(0.5)
            
            if not is_awake:
                print(f"Warning: Device {serial} did not report Awake state, trying to proceed anyway...")

            # Wait for screen to actually turn on (display stack to initialize)
            time.sleep(1.0)

            # Disable proximity sensor (often causes black screen on mirror)
            # Use prox_close to simulate user presence (screen ON)
            subprocess.run([get_adb_path(), "-s", serial, "shell", "am", "broadcast", "-a", "com.oculus.vrpowermanager.prox_close"], 
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            
            # Also try automation_disable as backup
            subprocess.run([get_adb_path(), "-s", serial, "shell", "am", "broadcast", "-a", "com.oculus.vrpowermanager.automation_disable"], 
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
             
             # Wait a bit for system to stabilize
            time.sleep(0.5)
        except Exception as e:
            print(f"Wakeup sequence error: {e}")
            pass
            
        width = options.get('width', 1280)
        height = options.get('height', 720)
        bitrate = options.get('bitrate', 5) # Mbps
        
        # ADB Command
        adb_cmd = [
            get_adb_path(), "-s", serial, "exec-out", "screenrecord",
            f"--bit-rate={bitrate * 1000000}",
            "--output-format=h264", 
            "--size", f"{width}x{height}", "-"
        ]
        
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
             raise RuntimeError("ADB process terminated immediately (device disconnected?)")

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
             raise RuntimeError("screenrecord process failed to start on device (pidof verification failed)")
        # --------------------------------------------------------

        
        # 2. Start Player (FFmpeg/FFplay) reading from ADB stdout
        self.player_process = subprocess.Popen(
            player_cmd, stdin=self.adb_process.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )
        print(f"Player process started: {player_cmd}")
        
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

    def stop(self) -> None:
        if self.player_process:
            self.player_process.terminate()
            try:
                self.player_process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.player_process.kill()
            self.player_process = None

        if self.adb_process:
            self.adb_process.terminate()
            try:
                self.adb_process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.adb_process.kill()
            self.adb_process = None
            
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
