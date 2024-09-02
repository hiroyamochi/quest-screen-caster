import flet as ft
import subprocess
import os
import sys
import configparser
import re
import threading

def find_application_directory():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(__file__)

scrcpy_path = os.path.join(find_application_directory(), "scrcpy", "scrcpy.exe")
adb_path = os.path.join(find_application_directory(), "scrcpy", "adb.exe")

def load_config():
    config = configparser.ConfigParser()
    config.read(os.path.join(find_application_directory(), 'config.ini'))
    return config

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
    page.title = "Scrcpy GUI for Quest"
    page.padding = 24
    page.theme_mode = ft.ThemeMode.SYSTEM

    devices = []
    device_serials = {}
    casting_devices = {}

    def load_device(e):
        connected_devices = get_connected_devices()
        options = [ft.dropdown.Option(f"{device_name} ({serial_number})") for serial_number, device_name in connected_devices.items()]
        device_dd.options = options
        page.update()

    def start_scrcpy(e):
        device = str(device_dd.value.split(' ')[0])
        serial = device_dd.value.split(' ')[1][1:-1]
        connection_mode = connection_mode_dd.value

        command = [scrcpy_path, "-s", serial, "--no-audio"]
        if connection_mode == "無線":
            ip_address = ip_address_input.value
            command = [scrcpy_path, "--tcpip=" + ip_address]

        if size:
            command.extend(["--max-size", size])
        if bitrate:
            command.extend(["--video-bit-rate", str(bitrate) + "M"])
        
        process = subprocess.Popen(command, creationflags=subprocess.CREATE_NO_WINDOW)
        casting_devices[serial] = process

        threading.Thread(target=monitor_casting, args=(serial,)).start()

    def monitor_casting(serial):
        process = casting_devices[serial]
        process.wait()
        del casting_devices[serial]

    title = ft.Text("Scrcpy GUI for Quest", style=ft.TextThemeStyle.TITLE_MEDIUM, size=32)
    device_dd = ft.Dropdown(label="デバイス", expand=True, options=[])
    connection_mode_dd = ft.Dropdown(label="接続モード", options=[
        ft.dropdown.Option("有線"),
        ft.dropdown.Option("無線")
    ], value="有線")
    ip_address_input = ft.TextField(label="IPアドレス", visible=False)
    connect_btn = ft.FloatingActionButton(icon=ft.icons.PLAY_ARROW, text="接続", on_click=start_scrcpy)
    load_device_btn = ft.FilledButton("読み込み", icon=ft.icons.REFRESH, on_click=load_device)

    def on_connection_mode_change(e):
        ip_address_input.visible = connection_mode_dd.value == "無線"
        page.update()

    connection_mode_dd.on_change = on_connection_mode_change

    page.add(title, device_dd, connection_mode_dd, ip_address_input, load_device_btn, connect_btn)

if __name__ == "__main__":
    ft.app(target=main)