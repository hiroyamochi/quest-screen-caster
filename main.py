import flet as ft
import subprocess
import time
import os
import sys
import configparser
import re
import atexit
from mirror_backend.scrcpy import ScrcpyBackend
from mirror_backend.screenrecord import ScreenRecordBackend
from mirror_backend.casting import CastingBackend, get_casting_exe
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
    try:
        result = subprocess.run([adb_path, "devices", "-l"], capture_output=True, text=True, timeout=10)
    except (subprocess.TimeoutExpired, Exception) as e:
        print(f"adb devices failed: {e}")
        return devices_info
    if result.returncode == 0:
        for match in re.finditer(r'(\S+)\s+device .+ model:(\S+)\s+', result.stdout):
            serial_number = match.group(1)
            device_name = match.group(2)
            devices_info[serial_number] = device_name
    return devices_info


def get_real_model_name(serial):
    try:
        # Get ro.product.model
        result = subprocess.run([adb_path, "-s", serial, "shell", "getprop", "ro.product.model"], capture_output=True, text=True, timeout=5)
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


def get_model_from_name(device_name_str):
    # device_name is "Quest_3 (2G0...)" -> returns "Quest_3"
    if " (" in device_name_str:
        return device_name_str.split(" (")[0]
    return "Default"


def main(page: ft.Page):
    page.title = "Screen Caster for Quest"
    page.padding = 24
    page.window_min_height = 150
    page.window_min_width = 200
    page.window_height = 600
    page.window_width = 450
    if hasattr(page, "window"):
        page.window.min_height = 150
        page.window.min_width = 200
        page.window.height = 600
        page.window.width = 600
    page.theme_mode = "system"
    page.scroll = ft.ScrollMode.AUTO

    casting_devices = {}
    app_exiting = False



    def on_device_change(e=None):
        nonlocal casting_devices

        device_name = str(device_dd.value)
        serial_number = get_serial_number(device_name)

        if serial_number in casting_devices:
            backend = casting_devices[serial_number]['backend']
            if backend.is_running():
                update_connect_btn(icon=ft.Icons.STOP, text="切断")
            else:
                update_connect_btn(icon=ft.Icons.PLAY_ARROW, text="接続")
        else:
            update_connect_btn(icon=ft.Icons.PLAY_ARROW, text="接続")

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


    def _set_proximity(serial, enabled):
        """Toggle the headset proximity sensor for a specific serial."""
        if not serial or serial == "None":
            return
        action = "com.oculus.vrpowermanager.prox_close" if not enabled else "com.oculus.vrpowermanager.automation_disable"
        try:
            subprocess.run([adb_path, "-s", serial, "shell", "am", "broadcast", "-a", action],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
        except Exception as e:
            print(f"proximity toggle failed for {serial}: {e}")

    def disable_proximity_sensor(e):
        serial = get_serial_number(str(device_dd.value))
        _set_proximity(serial, enabled=False)

    def enable_proximity_sensor(e):
        serial = get_serial_number(str(device_dd.value))
        _set_proximity(serial, enabled=True)

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
            result = subprocess.run([adb_path, "-s", serial_number, "shell", "ip", "route"], capture_output=True, text=True, timeout=5)
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

        try:
            subprocess.run([adb_path, 'kill-server'], timeout=10, check=False)
            subprocess.run([adb_path, 'start-server'], timeout=10, check=False)
        except Exception as e:
            print(f"adb reset failed: {e}")

        load_device()

    def on_app_exit():
        nonlocal app_exiting
        app_exiting = True
        print(f"[{time.strftime('%H:%M:%S')}] App closing: stopping all backends...")
        # Only terminate processes, do NOT update UI (reset_adb)
        for device in casting_devices.values():
            if device['backend'].is_running():
                device['backend'].stop()

    atexit.register(on_app_exit)
    
    def on_window_event(e):
        if e.data == "close":
            on_app_exit()
            page.window_destroy()

    page.window_prevent_close = True
    page.on_window_event = on_window_event

    # プロセスを監視する (Backend wrapper)
    def monitor_backend(serial_number, backend, connect_btn):
        # Poll until stopped
        print(f"[{time.strftime('%H:%M:%S')}] Monitor thread started for {serial_number}")
        while backend.is_running():
            time.sleep(1)
        
        print(f"[{time.strftime('%H:%M:%S')}] Monitor: backend stopped for {serial_number}")
        if serial_number in casting_devices:
            casting_devices.pop(serial_number, None)
            if not app_exiting:
                # Restore the proximity sensor on the device that actually
                # finished (not whatever device happens to be selected now).
                try:
                    _set_proximity(serial_number, enabled=True)
                except Exception:
                    pass
                # Only flip the connect button back if the finished device is
                # the one currently shown; otherwise we'd mislabel a device
                # that is still mirroring and allow a double-start.
                if get_serial_number(str(device_dd.value)) == serial_number:
                    print(f"[{time.strftime('%H:%M:%S')}] Monitor: updating button to 接続")
                    update_connect_btn(icon=ft.Icons.PLAY_ARROW, text="接続")

    def enable_wireless_connection(e=None):
        device_name = str(device_dd.value)
        serial_number = get_serial_number(device_name)
        ip_address = get_ip_address(serial_number)
        if not ip_address:
            print("IPアドレスが取得できないためワイヤレス接続を中止します")
            return
        try:
            subprocess.run([adb_path, "-s", serial_number, "tcpip", "5555"], timeout=10, check=False)
            subprocess.run([adb_path, "connect", ip_address], timeout=10, check=False)
        except Exception as e:
            print(f"ワイヤレス接続に失敗しました: {e}")
            return
        time.sleep(2)
        load_device()

    def toggle_mirroring(e):
        nonlocal casting_devices

        device_name = str(device_dd.value)
        serial_number = str(get_serial_number(device_name))
        
        if serial_number == "None":
            update_connect_btn(icon=ft.Icons.ERROR, text="デバイスを選択してください")
            time.sleep(2)
            update_connect_btn(icon=ft.Icons.PLAY_ARROW, text="接続")
            return

        # Check if already running
        if serial_number in casting_devices and casting_devices[serial_number]['backend'].is_running():
             print("プロセスを停止")
             try:
                 casting_devices[serial_number]['backend'].stop()
             except Exception:
                 pass
             casting_devices.pop(serial_number, None)
             
             update_connect_btn(icon=ft.Icons.PLAY_ARROW, text="接続")
             
             try:
                 enable_proximity_sensor(None)
             except Exception:
                 pass
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
            elif backend_type == 'Casting (MQDH)':
                backend = CastingBackend()
            else: # ScreenRecord
                backend = ScreenRecordBackend()
                mode = 'virtualcam' if vcam_switch.value else 'window'
                filter_section = f'Filters.{get_model_from_name(device_name)}' if f'Filters.{get_model_from_name(device_name)}' in config else 'Filters.Default'
                options.update({
                    'width': 1280,
                    'height': 720,
                    'eye': eye_dd.value.lower(),
                    'mode': mode,
                    'vcam_width': 1280,
                    'vcam_height': 720,
                    'vcam_fps': 30,
                    'rotation': int(config[filter_section]['rotation']),
                    'k1': float(config[filter_section]['k1']),
                    'k2': float(config[filter_section]['k2']),
                })
            
            backend.start(serial_number, options)
            casting_devices[serial_number] = {'backend': backend, 'connect': True}
            
            update_connect_btn(icon=ft.Icons.STOP, text="切断")

            # Start monitor via page.run_thread (NOT a raw threading.Thread):
            # Flet binds the page to a context var per run_thread call, and
            # page.update() only reaches the client when that context is set.
            # A raw thread's update() calls are silently dropped, which is why
            # the connect button never reverted after the window was closed.
            page.run_thread(monitor_backend, serial_number, backend, connect_btn)

        except Exception as ex:
            import traceback
            traceback.print_exc()
            print(f"Error starting mirror: {ex}")
            update_connect_btn(text="エラー")
    
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
        if hasattr(page, "open"):
            page.open(end_drawer)
        else:
            end_drawer.open = True
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
        
        if hasattr(page, "close"):
            page.close(end_drawer)
        else:
            end_drawer.open = False
        page.snack_bar = ft.SnackBar(ft.Text(f"{model} 用の設定を保存しました。反映するには再接続してください。"), open=True)
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
                ft.Button("保存して閉じる", icon=ft.Icons.SAVE, on_click=save_calibration)
            ]))
        ]
    )

    page.end_drawer = end_drawer

    title = ft.Text("Screen Caster for Quest", size=20, weight="bold")
    settings_btn = ft.IconButton(icon=ft.Icons.SETTINGS, tooltip="補正設定", on_click=open_calibration)

    device_dd = ft.Dropdown(label="デバイス", expand=True, options=[], value=None, on_select=on_device_change)


    backend_options = [
        ft.dropdown.Option("Scrcpy"),
        ft.dropdown.Option("ScreenRecord"),
    ]
    default_backend = "ScreenRecord"
    if get_casting_exe():
        backend_options.append(ft.dropdown.Option("Casting (MQDH)"))
        default_backend = "Casting (MQDH)"

    backend_dd = ft.Dropdown(
        label="バックエンド",
        options=backend_options,
        value=default_backend,
        width=180
    )

    eye_dd = ft.Dropdown(
        label="視点",
        options=[ft.dropdown.Option("両眼"), ft.dropdown.Option("左眼"), ft.dropdown.Option("右眼")],
        value="左眼",
        width=100
    )

    def on_backend_change(e=None):
        # 視点(eye)は ScreenRecord バックエンドでしか使われない。
        # Scrcpy はモデル別クロップ、Casting(MQDH) はヘッドセット側が
        # 出力を決めるため選んでも無意味なので、その場合は隠す。
        eye_dd.visible = (backend_dd.value == "ScreenRecord")
        try:
            eye_dd.update()
        except Exception:
            pass

    backend_dd.on_change = on_backend_change
    # 起動時の初期状態にも反映（既定バックエンドが ScreenRecord 以外なら非表示）
    eye_dd.visible = (default_backend == "ScreenRecord")

    # OBSモード・UDPポートは非表示（当面サポート外）

    connect_btn = ft.Button(
        "接続",
        icon=ft.Icons.PLAY_ARROW,
        on_click=toggle_mirroring,
        style=ft.ButtonStyle(
            bgcolor=ft.Colors.PRIMARY,
            color=ft.Colors.ON_PRIMARY,
            padding=20,
            text_style=ft.TextStyle(size=16, weight=ft.FontWeight.BOLD),
        ),
        height=48,
    )
    page.bottom_appbar = ft.BottomAppBar(
        padding=10,
        content=ft.Row(
            [connect_btn],
            alignment=ft.MainAxisAlignment.END,
        ),
    )

    def update_connect_btn(icon=None, text=None):
        if icon is not None:
            connect_btn.icon = icon
        if text is not None:
            connect_btn.content = text
        try:
            page.update()
        except Exception as ex:
            print(f"[{time.strftime('%H:%M:%S')}] update_connect_btn error: {ex}")

    select_device = ft.Row([
        device_dd,
        ft.Button("読み込み", icon=ft.Icons.REFRESH, on_click=load_device)
    ], expand=0)

    models = ft.Dropdown(
        label="モデル", 
        options=[
          ft.dropdown.Option("Quest 2/3S"),
          ft.dropdown.Option("Quest 3"),
          ft.dropdown.Option("Quest Pro"),
          ft.dropdown.Option("その他 (クロップなし)")
        ],
                value="Quest 2/3S"
        )

    # UI設定
    select_model = ft.Row([models, backend_dd])
    advanced_options = ft.Row([eye_dd])

    is_cast_video = ft.Switch(label="画面をキャスト", value=True, expand=True)

    is_cast_audio = ft.Switch(label="音声をキャスト", value=False, expand=True)

    vcam_switch = ft.Switch(label="仮想カメラ出力 (OBS)", value=False, expand=True)

    enable_wireless_connection_btn = ft.TextButton("ワイヤレス接続を有効にする", on_click=enable_wireless_connection, icon=ft.Icons.WIFI)

    bitrate = ft.TextField(label="ビットレート", suffix="Mbps", value=default_bitrate, width=250)

    mirror_size = ft.TextField(label="解像度", suffix="px", value=default_size, width=250)

    audiosource = ft.Dropdown(label="オーディオソース", options=[ft.dropdown.Option("端末内部"), ft.dropdown.Option("マイク")])

    label_proximity = ft.Text("近接センサ (無効にすると装着時以外も画面が点灯する)", size=15, weight="bold")
    enable_proximity = ft.TextButton('有効にする', icon=ft.Icons.REMOVE_RED_EYE, on_click=enable_proximity_sensor)
    disable_proximity = ft.TextButton('無効にする', icon=ft.Icons.REMOVE_RED_EYE_OUTLINED, on_click=disable_proximity_sensor)

    reset_adb_button = ft.TextButton("ADBをリセット", on_click=reset_adb, icon=ft.Icons.REFRESH, style=ft.ButtonStyle(color="red"))

    page.add(
        ft.Row([title, settings_btn], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        select_device,
        select_model,
        advanced_options,
        ft.Row([is_cast_video, is_cast_audio, vcam_switch]),
        ft.Row([enable_wireless_connection_btn]),
        ft.Row([bitrate, mirror_size]),
        label_proximity,
        ft.Row([enable_proximity, disable_proximity]),
        reset_adb_button,
    )

    # 起動時に接続されているデバイスを読み込む
    load_device()






if __name__ == "__main__":
    ft.run(main)

