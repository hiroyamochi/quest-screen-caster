# quest-screen-caster 実装ドキュメント

最終更新: 2026-06-08

---

## 概要

Meta Quest ヘッドセット複数台を同時にミラーリングするアプリ。  
公式 Meta Quest Developer Hub (MQDH) は1台しか同時ミラーリングできないため、自作アプリで複数台対応。

---

## アーキテクチャ

```
main.py                      # Flet GUI (v0.85.2)
mirror_backend/
    base.py                  # MirrorBackend 抽象基底クラス
    scrcpy.py                # Scrcpy バックエンド (旧実装)
    screenrecord.py          # ADB screenrecord バックエンド
    casting.py               # MQDH Casting.exe バックエンド (新規追加)
    virtual_camera.py        # 仮想カメラ出力 (pyvirtualcam + ffmpeg)
    utils.py                 # adb/scrcpy パス解決など共通ユーティリティ
```

---

## バックエンド: MirrorBackend 基底クラス (`mirror_backend/base.py`)

全バックエンドが実装するインタフェース:

```python
class MirrorBackend(ABC):
    def start(self, serial: str, options: dict) -> None: ...
    def stop(self) -> None: ...
    def is_running(self) -> bool: ...
```

---

## バックエンド: CastingBackend (`mirror_backend/casting.py`)

### 方針

MQDH のミラーリングは独自プロトコル (XRSP) を使っており直接再実装は困難。  
代わりに MQDH に同梱されている `Casting.exe` を1台ごとにプロセスとして起動する。

### Casting.exe の場所

```
C:\Program Files\Meta Quest Developer Hub\resources\bin\Casting\Casting.exe
```

### 起動引数

```
Casting.exe
  --adb <adb.exe へのパス>
  --application-caches-dir <キャッシュディレクトリ (デバイスごと)>
  --exit-on-close
  --launch-surface MQDH
  --target-device {"id":"<serial>"}
  --launch-surface-session-uuid <UUID>
  [--features <feature1> <feature2> ...]
```

`--target-device` の値は JSON 文字列。  
`--launch-surface-session-uuid` は起動ごとに `uuid.uuid4()` で生成。

キャッシュディレクトリ:
```
%LOCALAPPDATA%\Meta Quest Developer Hub\MagicIsland\Cache\<serial>
```

### 停止

1. `process.terminate()` でプロセスを終了
2. ADB ブロードキャストで Quest 側にも停止を通知:
   ```
   adb -s <serial> shell am broadcast -a com.oculus.magicislandcastingservice.STOP_CASTING
   ```

### 制限

- Casting.exe はウィンドウを表示する (バックグラウンド化不可)
- `CREATE_NO_WINDOW` フラグを使っているが、Casting.exe 自身がウィンドウを作る
- 複数台起動した場合、それぞれ独立したウィンドウが表示される

---

## バックエンド: VirtualCameraOutput (`mirror_backend/virtual_camera.py`)

### 方針

OBS の「映像キャプチャデバイス」ソースとして Quest の映像を入力する機能。  
pyvirtualcam + ffmpeg で実現。

### 動作フロー

```
ADB stdout (H.264 raw)
    → ffmpeg (デコード: H.264 → RGB24 rawvideo)
    → pyvirtualcam (OBS Virtual Camera ドライバ経由で仮想カメラとして公開)
```

### 要件

- OBS をインストールしておくこと (OBS Virtual Camera ドライバが必要)
- ffmpeg が PATH に通っていること
- pyvirtualcam, numpy がインストールされていること

### 実装上の注意

- `pyvirtualcam.Camera` は1プロセスに1インスタンスのみ
- 複数台を仮想カメラ出力する場合、デバイスラベルで区別するが OBS 側でデバイスが1つしか見えない可能性あり (未検証)

---

## GUI (`main.py`)

### Flet バージョン

**Flet 0.85.2** を使用。  
現在の実装は `main.py` の既存 API をそのまま使える範囲に収まっており、`ft.app(target=main)` でも `ft.run(main)` でも起動可能。将来の切替に備えて、Flet 側の非推奨警告が出たら `ft.run(main)` へ寄せる。

### 主要 UI コンポーネント

| コンポーネント | 役割 |
|---|---|
| `device_dd` | 接続デバイス選択ドロップダウン |
| `backend_dd` | バックエンド選択 (Scrcpy / ScreenRecord / Casting) |
| `eye_dd` | 視点選択 (両眼 / 左眼 / 右眼) |
| `connect_btn` | ミラーリング開始/停止ボタン |
| `vcam_switch` | 仮想カメラ出力の ON/OFF |
| `is_cast_video` | 映像キャストの ON/OFF |
| `is_cast_audio` | 音声キャストの ON/OFF |
| `settings_btn` | 映像補正設定ドロワーを開く |

### バックエンドの管理

`casting_devices` dict でデバイスごとのバックエンドインスタンスを管理:

```python
casting_devices = {
    "<serial>": {"backend": <MirrorBackend instance>},
    ...
}
```

`monitor_backend` スレッドが `is_running()` をポーリングし、プロセスが終了したら UI を更新。

### ウィンドウ終了処理

```python
page.window_prevent_close = True

def on_window_event(e):
    if e.data == "close":
        on_app_exit()          # 全バックエンドを停止
        page.window_destroy()  # ウィンドウを閉じる

page.on_window_event = on_window_event
```

`atexit` でも `on_app_exit` を登録し、強制終了時にも後処理が走るようにしている。

---

## 環境構築

```powershell
# venv 作成 (uv を使用)
uv venv .venv --python 3.13

# 依存インストール
uv pip install "flet[all]==0.85.2"
uv pip install pyvirtualcam numpy
```

### `pyproject.toml`

```toml
[project]
name = "quest-screen-caster"
version = "0.2.0"
requires-python = ">=3.10"
dependencies = [
    "flet[all]==0.85.2",
    "pyvirtualcam>=0.15",
    "numpy>=2.0",
]
```

---

## MQDH リバースエンジニアリング調査メモ

### XRSP プロトコル

MQDH のミラーリングは **XRSP (XR Streaming Protocol)** という独自プロトコルを使用。  
USB (WinUSB/libusb) または TCP 上で動作する。

- **再利用可否**: 困難。バイナリのみ提供でプロトコル仕様は非公開。
- **代替策**: Casting.exe を子プロセスとして起動する方法を採用。

### Casting.exe の内部構造

- React Native for Windows (UWP アプリ) 約32.7MB
- `MagicDirectShowFilterView`: DirectShow フィルタで仮想 WebCam として映像を公開
- `MagicSessionManager`: XRSP セッション管理、状態遷移 (0→1→2→4=CASTING)
- `magicdsfilterQuest*.dll`: DirectShow 仮想カメラフィルタ、共有メモリで NV12 フレームを受け渡し
- H.264 デコードは Media Foundation (Windows 標準) を使用

### Casting.exe の動作ログ (正常時)

```
[DeviceSession] Starting connection loop..
[DeviceSession] Connection state changed to CONNECTING
session state transitioned from 0 to 1
Got handshake from headset with protocol version: 1
session state transitioned from 1 to 2
Got resolution from headset: 2064 x 2208
session state transitioned from 2 to 4
[DeviceSession] Connection state changed to CASTING
[MagicCastingView] Screen size: 1920x1152
Frame Rendered in ~85ms  (約12fps, 実際は24fps設定)
```

---

## 既知の問題・TODO

- [ ] Casting.exe がウィンドウを表示してしまう (非表示化の手段が現時点でない)
- [ ] 仮想カメラ出力は未エンドツーエンドテスト (Quest 実機で未確認)
- [ ] 複数台の仮想カメラ同時出力は未検証
- [ ] `stop()` 時に ADB ブロードキャストが `com.oculus.vrpowermanager.automation_disable` になっているが、正しいのは `com.oculus.magicislandcastingservice.STOP_CASTING` のはず (要確認)
