# Scrcpy GUI for Quest

This is a simple GUI for [Scrcpy](https://github.com/Genymobile/scrcpy), a tool for displaying and controlling Android devices connected via USB (currently not supported via TCP/IP). This GUI is specifically designed for Meta Quest devices.

## Prerequisites

- Python 3
- [Scrcpy](https://github.com/Genymobile/scrcpy)
- [ADB](https://developer.android.com/studio/command-line/adb) (Android Debug Bridge)
- Only works with Windows

## Usage
- Get [Scrcpy](https://github.com/Genymobile/scrcpy)
- Rename scrcpy folder to `scrcpy` (a folder where scrcpy.exe exists)
- Download screen-caster-quest.exe from release page
- Directory should be like below:
```
screen-caster-quest
├ screen-caster-quest.exe
└ scrcpy
　 └ scrcpy.exe
```

## Build
- Run following in the project directory:
```bash
pyinstaller --onefile --windowed --add-data main.py --name screen-caster-quest
```

## Configuration

You can set the default bitrate in the `config.ini` file in the same directory as this script. The default bitrate is used when the "Bitrate" field is left empty.

```ini
[scrcpy]
bitrate = 20