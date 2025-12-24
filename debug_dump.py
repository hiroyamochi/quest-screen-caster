from mirror_backend.utils import get_adb_path
import subprocess
import sys

def get_device():
    # Get first device
    adb = get_adb_path()
    res = subprocess.run([adb, "devices"], capture_output=True, text=True)
    lines = res.stdout.strip().split('\n')[1:]
    for line in lines:
        if "\tdevice" in line:
            return line.split('\t')[0]
    return None

def main():
    serial = get_device()
    if not serial:
        print("No device found")
        return

    print(f"Target: {serial}")
    adb = get_adb_path()
    
    # Same command as screenrecord.py
    # adb exec-out screenrecord --bit-rate=5000000 --output-format=h264 --size 1280x720 -
    cmd = [
        adb, "-s", serial, "exec-out", "screenrecord",
        "--bit-rate=5000000",
        "--output-format=h264", 
        "--size", "1280x720", "-"
    ]
    
    print(f"Running: {cmd}")
    
    # Capture first 2000 bytes
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        header = proc.stdout.read(2048)
        
        with open("stream_dump.bin", "wb") as f:
            f.write(header)
            
        print(f"Captured {len(header)} bytes. Saved to stream_dump.bin")
        print(f"Hex start: {header[:64].hex()}")

        # Check for ASCII text
        try:
            text = header[:100].decode('utf-8')
            print(f"Decoded start: {text}")
        except:
            print("Start is not valid utf-8 text (Good)")

        proc.kill()
    except Exception as e:
        print(e)

if __name__ == "__main__":
    main()
