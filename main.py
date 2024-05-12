import flet as ft
import subprocess
import time
import os
import sys
import configparser
import re
import atexit


def find_application_directory():
    if getattr(sys, 'frozen', False):
        # In built executable
        application_path = sys._MEIPASS
    else:
        # In dev environment
        application_path = os.path.dirname(__file__)
    
    return application_path

# Path to exe
scrcpy_path = os.path.join(find_application_directory(), "scrcpy-mod-by-vuisme", "scrcpy.exe")
adb_path = os.path.join(find_application_directory(), "scrcpy-mod-by-vuisme", "adb.exe")

print(f'app path: {find_application_directory()}')
print(f'scrcpy_path: {scrcpy_path}')
print(f'adb_path: {adb_path}')

# Load config
def load_config():
    config = configparser.ConfigParser()
    config.read(os.path.join(find_application_directory(), 'config.ini'))
    return config

# Load default bitrate from config
config = load_config()
default_bitrate = config.getint('scrcpy', 'bitrate', fallback=20)
default_size = config.getint('scrcpy', 'size', fallback=1024)


def get_connected_devices():
    devices_info = {}
    result = subprocess.run([adb_path, "devices", "-l"], capture_output=True, text=True)
    if result.returncode == 0:
        for match in re.finditer(r'(\S+)\s+device .+ model:(\S+)\s+', result.stdout):
            serial_number = match.group(1)
            device_name = match.group(2)
            devices_info[serial_number] = device_name
    return devices_info


def main(page: ft.Page):
    page.title = "Screen Caster for Quest"
    page.padding = 24
    page.window_min_height = 150
    page.window_min_width = 200
    page.window_height = 500
    page.window_width = 600
    page.theme_mode = ft.ThemeMode.SYSTEM

    casting_devices = {}

    def check_av(e):
        if noaudio.value == True:
            novideo.value = False
            novideo.update()
        elif novideo.value == True:
            noaudio.value = False
            noaudio.update()

    def on_device_change(e):
        nonlocal casting_devices

        device_name = str(device_dd.value)
        serial_number = get_serial_number(device_name)

        if serial_number in casting_devices:
            if casting_devices[serial_number]['process'] is not None or casting_devices[serial_number]['process'].poll() is None:
                connect_btn.icon = ft.icons.STOP
                connect_btn.text = "切断"
            else:
                connect_btn.icon = ft.icons.PLAY_ARROW
                connect_btn.text = "接続"
        else:
            connect_btn.icon = ft.icons.PLAY_ARROW
            connect_btn.text = "接続"

        if "Quest_2" in device_name:
            models.value = "Quest 2"
            models.update()
        elif "Quest_3" in device_name:
            models.value = "Quest 3"
            models.update()

        connect_btn.update()

    def load_device(e):
        connected_devices = get_connected_devices()

        print(f'connected_devices: {connected_devices}')

        options = [
            ft.dropdown.Option(text=f"{name} ({serial})") 
            for serial, name 
            in connected_devices.items()
            ]
        device_dd.options = options
        page.update()

    def disable_proximity_sensor(e):
        device_name = str(device_dd.value)
        serial = get_serial_number(device_name)
        subprocess.run([adb_path, "-s", serial, "shell", "am", "broadcast", "-a", "com.oculus.vrpowermanager.prox_close"])
  
    def enable_proximity_sensor(e):
        device_name = str(device_dd.value)
        serial = get_serial_number(device_name)
        subprocess.run([adb_path, "-s", serial, "shell", "am", "broadcast", "-a", "com.oculus.vrpowermanager.automation_disable"])

    def get_serial_number(device_name):
        # get serial number from device name menu
        serial_number_match = re.search(r'\((.*?)\)', device_name)
        if serial_number_match:
            serial_number = serial_number_match.group(1)
        else:
            print("シリアル番号が見つかりません")
            return None
        return serial_number

    def reset_adb(e):
        subprocess.run([adb_path, "kill-server"])
        subprocess.run([adb_path, "start-server"])
    
    reset_adb

    def on_app_exit():
        for device in casting_devices.values():
            if device['process'] is not None or device['process'].poll() is None:
                device['process'].terminate()

    atexit.register(on_app_exit)

    def start_scrcpy(e):
        nonlocal casting_devices

        no_video = novideo.value
        no_audio = noaudio.value
        bitrate_value = bitrate.value
        audio_s = audiosource.value

        device_model = models.value

        device_name = str(device_dd.value)
        serial_number = get_serial_number(device_name)
        
        print(f'serial: {serial_number}')

        command = [scrcpy_path, '-s', serial_number, '-m', '1024']
        command.append('--window-title=' + device_name)
        if serial_number != "None":
            if no_video == True:
                command.append('--no-video')
            if no_audio == True:
                command.append('--no-audio')
            if bitrate_value:
                command.append('-b' + str(bitrate_value) + 'M')
            if audio_s is None and audio_s == "内部音声":
                pass
            elif audio_s == "マイク":
                command.append('--audio-source=mic')
            if device_model == "Quest 2":
                command.append("--crop=1450:1450:140:140")
            elif device_model == "Quest 3":
                command.append('--crop=2064:2208:2064:100')
                command.append('--rotation-offset=-22')
                command.append('--scale=190')
                command.append('--position-x-offset=-520')
                command.append('--position-y-offset=-490')
            
            if serial_number in casting_devices: # Check if device is already casting
                if casting_devices[serial_number]['process'] is not None or casting_devices[serial_number]['process'].poll() is None:
                    print("プロセスを停止")
                    enable_proximity_sensor(None)
                    casting_devices[serial_number]['process'].terminate()
                    connect_btn.icon = ft.icons.PLAY_ARROW
                    connect_btn.text = "接続"
                    connect_btn.update()
                    del casting_devices[serial_number]
            else: # Start casting 
                print("プロセスを開始")
                process = subprocess.Popen(command, creationflags=subprocess.CREATE_NO_WINDOW)
                casting_devices[serial_number] = {'process': process, 'connect': True}
                connect_btn.icon = ft.icons.STOP
                connect_btn.text = "切断"
                connect_btn.update()
        else:
            connect_btn.text = "デバイスを選択してください"
            connect_btn.icon = ft.icons.ERROR
            connect_btn.update()
            time.sleep(2)
            connect_btn.text = "接続"
            connect_btn.icon = ft.icons.PLAY_ARROW
            connect_btn.update()
    
    title = ft.Text("Screen Caster for Quest", style=ft.TextThemeStyle.TITLE_MEDIUM,size=20)

    device_dd = ft.Dropdown(label="デバイス", expand=True, options=[], value=None, on_change=on_device_change)

    connect_btn = ft.FloatingActionButton(icon=ft.icons.PLAY_ARROW, text="接続", on_click=start_scrcpy)

    select_device = ft.Row([
        device_dd,
        ft.FilledButton("読み込み", icon=ft.icons.REFRESH, on_click=load_device)
    ], expand=0)

    models = ft.Dropdown(
        label="モデル", 
        options=[
          ft.dropdown.Option("Quest 2"),
          ft.dropdown.Option("Quest 3"),
          # ft.dropdown.Option("Quest Pro"),
          ft.dropdown.Option("Other (No Crop)")
        ],
        value="Quest 2"
        )
    
    select_model = ft.Row([models])

    novideo = ft.Switch(label="画面をキャストしない", value=False, expand=True, on_change=check_av)

    noaudio = ft.Switch(label="音声をキャストしない", value=True, expand=True, on_change=check_av)

    nosource = ft.Row([novideo,noaudio])

    bitrate = ft.TextField(label="映像ビットレート (推奨: 20Mbps)",suffix_text="Mbps", value=default_bitrate)

    audiosource = ft.Dropdown(label="オーディオソース", options=[ft.dropdown.Option("端末内部"),ft.dropdown.Option("マイク")])

    options = ft.Column([
        nosource,bitrate
    ], spacing=10)

    label_proximity = ft.Text("近接センサ (無効にすると装着時以外も画面が点灯する)", style=ft.TextThemeStyle.TITLE_SMALL, size=15)
    enable_proximity = ft.TextButton(text='有効にする', icon=ft.icons.REMOVE_RED_EYE, on_click=enable_proximity_sensor)
    disable_proximity = ft.TextButton(text='無効にする', icon=ft.icons.REMOVE_RED_EYE_OUTLINED, on_click=disable_proximity_sensor)

    reset_adb_button = ft.TextButton("ADBをリセット", on_click=reset_adb, icon=ft.icons.REFRESH, style=ft.ButtonStyle(color=ft.colors.RED))

    column_proximity = ft.Row([enable_proximity, disable_proximity], spacing=10)

    page.add(title, select_device, select_model, connect_btn, options, label_proximity, column_proximity, reset_adb_button)


if __name__ == "__main__":
    ft.app(main)

