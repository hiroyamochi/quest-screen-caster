from .base import MirrorBackend
from .utils import get_scrcpy_path, check_process_alive
import subprocess

class ScrcpyBackend(MirrorBackend):
    def __init__(self):
        self.process = None

    def start(self, serial: str, options: dict) -> None:
        if self.is_running():
            self.stop()

        scrcpy_path = get_scrcpy_path()
        size = options.get('size', 1024)
        bitrate = options.get('bitrate', 20)
        window_title = options.get('window_title', serial)
        
        command = [scrcpy_path, '-s', serial, '-m', str(size)]
        command.append(f'--window-title={window_title}')
        
        if not options.get('video', True):
           command.append('--no-video')
        if not options.get('audio', False):
           command.append('--no-audio')
           
        command.append('-b' + str(bitrate) + 'M')
        
        audio_source = options.get('audio_source')
        if audio_source == 'mic':
            command.append('--audio-source=mic')
            
        # Device specific crops (logic moved from main.py)
        model = options.get('model')
        if model == "Quest 2":
            command.append("--crop=1450:1450:140:140")
        elif model == "Quest 3":
            command.append('--crop=2000:2000:2000:0')
            command.append('--rotation-offset=-20')
            command.append('--scale=132')
            command.append('--position-x-offset=-170')
            command.append('--position-y-offset=-125')
        elif model == "Quest Pro":
            command.append('--crop=2000:2000:1800:0')
            command.append('--rotation-offset=-20')
            command.append('--scale=125')
            command.append('--position-x-offset=-120')
            command.append('--position-y-offset=-160')
            
        self.process = subprocess.Popen(
            command, 
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )

    def stop(self) -> None:
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    def is_running(self) -> bool:
        return check_process_alive(self.process)
