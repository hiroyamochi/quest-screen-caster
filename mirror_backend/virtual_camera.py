"""
Virtual camera output using pyvirtualcam.
Reads raw video frames from ffmpeg and pushes them to a virtual camera
that OBS (or any app) can pick up as a video capture device.

Requires: pyvirtualcam, numpy
On Windows, pyvirtualcam uses OBS Virtual Camera (install OBS to get the driver).
"""

import subprocess
import threading
import time
import numpy as np

try:
    import pyvirtualcam
    PYVIRTUALCAM_AVAILABLE = True
except ImportError:
    PYVIRTUALCAM_AVAILABLE = False


class VirtualCameraOutput:
    """Wraps a virtual camera that receives frames from an ffmpeg pipe."""

    def __init__(self, width: int, height: int, fps: int = 30, device_label: str = "", vf_str: str = ""):
        if not PYVIRTUALCAM_AVAILABLE:
            raise ImportError(
                "pyvirtualcam is not installed. Run: uv pip install pyvirtualcam"
            )
        self.width = width
        self.height = height
        self.fps = fps
        self.device_label = device_label
        self.vf_str = vf_str
        self._cam = None
        self._running = False
        self._thread = None
        self._ffmpeg_process = None

    def start_from_h264_pipe(self, input_pipe) -> None:
        """
        Start reading H.264 from input_pipe (e.g., adb stdout),
        decode with ffmpeg, and push frames to virtual camera.
        """
        frame_size = self.width * self.height * 3  # RGB24

        ffmpeg_cmd = [
            "ffmpeg",
            "-f", "h264",
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-i", "pipe:0",
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
        ]

        if self.vf_str:
            final_vf = f"{self.vf_str},scale={self.width}:{self.height}"
        else:
            final_vf = f"scale={self.width}:{self.height}"
            
        ffmpeg_cmd.extend(["-vf", final_vf])
        ffmpeg_cmd.extend([
            "-r", str(self.fps),
            "-v", "error",
            "pipe:1",
        ])

        self._ffmpeg_process = subprocess.Popen(
            ffmpeg_cmd,
            stdin=input_pipe,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
        )

        self._running = True
        self._thread = threading.Thread(target=self._feed_loop, args=(frame_size,), daemon=True)
        self._thread.start()

        # Log ffmpeg errors
        def _log_err():
            try:
                for line in self._ffmpeg_process.stderr:
                    text = line.decode("utf-8", errors="replace").strip()
                    if text:
                        print(f"[VCam/ffmpeg] {text}")
            except Exception:
                pass
        threading.Thread(target=_log_err, daemon=True).start()

    def _feed_loop(self, frame_size: int):
        try:
            self._cam = pyvirtualcam.Camera(
                width=self.width,
                height=self.height,
                fps=self.fps,
                fmt=pyvirtualcam.PixelFormat.RGB,
            )
            print(f"[VCam] Virtual camera started: {self._cam.device} ({self.width}x{self.height}@{self.fps}fps)")

            while self._running:
                data = b""
                while len(data) < frame_size and self._running:
                    chunk = self._ffmpeg_process.stdout.read(frame_size - len(data))
                    if not chunk:
                        break
                    data += chunk
                
                if len(data) < frame_size:
                    if not self._running:
                        break
                    if self._ffmpeg_process.poll() is not None:
                        break
                    time.sleep(0.01)
                    continue

                frame = np.frombuffer(data, dtype=np.uint8).reshape(self.height, self.width, 3)
                self._cam.send(frame)
                self._cam.sleep_until_next_frame()

        except Exception as e:
            print(f"[VCam] Error in feed loop: {e}")
        finally:
            if self._cam:
                self._cam.close()
                self._cam = None

    def stop(self):
        self._running = False
        if self._ffmpeg_process:
            try:
                self._ffmpeg_process.terminate()
                self._ffmpeg_process.wait(timeout=2)
            except Exception:
                try:
                    self._ffmpeg_process.kill()
                except Exception:
                    pass
            self._ffmpeg_process = None
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    @property
    def is_active(self) -> bool:
        return self._running and self._cam is not None
