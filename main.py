import flet as ft
import subprocess
import time
import os
import sys
import configparser
import re
import atexit
import threading


def find_application_directory():
    if getattr(sys, 'frozen', False):
        # In built executable
        application_path = sys._MEIPASS
    else:
        # In dev environment
        application_path = os.path.dirname(__file__)
    
    return application_path

# Path to exe
scrcpy_path = os.path.join(find_application_directory(), "scrcpy", "scrcpy.exe")
adb_path = os.path.join(find_application_directory(), "scrcpy", "adb.exe")

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
        if is_cast_audio.value == True:
            is_cast_video.update()
        elif is_cast_video.value == True:
            is_cast_audio.update()

    def on_device_change(e=None):
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
        elif "Quest_Pro" in device_name:
            models.value = "Quest Pro"
            models.update()
        else:
            models.value = "Other (No Crop)"
            models.update()

        connect_btn.update()

    def load_device(e=None):
        connected_devices = get_connected_devices()

        print(f'connected_devices: {connected_devices}')

        options = [
            ft.dropdown.Option(text=f"{name} ({serial})") 
            for serial, name 
            in connected_devices.items()
            ]
        device_dd.options = options

        if len(device_dd.options) > 0:
            device_dd.value = device_dd.options[0].text
            on_device_change()
            page.update()

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

    def get_ip_address(serial_number):
        try:
            result = subprocess.run([adb_path, "-s", serial_number, "shell", "ip", "route"], capture_output=True, text=True)
            if result.returncode == 0:
                output = result.stdout
                ip_match = re.search(r'src (\d+\.\d+\.\d+\.\d+)', output)
                if ip_match:
                    return ip_match.group(1)
                else:
                    print("IPアドレスが見つかりません")
                    return None
            else:
                print("adbコマンドの実行に失敗しました")
                return None
        except Exception as e:
            print(f"エラーが発生しました: {e}")
            return None

    def reset_adb(e=None):
        device_dd.options = [ft.dropdown.Option(text = '読込中……')]
        device_dd.value = device_dd.options[0].text
        page.update()

        subprocess.run([adb_path, 'kill-server'])
        subprocess.run([adb_path, 'start-server'])

        load_device()

    def stop_all_casts():
        for device in casting_devices.values():
            if device['process'] is not None or device['process'].poll() is None:
                device['process'].terminate()
                reset_adb()

    def on_app_exit():
        for device in casting_devices.values():
            if device['process'] is not None or device['process'].poll() is None:
                device['process'].terminate()
                reset_adb()

    atexit.register(on_app_exit)

    # scrcpyのプロセスを監視する
    def monitor_process(serial_number, process, connect_btn):
        process.wait()  # プロセスが終了するのを待つ
        if serial_number in casting_devices:
            enable_proximity_sensor(None)
            connect_btn.icon = ft.icons.PLAY_ARROW
            connect_btn.text = "接続"
            connect_btn.update()
            del casting_devices[serial_number]

    def enable_wireless_connection(e=None):
        device_name = str(device_dd.value)
        serial_number = get_serial_number(device_name)
        ip_address = get_ip_address(serial_number)
        command1 = [adb_path, "-s", serial_number, "tcpip", "5555"]
        command2 = [adb_path, "connect", ip_address]
        subprocess.run(command1)
        subprocess.run(command2)
        time.sleep(2)
        load_device()

    def start_scrcpy(e):
        nonlocal casting_devices

        audio_s = audiosource.value

        device_model = models.value

        device_name = str(device_dd.value)
        serial_number = get_serial_number(device_name)
        
        print(f'serial: {serial_number}')

        command = [scrcpy_path, '-s', serial_number, '-m', '1024']

        if serial_number != "None":
            if is_cast_video.value == False:
                command.append('--no-video')
            if is_cast_audio.value == False:
                command.append('--no-audio')
            if bitrate.value:
                command.append('-b' + str(bitrate.value) + 'M')
            if audio_s is None and audio_s == "内部音声":
                pass
            elif audio_s == "マイク":
                command.append('--audio-source=mic')
            if device_model == "Quest 2":
                command.append("--crop=1450:1450:140:140")
            elif device_model == "Quest 3":
                command.append('--crop=2000:2000:2000:0')
                command.append('--rotation-offset=-20')
                command.append('--scale=132')
                command.append('--position-x-offset=-170')
                command.append('--position-y-offset=-125')
            elif device_model == "Quest Pro":
                command.append('--crop=2000:2000:1800:0')
                command.append('--rotation-offset=-20')
                command.append('--scale=125')
                command.append('--position-x-offset=-120')
                command.append('--position-y-offset=-160')

            print(f'command: {command}')
            
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
                # プロセスの監視を開始
                monitor_thread = threading.Thread(target=monitor_process, args=(serial_number, process, connect_btn))
                monitor_thread.start()
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
          ft.dropdown.Option("Quest Pro"),
          ft.dropdown.Option("Other (No Crop)")
        ],
        value="Quest 2"
        )

    # UI設定
    select_model = ft.Row([models])

    is_cast_video = ft.Switch(label="画面をキャスト", value=True, expand=True, on_change=check_av)

    is_cast_audio = ft.Switch(label="音声をキャスト", value=False, expand=True, on_change=check_av)

    # is_tcpip_mode = ft.Switch(label="ワイヤレス接続", value=False, expand=True)

    row1 = ft.Row([is_cast_video,is_cast_audio], spacing=10)

    bitrate = ft.TextField(label="映像ビットレート (推奨: 20Mbps)",suffix_text="Mbps", value=default_bitrate)

    enable_wireless_connection_btn = ft.TextButton("ワイヤレス接続を有効にする", on_click=enable_wireless_connection, icon=ft.icons.WIFI)

    row2 = ft.Row([bitrate, enable_wireless_connection_btn], spacing=10)

    audiosource = ft.Dropdown(label="オーディオソース", options=[ft.dropdown.Option("端末内部"),ft.dropdown.Option("マイク")])

    options = ft.Column([
        row1, row2
    ], spacing=10)

    label_proximity = ft.Text("近接センサ (無効にすると装着時以外も画面が点灯する)", style=ft.TextThemeStyle.TITLE_SMALL, size=15)
    enable_proximity = ft.TextButton(text='有効にする', icon=ft.icons.REMOVE_RED_EYE, on_click=enable_proximity_sensor)
    disable_proximity = ft.TextButton(text='無効にする', icon=ft.icons.REMOVE_RED_EYE_OUTLINED, on_click=disable_proximity_sensor)

    reset_adb_button = ft.TextButton("ADBをリセット", on_click=reset_adb, icon=ft.icons.REFRESH, style=ft.ButtonStyle(color=ft.colors.RED))

    column_proximity = ft.Row([enable_proximity, disable_proximity], spacing=10)

    page.add(title, select_device, select_model, connect_btn, options, label_proximity, column_proximity, reset_adb_button)

    # 起動時に接続されているデバイスを読み込む
    load_device()



    # アプリケーション終了時にすべてのキャストを停止する
    page.on_close = stop_all_casts






if __name__ == "__main__":
    ft.app(target=main)

