import flet as ft
import subprocess
import time
import os
import sys
import configparser
import re
import atexit
import threading
from mirror_backend.scrcpy import ScrcpyBackend
from mirror_backend.screenrecord import ScreenRecordBackend
from mirror_backend.utils import get_adb_path, get_scrcpy_path, get_base_path



# Path to exe
scrcpy_path = get_scrcpy_path()
adb_path = get_adb_path()


# Load config
def load_config():
    config = configparser.ConfigParser()
    config.read(os.path.join(get_base_path(), 'config.ini'))
    return config

# Load default bitrate from config
config = load_config()
default_bitrate = config.get('scrcpy', 'bitrate', fallback=20)
default_size = config.get('scrcpy', 'size', fallback=1024)


def get_connected_devices():
    devices_info = {}
    result = subprocess.run([adb_path, "devices", "-l"], capture_output=True, text=True)
    if result.returncode == 0:
        for match in re.finditer(r'(\S+)\s+device .+ model:(\S+)\s+', result.stdout):
            serial_number = match.group(1)
            device_name = match.group(2)
            devices_info[serial_number] = device_name
    return devices_info


def get_real_model_name(serial):
    try:
        # Get ro.product.model
        result = subprocess.run([adb_path, "-s", serial, "shell", "getprop", "ro.product.model"], capture_output=True, text=True)
        if result.returncode == 0:
            model = result.stdout.strip()
            # Map code names or explicit names
            if model in ["Quest 3", "Eureka"]:
                return "Quest 3"
            elif model in ["Quest 2", "Hollywood", "Quest 3S"]:
                return "Quest 2/3S"
            elif model in ["Quest Pro", "Seacliff"]:
                return "Quest Pro"
            return model
    except:
        pass
    return "Unknown"


def main(page: ft.Page):
    page.title = "Screen Caster for Quest"
    page.padding = 24
    page.window_min_height = 150
    page.window_min_width = 200
    page.window_height = 500
    page.window_width = 600
    page.theme_mode = "system"

    casting_devices = {}
    app_exiting = False



    def on_device_change(e=None):
        nonlocal casting_devices

        device_name = str(device_dd.value)
        serial_number = get_serial_number(device_name)

        if serial_number in casting_devices:
            backend = casting_devices[serial_number]['backend']
            if backend.is_running():
                connect_btn.icon = "stop"
                connect_btn.text = "切断"
            else:
                connect_btn.icon = "play_arrow"
                connect_btn.text = "接続"
        else:
            connect_btn.icon = "play_arrow"
            connect_btn.text = "接続"

        if "Quest 2" in device_name: # Fallback if already in name
            models.value = "Quest 2/3S"
        elif "Quest 3" in device_name and "Quest 3S" not in device_name:
            models.value = "Quest 3"
        elif "Quest Pro" in device_name:
            models.value = "Quest Pro"
        
        # Try to get real model
        real_model = get_real_model_name(serial_number)
        if real_model == "Quest 3":
            models.value = "Quest 3"
        elif real_model == "Quest 2/3S":
            models.value = "Quest 2/3S"
        elif real_model == "Quest Pro":
            models.value = "Quest Pro"
            
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
            if device['backend'].is_running():
                device['backend'].stop()
        reset_adb()

    def on_app_exit():
        nonlocal app_exiting
        app_exiting = True
        print(f"[{time.strftime('%H:%M:%S')}] App closing: stopping all backends...")
        # Only terminate processes, do NOT update UI (reset_adb)
        for device in casting_devices.values():
            if device['backend'].is_running():
                device['backend'].stop()

    atexit.register(on_app_exit)
    
    # ウィンドウクローズイベントをハンドル
    def on_window_event(e):
        if e.data == "close":
            print(f"[{time.strftime('%H:%M:%S')}] Window close event detected")
            on_app_exit()
            page.window_destroy()

    page.on_window_event = on_window_event
    page.window_prevent_close = True

    # プロセスを監視する (Backend wrapper)
    def monitor_backend(serial_number, backend, connect_btn):
        # Poll until stopped
        while backend.is_running():
            time.sleep(1)
            
        if serial_number in casting_devices:
            if not app_exiting:
                try:
                    enable_proximity_sensor(None)
                    connect_btn.icon = "play_arrow"
                    connect_btn.text = "接続"
                    connect_btn.update()
                except Exception:
                    pass
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

    def toggle_mirroring(e):
        nonlocal casting_devices

        device_name = str(device_dd.value)
        serial_number = str(get_serial_number(device_name))
        
        if serial_number == "None":
            connect_btn.text = "デバイスを選択してください"
            connect_btn.icon = "error"
            connect_btn.update()
            time.sleep(2)
            connect_btn.text = "接続"
            connect_btn.icon = "play_arrow"
            connect_btn.update()
            return

        # Check if already running
        if serial_number in casting_devices and casting_devices[serial_number]['backend'].is_running():
             print("プロセスを停止")
             enable_proximity_sensor(None)
             casting_devices[serial_number]['backend'].stop()
             del casting_devices[serial_number]
             
             connect_btn.icon = "play_arrow"
             connect_btn.text = "接続"
             connect_btn.update()
             return

        # Start new mirroring
        print(f'Starting mirror for {serial_number}')
        
        backend_type = backend_dd.value
        options = {
            'bitrate': int(bitrate.value) if bitrate.value else 20,
            'size': int(mirror_size.value) if mirror_size.value else 1024,
            'window_title': device_name,
            'video': is_cast_video.value,
            'audio': is_cast_audio.value,
            'audio_source': 'mic' if audiosource.value == "マイク" else None,
            'model': models.value
        }
        
        try:
            if backend_type == 'Scrcpy':
                backend = ScrcpyBackend()
            else: # ScreenRecord
                backend = ScreenRecordBackend()
                options.update({
                    'width': 1280, # TODO: Make configurable or derive
                    'height': 720,
                    'eye': eye_dd.value.lower(),
                    'mode': 'window',
                    # Add filter params from config
                    'rotation': int(config[f'Filters.{get_model_from_name(device_name)}' if f'Filters.{get_model_from_name(device_name)}' in config else 'Filters.Default']['rotation']),
                    'k1': float(config[f'Filters.{get_model_from_name(device_name)}' if f'Filters.{get_model_from_name(device_name)}' in config else 'Filters.Default']['k1']),
                    'k2': float(config[f'Filters.{get_model_from_name(device_name)}' if f'Filters.{get_model_from_name(device_name)}' in config else 'Filters.Default']['k2']),
                })
            
            backend.start(serial_number, options)
            casting_devices[serial_number] = {'backend': backend, 'connect': True}
            
            connect_btn.icon = "stop"
            connect_btn.text = "切断"
            connect_btn.update()
            
            # Start monitor
            monitor_thread = threading.Thread(target=monitor_backend, args=(serial_number, backend, connect_btn))
            monitor_thread.start()
            
        except Exception as ex:
            import traceback
            traceback.print_exc()
            print(f"Error starting mirror: {ex}")
            connect_btn.text = "エラー"
            connect_btn.update()
    
    title = ft.Text("Screen Caster for Quest", size=20, weight="bold")

    device_dd = ft.Dropdown(label="デバイス", expand=True, options=[], value=None, on_change=on_device_change)


    backend_dd = ft.Dropdown(
        label="バックエンド",
        options=[ft.dropdown.Option("Scrcpy"), ft.dropdown.Option("ScreenRecord")],
        value="ScreenRecord",
        width=150
    )

    eye_dd = ft.Dropdown(
        label="視点",
        options=[ft.dropdown.Option("両眼"), ft.dropdown.Option("左眼"), ft.dropdown.Option("右眼")],
        value="左眼",
        width=100
    )

    # OBSモード・UDPポートは非表示（当面サポート外）

    connect_btn = ft.FloatingActionButton(icon="play_arrow", text="接続", on_click=toggle_mirroring)

    select_device = ft.Row([
        device_dd,
        ft.FilledButton("読み込み", icon="refresh", on_click=load_device)
    ], expand=0)

    models = ft.Dropdown(
        label="モデル", 
        options=[
          ft.dropdown.Option("Quest 2/3S"),
          ft.dropdown.Option("Quest 3"),
          ft.dropdown.Option("Quest Pro"),
          ft.dropdown.Option("その他 (クロップなし)")
        ],
        value="Quest 2"
        )

    # UI設定
    select_model = ft.Row([models, backend_dd])
    advanced_options = ft.Row([eye_dd])

    is_cast_video = ft.Switch(label="画面をキャスト", value=True, expand=True)

    is_cast_audio = ft.Switch(label="音声をキャスト", value=False, expand=True)

    enable_wireless_connection_btn = ft.TextButton("ワイヤレス接続を有効にする", on_click=enable_wireless_connection, icon="wifi")

    bitrate = ft.TextField(label="ビットレート", suffix_text="Mbps", value=default_bitrate, width=page.window_width / 2 - 50)

    mirror_size = ft.TextField(label="解像度", suffix_text='px', value=default_size, width=page.window_width / 2 - 50)

    audiosource = ft.Dropdown(label="オーディオソース", options=[ft.dropdown.Option("端末内部"), ft.dropdown.Option("マイク")])

    label_proximity = ft.Text("近接センサ (無効にすると装着時以外も画面が点灯する)", size=15, weight="bold")
    enable_proximity = ft.TextButton(text='有効にする', icon="remove_red_eye", on_click=enable_proximity_sensor)
    disable_proximity = ft.TextButton(text='無効にする', icon="remove_red_eye_outlined", on_click=disable_proximity_sensor)

    reset_adb_button = ft.TextButton("ADBをリセット", on_click=reset_adb, icon="refresh", style=ft.ButtonStyle(color="red"))

    page.add(
        title, 
        select_device, 
        select_model, 
        advanced_options,
        connect_btn, 
        ft.Row([is_cast_video, is_cast_audio, enable_wireless_connection_btn]), 
        ft.Row([bitrate, mirror_size]), 
        label_proximity, 
        ft.Row([enable_proximity, disable_proximity]), 
        reset_adb_button
    )

    # 起動時に接続されているデバイスを読み込む
    load_device()



    # Helper to get model from "Model (Serial)" string
    def get_model_from_name(device_name_str):
        # device_name is "Quest_3 (2G0...)" -> returns "Quest_3"
        if " (" in device_name_str:
            return device_name_str.split(" (")[0]
        return "Default"

    # Calibration UI
    def open_calibration(e):
        device_name = str(device_dd.value)
        model = get_model_from_name(device_name)
        section = f'Filters.{model}'
        if section not in config:
            section = 'Filters.Default'
            
        # Load current values
        try:
            rot_slider.value = int(config[section]['rotation'])
            k1_slider.value = float(config[section]['k1'])
            k2_slider.value = float(config[section]['k2'])
        except:
            pass
        page.open(end_drawer)
        page.update()

    def save_calibration(e):
        device_name = str(device_dd.value)
        model = get_model_from_name(device_name)
        section = f'Filters.{model}'
        
        if section not in config:
            config[section] = {}
            
        config[section]['rotation'] = str(int(rot_slider.value))
        config[section]['k1'] = str(k1_slider.value)
        config[section]['k2'] = str(k2_slider.value)
        
        with open('config.ini', 'w') as configfile:
            config.write(configfile)
        
        page.close(end_drawer)
        page.snack_bar = ft.SnackBar(ft.Text(f"{model} 用の設定を保存しました。反映するには再接続してください。"))
        page.snack_bar.open = True
        page.update()

    rot_slider = ft.Slider(min=-180, max=180, divisions=360, label="{value} deg")
    k1_slider = ft.Slider(min=-0.5, max=0.5, divisions=100, label="k1: {value}")
    k2_slider = ft.Slider(min=-0.5, max=0.5, divisions=100, label="k2: {value}")
    
    end_drawer = ft.NavigationDrawer(
        controls=[
            ft.Container(padding=12, content=ft.Column([
                ft.Text("映像補正 (要再接続)", size=20, weight="bold"),
                ft.Divider(),
                ft.Text("回転 (Rotation)"),
                rot_slider,
                ft.Text("レンズ補正 k1 (Barrel/Pincushion)"),
                k1_slider,
                ft.Text("レンズ補正 k2 (Edge)"),
                k2_slider,
                ft.ElevatedButton("保存して閉じる", icon="save", on_click=save_calibration)
            ]))
        ]
    )

    # Header with calibration button
    page.add(
        ft.Row([
            ft.Text("Quest Screen Caster", size=24, weight="bold"),
            ft.IconButton(icon="settings", on_click=open_calibration, tooltip="補正設定")
        ], alignment="spaceBetween")
    )






if __name__ == "__main__":
    ft.app(target=main)

