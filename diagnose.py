import subprocess
import time
from mirror_backend.utils import get_adb_path

def run_adb(args, serial=None):
    cmd = [get_adb_path()]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(args)
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.stdout.strip()

def get_serial():
    lines = run_adb(["devices"]).split('\n')[1:]
    for line in lines:
        if "\tdevice" in line:
            return line.split('\t')[0]
    return None

def main():
    serial = get_serial()
    if not serial:
        print("No device")
        return
    print(f"Device: {serial}")
    
    # Check Power State
    print("--- Power State ---")
    dumpsys = run_adb(["shell", "dumpsys", "power"], serial)
    for line in dumpsys.split('\n'):
        if "mWakefulness=" in line:
            print(line.strip())
            
    # Try Wakeup
    print("--- Sending WAKEUP ---")
    run_adb(["shell", "input", "keyevent", "WAKEUP"], serial)
    time.sleep(1)
    
    dumpsys = run_adb(["shell", "dumpsys", "power"], serial)
    for line in dumpsys.split('\n'):
        if "mWakefulness=" in line:
            print(f"After WAKEUP: {line.strip()}")
            
    # Try Screenrecord
    print("--- Running screenrecord (1s) ---")
    cmd = [get_adb_path(), "-s", serial, "exec-out", "screenrecord", "--output-format=h264", "--size", "1280x720", "-"]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(1.0)
        if proc.poll() is not None:
            print(f"Process exited early!")
            print(f"Stderr: {proc.stderr.read().decode()}")
        else:
            print("Process is running...")
            proc.kill()
            header = proc.stdout.read(100)
            print(f"Header: {header}")
    except Exception as e:
        print(e)
        
if __name__ == "__main__":
    main()
