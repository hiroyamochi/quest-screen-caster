from .base import MirrorBackend
from .utils import get_scrcpy_path, check_process_alive
import subprocess
import re

_angle_support_cache = {}


def _supports_angle(scrcpy_path: str) -> bool:
    """--angle was not available in the older bundled fork (2.3.1); passing it
    there is a hard "unknown option" crash. Detect support once per binary
    path (cheap: `--version` prints in well under a second) instead of
    assuming the official scrcpy 4.0+ semantics this module otherwise targets.
    """
    if scrcpy_path in _angle_support_cache:
        return _angle_support_cache[scrcpy_path]
    supported = False
    try:
        res = subprocess.run(
            [scrcpy_path, '--version'], capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )
        m = re.search(r"scrcpy (\d+)\.", res.stdout)
        if m:
            supported = int(m.group(1)) >= 4
    except Exception:
        pass
    _angle_support_cache[scrcpy_path] = supported
    return supported

# Per-model crop of the raw stereo fisheye passthrough frame, calibrated on
# real hardware against official scrcpy 4.0 (Genymobile build). scrcpy only
# exposes --crop (rectangle, in native/full-resolution pixels) and --angle
# (simple rotation) -- unlike ScreenRecordBackend's ffmpeg pipeline, it has no
# fisheye-flattening (v360) filter, so this only trims each eye to a centered
# square and levels the tilt; the barrel distortion itself is not corrected.
#
# Values are in NATIVE pixels for that model's full side-by-side texture, as
# reported by scrcpy's "Texture: WxH" log line, so they do NOT scale with
# --max-size. Format: (native_full_w, native_full_h, crop_size, offset_y, angle_deg).
# Left eye crop = crop_size:crop_size:0:offset_y : right eye adds native_full_w/2 to x.
MODEL_CROP = {
    "Quest 2/3S": (5934, 4320, 2966, 677, 0),
    "Quest 3": (4128, 2208, 2064, 72, 13),
    # Quest Pro has not been calibrated on real hardware (none available at the
    # time these values were tuned). Falling back to no crop (full SBS frame)
    # is safer than guessing wrong absolute pixel offsets for an unknown
    # native resolution -- an incorrect crop rectangle can clip into black.
}

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

        command = [scrcpy_path, '-s', serial, f'--max-size={size}']
        command.append(f'--window-title={window_title}')

        if not options.get('video', True):
           command.append('--no-video')
        if not options.get('audio', False):
           command.append('--no-audio')

        command.append(f'--video-bit-rate={bitrate}M')

        audio_source = options.get('audio_source')
        if audio_source == 'mic':
            command.append('--audio-source=mic')

        # Device-specific crop + tilt correction (see MODEL_CROP above).
        model = options.get('model')
        eye = options.get('eye', '両眼')
        calib = MODEL_CROP.get(model)
        if calib:
            full_w, full_h, crop_size, offset_y, angle = calib
            if eye == '左眼':
                command.append(f'--crop={crop_size}:{crop_size}:0:{offset_y}')
            elif eye == '右眼':
                command.append(f'--crop={crop_size}:{crop_size}:{full_w // 2}:{offset_y}')
            # eye == '両眼' -> no crop, show the raw SBS frame uncorrected
            if angle and _supports_angle(scrcpy_path):
                command.append(f'--angle={angle}')

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
