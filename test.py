import flet as ft
import subprocess
import time
import os
import sys
import configparser

def find_application_directory():
    if getattr(sys, 'frozen', False):
        # 実行ファイルの場合
        application_path = os.path.dirname(sys.executable)
    else:
        # 開発環境の場合
        application_path = os.path.dirname(os.path.abspath(__file__))
    
    print(f'app path: {application_path}')
    return application_path

# scrcpyのパス
scrcpy_path = os.path.join(find_application_directory(), "scrcpy-mod-by-vuisme", "scrcpy.exe")
adb_path = os.path.join(find_application_directory(), "scrcpy-mod-by-vuisme", "adb.exe")

# 設定の読み込み
def load_config():
    config = configparser.ConfigParser()
    config.read(os.path.join(find_application_directory(), 'config.ini'))
    return config

# 設定からデフォルトビットレートとサイズを読み込む
config = load_config()
default_bitrate = config.getint('scrcpy', 'bitrate', fallback=20)
default_size = config.getint('scrcpy', 'size', fallback=1024)

def get_connected_devices():
    # 'adb devices'コマンドを実行して接続されているデバイスの一覧を取得
    result = subprocess.run([adb_path, 'devices'], capture_output=True, text=True)
    
    # 出力からデバイスのリストを作成
    output_lines = result.stdout.splitlines()[1:]
    devices = [{'device_id': line.split('\t')[0], 'status': 'connected' if 'device' in line else 'disconnected'} for line in output_lines if len(line.split('\t')) > 1]
    return devices

def main(page: ft.Page):
    page.title = "Scrcpy_GUI"
    page.padding = 24
    page.theme_mode = ft.ThemeMode.SYSTEM
    devices = []
    device_serials = {}
    process_dict = {}
    connect = False

    def load_device(e):
        connected_devices = get_connected_devices()
        options = [ft.dropdown.Option(f"{device['device_id']} ({device['status']})") for device in connected_devices]
        device_dd.options = options
        page.update()

    def start_scrcpy(e):
        device = str(device_dd.value.split(' ')[0])  # 'device_id (status)'からdevice_idを抽出
        status = device_dd.value.split(' ')[1][1:-1]  # '(status)'からstatusを抽出

        if status == 'disconnected':
            connect_btn.text = "切断"
            connect_btn.icon = ft.icons.STOP
            connect_btn.update()
            # ここにデバイス接続のロジックを追加
        else:
            connect_btn.text = "接続"
            connect_btn.icon = ft.icons.PLAY_ARROW
            connect_btn.update()
            # ここにデバイス切断のロジックを追加

    title = ft.Text("Scrcpy_GUI", style=ft.TextThemeStyle.TITLE_MEDIUM, size=32)
    device_dd = ft.Dropdown(label="デバイス", expand=True, options=[])
    connect_btn = ft.FloatingActionButton(icon=ft.icons.PLAY_ARROW, text="接続", on_click=start_scrcpy)
    select_device = ft.Row([
        device_dd,
        ft.FilledButton("読み込み", icon=ft.icons.REFRESH, on_click=load_device)
    ], expand=0)

    page.add(title, select_device, connect_btn)

if __name__ == "__main__":
    ft.app(main)


"""""""

import flet as ft
import subprocess
import time
import os
import sys
import configparser

def find_application_directory():
    if getattr(sys, 'frozen', False):
        # In built executable
        application_path = os.path.dirname(sys.executable)
    else:
        # In dev environment
        application_path = os.path.dirname(os.path.abspath(__file__))
    
    print(f'app path: {application_path}')
    return application_path

# Path to exe
scrcpy_path = os.path.join(find_application_directory(), "scrcpy-mod-by-vuisme", "scrcpy.exe")
adb_path = os.path.join(find_application_directory(), "scrcpy-mod-by-vuisme", "adb.exe")

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
    # adb devicesコマンドを実行して接続されているデバイスの一覧を取得
    result = subprocess.run([adb_path, 'devices'], capture_output=True, text=True)
    
    # 出力からデバイスのリストを作成
    output_lines = result.stdout.splitlines()[1:]
    devices = [{'device_id': line.split('\t')[0]} for line in output_lines if len(line.split('\t')) == 2]
    return devices

def main(page: ft.Page):
    page.title = "Scrcpy_GUI"
    page.padding = 24
    page.theme_mode = ft.ThemeMode.SYSTEM
    devices = []
    device_serials = {}
    process = None
    connect = False

    def check_av(e):
        if noaudio.value == True:
            novideo.value = False
            novideo.update()
        elif novideo.value == True:
            noaudio.value = False
            noaudio.update()

    def load_device(e):
        connected_devices = get_connected_devices()
        options = [ft.dropdown.Option(label=f"{device['device_id']} ({device['device_id']}") for device in connected_devices]
        device_dd.options = options
        page.update()


    def start_scrcpy(e):
        nonlocal connect, process

        nv = novideo.value
        na = noaudio.value
        bt = bitrate.value
        audio_s = audiosource.value
        ab = audiobuffer.value
        db = displaybuffer.value

        device = str(device_dd.value)
        print(device)
        command = [scrcpy_path, '-s', device]
        if device != "None":
            if nv == True:
                command.append('--no-video')
            if na == True:
                command.append('--no-audio')
            if bt:
                command += ['-b',f'{bt}M']
            if audio_s is None and audio_s == "内部音声":
                pass
            elif audio_s == "マイク":
                command.append('--audio-source=mic')
            if ab:
                command.append(f'--audio-buffer={ab}')
            if db:
                command.append(f'--display-buffer={db}')
            if connect:
                if process is not None or process.poll() is None:
                    print("プロセスを停止")
                    process.terminate()
                    connect_btn.icon = ft.icons.PLAY_ARROW
                    connect_btn.text = "接続"
                    connect_btn.update()
                connect = False
            else:
                print("プロセスを開始")
                process = subprocess.Popen(command)
                connect = True
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
    
    title = ft.Text("Scrcpy_GUI", style=ft.TextThemeStyle.TITLE_MEDIUM,size=32)
    device_dd = ft.Dropdown(label="デバイス", expand=True, options=[], value=None)
    connect_btn = ft.FloatingActionButton(icon=ft.icons.PLAY_ARROW, text="接続", on_click=start_scrcpy)
    select_device = ft.Row([
        device_dd,
        ft.FilledButton("読み込み", icon=ft.icons.REFRESH, on_click=load_device)
    ], expand=0)
    novideo = ft.Switch(label="画面をキャストしない",value=False,expand=True,on_change=check_av)
    noaudio = ft.Switch(label="音声をキャストしない",value=False,expand=True,on_change=check_av)
    nosource = ft.Row([novideo,noaudio])
    bitrate = ft.TextField(label="映像ビットレート(デフォルト:8)",suffix_text="Mbps")
    audiosource = ft.Dropdown(label="オーディオソース",options=[ft.dropdown.Option("端末内部"),ft.dropdown.Option("マイク")])
    audiobuffer = ft.TextField(label="オーディオバッファー(デフォルト:50)",suffix_text="ms",expand=True)
    displaybuffer = ft.TextField(label="ディスプレイバッファー(デフォルト:0)",suffix_text="ms",expand=True)
    buffers = ft.Row([audiobuffer,displaybuffer])
    options = ft.Column([
        nosource,bitrate,audiosource,buffers
    ],spacing=10)

    page.add(title, select_device, connect_btn,options)

if __name__ == "__main__":
    ft.app(main)
