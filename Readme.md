# Scrcpy GUI for Quest

A simple GUI for [Scrcpy](https://github.com/Genymobile/scrcpy), a tool for displaying and controlling Android devices connected via USB (currently not supported via TCP/IP in this tool). 

This GUI is specifically designed for Meta Quest devices.

![GUI image](./img/showcase.png)

## Features
- Simple GUI of scrcpy
- Mirror multiple devices simultaneously
- Adjust screen size for Quest devices
- Toggle proximity sensor

<!--
## Prerequisites

- Python 3
- [Scrcpy](https://github.com/Genymobile/scrcpy)
- [ADB](https://developer.android.com/studio/command-line/adb) (Android Debug Bridge)
  - ADB path should be set in system variable
- Only works with Windows
-->

## Usage
- Get [Scrcpy](https://github.com/Genymobile/scrcpy)
- Rename scrcpy folder to `scrcpy` (a folder where scrcpy.exe exists)
- Download screen-caster-quest.exe from [release page](https://github.com/hiroyamochi/quest-screen-caster/releases/latest)
- Directory should be like below:
```
screen-caster-quest
├ screen-caster-quest.exe
├ config.ini
└ scrcpy
　 └ scrcpy.exe
```

## Build
- You will need `pyinstaller` to build a binary file (.exe)
- Run following in the project directory:
```bash
pyinstaller main.py --onefile --windowed --icon=icon.ico --add-data "icon.ico;." --name screen-caster-quest
```

## Configuration
You can set the default bitrate & size of mirroring window in the `config.ini` file.

```ini
[scrcpy]
bitrate = 20
size = 1024
```

## Acknowledgement
This tool is based on [scrcpy](https://github.com/Genymobile/scrcpy) by Genymobile, and some features are built by [vuisme](https://github.com/Genymobile/scrcpy/pull/4658#issuecomment-1974796095). Thank you for those great works.