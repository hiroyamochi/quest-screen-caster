import tkinter as tk
from tkinter import Button
import subprocess
import os
import threading
import configparser
import sys


def find_application_directory():
    if getattr(sys, 'frozen', False):
        # If frozen (in built executable), the path to scrcpy.exe is in same directory as executable
        application_path = sys._MEIPASS
    else:
        # If not frozen (dev environment), the path to scrcpy.exe is in the scrcpy directory
        application_path = os.path.dirname(os.path.abspath(__file__))
    return application_path

# path to scrcpy.exe
scrcpy_path = os.path.join(find_application_directory(), "scrcpy", "scrcpy.exe")

# Load config
def load_config():
    config = configparser.ConfigParser()
    config.read(os.path.join(find_application_directory(), 'config.ini'))
    return config

# Load default bitrate from config
config = load_config()
default_bitrate = config.getint('scrcpy', 'bitrate', fallback=20)
default_size = config.getint('scrcpy', 'size', fallback=1024)

casting_devices = {}

def initialize_adb():
    # adb kill-serverを実行
    subprocess.run(["adb", "kill-server"])
    # Notify the GUI that the initialization is complete
    get_device_details_async()

def start_scrcpy():
    global casting_devices

    # Set options
    device_name = serial_var.get().split()[0]
    serial = device_serials[device_name]
    size = size_entry.get()
    bitrate = bitrate_entry.get() or default_bitrate
    screen_off = screen_off_var.get()
    title = f"Scrcpy for Quest - {serial}"
    device_type = device_type_var.get()

    # Construct the command
    command = [scrcpy_path, "-s", serial, "--no-audio"]
    if size:
        command.extend(["--max-size", size])
    if bitrate:
        command.extend(["--video-bit-rate", str(bitrate)+"M"])
    if screen_off:
        command.append("--power-off-on-close")
    if title:
        command.extend(["--window-title", title])
    
    if device_type == "Quest 2":
        command.append("--crop=1450:1450:140:140")
    elif device_type == "Quest 3":
        command.append("--crop=1650:1650:300:300") # Consider later
    elif device_type == "Quest Pro":
        command.append("--crop=2064:2208:2064:100") # Consider later
    elif device_type == "Other":
        pass
        
    process = subprocess.Popen(
        command,
        creationflags=subprocess.CREATE_NO_WINDOW
        )

    casting_devices[serial] = process

    # Start a separate thread to wait for the process to finish and output any errors
    threading.Thread(target=monitor_casting, args=(serial,)).start()

def monitor_casting(serial):
    global casting_devices

    # Wait for the process to finish
    process = casting_devices[serial]
    stdout, _ = process.communicate()  # This will also capture stderr because of the redirection

    # Print the output, which includes stderr
    # print(stdout.decode())

    # Remove the process from the dictionary
    del casting_devices[serial]

    print("Casting finished.")

def stop_scrcpy():
    global casting_devices

    # Get the serial number from the device_serials dictionary
    device_name = serial_var.get().split()[0]
    serial = device_serials[device_name]
    if serial not in casting_devices:
        print("No casting found for the selected device.")
        return

    process = casting_devices[serial]
    process.terminate()
    del casting_devices[serial]
    print(f"Casting stopped for device: {device_name}")

device_serials = {}

def get_device_details_async():
    def get_device_details():
        result = subprocess.run(["adb", "devices", "-l"], capture_output=True, text=True)
        lines = result.stdout.splitlines()
        devices = []
        for line in lines[1:]:  # Skip the first line
            if "device" in line:
                parts = line.split()
                serial = parts[0]
                details = " ".join(parts[1:])
                # Extract the model name
                model = [s for s in details.split() if "model:" in s][0].replace("model:", "")
                devices.append(model)
                device_serials[model] = serial  # Store the serial number
        
        # Update the dropdown menu with the found devices
        device_label = f"{devices[0]} ({device_serials[devices[0]]})" if devices else ""
        serial_var.set(device_label)
        serial_menu["menu"].delete(0, "end")
        for device in devices:
            serial = device_serials[device]
            label = f"{device} ({serial})"
            serial_menu["menu"].add_command(label=label, command=tk._setit(serial_var, label))
        
        get_button.config(state="normal")  # Re-enable the button
        if devices:
            log_label.config(text="Device ready.")
        else:
            log_label.config(text="No devices found.")

    get_button.config(state="disabled")  # Disable the button while fetching the devices
    threading.Thread(target=get_device_details).start()


def disable_proximity_sensor():
    device_name = serial_var.get().split()[0]
    serial = device_serials[device_name]
    subprocess.run(["adb", "-s", serial, "shell", "am", "broadcast", "-a", "com.oculus.vrpowermanager.prox_close"])

def enable_proximity_sensor():
    device_name = serial_var.get().split()[0]
    serial = device_serials[device_name]
    subprocess.run(["adb", "-s", serial, "shell", "am", "broadcast", "-a", "com.oculus.vrpowermanager.automation_disable"])


# Create Tkinter window
root = tk.Tk()
root.title("Scrcpy GUI for Quest")
# root.resizable(False, False)  # Disable window resizing
root.geometry("600x400")  # Set window size

# Set icon
icon_path = os.path.join(find_application_directory(), "icon.ico")
root.iconbitmap(icon_path)


# Set font
if 'win' in root.tk.call('tk', 'windowingsystem'):
    font = ("MS Gothic", 12)
else:
    font = ("Noto Sans CJK JP", 12)

### Create widgets ###

# Serial number input and Get button
serial_label = tk.Label(root, text="Device:")
serial_label.grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
serial_var = tk.StringVar()
serial_menu = tk.OptionMenu(root, serial_var, "")
serial_menu.grid(row=0, column=1, sticky=tk.EW)
get_button = tk.Button(root, text="Get", command=get_device_details_async)
get_button.grid(row=0, column=2)

# Mirroring window size specification
size_label = tk.Label(root, text="Screen Size (e.g., 1024):")
size_label.grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
size_entry = tk.Entry(root, width=15)
size_entry.grid(row=1, column=1, sticky=tk.EW, padx=5, pady=5)
size_entry.insert(0, str(default_size))  # Insert default size

# Bitrate specification
bitrate_label = tk.Label(root, text="Bitrate (Mbps):")
bitrate_label.grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
bitrate_entry = tk.Entry(root, width=15)
bitrate_entry.grid(row=2, column=1, sticky=tk.EW, padx=5, pady=5)
bitrate_entry.insert(0, str(default_bitrate))  # Insert default bitrate

# Screen off feature when disconnecting
screen_off_var = tk.BooleanVar()
screen_off_var.set(False)
screen_off_checkbox = tk.Checkbutton(root, text="Turn off screen when disconnecting", variable=screen_off_var)
screen_off_checkbox.grid(row=3, column=0, sticky=tk.W, padx=5, pady=5, columnspan=2)

# Start/Stop mirroring buttons
start_stop_label = tk.Label(root, text="Screen Cast:")
start_stop_label.grid(row=4, column=0, sticky=tk.W, padx=5, pady=5)
start_button = tk.Button(root, text="Start", command=start_scrcpy)
start_button.grid(row=4, column=1, padx=5, pady=5, sticky=tk.W)
stop_button = tk.Button(root, text="Stop", command=stop_scrcpy)
stop_button.grid(row=4, column=2, padx=5, pady=5, sticky=tk.W)

# Device Selection
device_type_var = tk.StringVar(value="Other")
device_type_label = tk.Label(root, text="Device Type:")
device_type_label.grid(row=5, column=0, sticky=tk.W, padx=5, pady=5)
quest_2_radio = tk.Radiobutton(root, text="Quest 2", variable=device_type_var, value="Quest 2")
quest_2_radio.grid(row=5, column=1, sticky=tk.W)
quest_3_radio = tk.Radiobutton(root, text="Quest 3", variable=device_type_var, value="Quest 3")
quest_3_radio.grid(row=6, column=1, sticky=tk.W)
quest_pro_radio = tk.Radiobutton(root, text="Quest Pro", variable=device_type_var, value="Quest Pro")
quest_pro_radio.grid(row=7, column=1, sticky=tk.W)
other_radio = tk.Radiobutton(root, text="Other", variable=device_type_var, value="Other")
other_radio.grid(row=8, column=1, sticky=tk.W)

# Buttons for enabling and disabling the proximity sensor
# if device_type_var.get() in ["Quest 2", "Quest 3", "Quest Pro"]:
proximity_sensor_button = Button(root, text="Enable Proximity Sensor", command=enable_proximity_sensor)
proximity_sensor_button.grid(row=5, column=2, padx=5, pady=5)

disable_proximity_sensor_button = Button(root, text="Disable Proximity Sensor", command=disable_proximity_sensor)
disable_proximity_sensor_button.grid(row=6, column=2, padx=5, pady=5)

# Log Message
log_label = tk.Label(root, text="Initializing ADB...")
log_label.grid(row=9, column=0, columnspan=3, padx=5, pady=5)

# Adjust the grid configuration
root.grid_columnconfigure (1, weight=1)
root.grid_columnconfigure (2, weight=1)
root.grid_columnconfigure (3, weight=1)
root.grid_columnconfigure (4, weight=1)

# Initialize ADB in a separate thread to avoid freezing the GUI
threading.Thread(target=initialize_adb).start()

# Start GUI loop
root.mainloop()
