# Scrcpy GUI for Quest

This is a simple GUI for [Scrcpy](https://github.com/Genymobile/scrcpy), a tool for displaying and controlling Android devices connected via USB or TCP/IP. This GUI is specifically designed for Oculus Quest devices.

## Prerequisites

- Python 3
- [Scrcpy](https://github.com/Genymobile/scrcpy)
- [ADB](https://developer.android.com/studio/command-line/adb) (Android Debug Bridge)
- Only for Windows

Make sure that `scrcpy` and `adb` are located in the `scrcpy` directory in the same directory as this script.

## Build
- Run following in the project directory:
```bash
pyinstaller --onefile --windowed --add-data "scrcpy;scrcpy" main.py --name screen-caster-quest
```


## Configuration

You can set the default bitrate in the `config.ini` file in the same directory as this script. The default bitrate is used when the "Bitrate" field is left empty. The `config.ini` file should look like this:

```ini
[scrcpy]
bitrate = 20