## Ounce-bt

<p float="left">
    <img src="./assets/Homepage.png" alt="Homepage" width="70%" />
    <img src="./assets/CompactHomepage.png" alt="Compact Homepage" width="29%" />
</p>
<p float="left">
  <img src="./assets/PresetEditor.png" alt="Macro Editor" width="33%" />
  <img src="./assets/MacroEditor.png" alt="Preset Editor" width="33%" />
  <img src="./assets/Appearance.png" alt="Controller Appearance" width="33%" />
</p>

## Setup Instructions

### Windows

### Zadig

Firstly , your bluetooth adapter needs to be adapted to WinUSB firmware.\
See [Instructions](https://google.github.io/bumble/platforms/windows.html)

This does not modify the adapter firmware and is reversible.

### BT Firmware

Ounce-bt on Windows requires separately obtained `rtl8761bu_fw.bin` and
`rtl8761bu_config.bin` firmware files.\
These are not distributed with Ounce-bt for licensing reasons.\
They can be found from the [Linux kernel Git](https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/rtl_bt/)

If either file is missing, the frontend will notify you.\
The files should be placed in the same folder as the executable.

### Download and install

Once your adapter firmware has been switched to winUSB

- Download the latest build from [releases](https://github.com/jchu634/Ounce-bt/releases/)
- Run the installer and (Optionally) provide the path to the firmware if you have downloaded it.

### Linux:

Linux builds are distributed as an AppImage and there is no need to supply your own firmware as Ounce-bt uses the kernel's bundled firmware.

Download and extract the Linux release ZIP, then launch from its extracted folder:

```bash
./run-with-hci-caps.sh "$PWD/Ounce-bt-x86_64.AppImage" usb:0
```

More documentation at [Linux documentation](docs/linux.md).

## Credits

This project includes code adapted from Brikwerk's [NXBT](https://github.com/Brikwerk/nxbt) project.\
The project also utilised typenoob's bumble implementation [(NXBT)](https://github.com/typenoob/nxbt) for help in understanding the pairing protocol.\
Rumble decoding was built upon dekuNukem's [Switch RE notes](https://github.com/dekuNukem/Nintendo_Switch_Reverse_Engineering)

## Technical Details

### Configuration

Configuration files are stored in

- Windows: `%APPDATA%/ounce-bt/config.json`
- Linux: `$XDG_CONFIG_HOME/ounce-bt/config.json`, (Default: `~/.config/ounce-bt/config.json`)

#### Arguments

Settings can overridden for a single run with these command-line arguments.\
Run `uv run main.py --help` for the full help text.

| Argument                                             | Description                                                                      |
| ---------------------------------------------------- | -------------------------------------------------------------------------------- |
| `[device_config]`                                    | Optional Bumble device configuration JSON path.                                  |
| `[transport_spec]`                                   | Bluetooth transport, default `usb:0`. Can be supplied without `[device_config]`. |
| `[bt_address]`                                       | Optional Bluetooth address for the Realtek firmware patch.                       |
| `--input controller\|controller:<idx>\|macro:<path>` | Enable an input source; repeat to enable multiple sources.                       |
| `--web-host HOST`                                    | Web server bind host. Defaults to `127.0.0.1`.                                   |
| `--web-port PORT`                                    | Web server bind port. Defaults to `9127`.                                        |
| `--nolog`                                            | Disable logging for this run.                                                    |
| `--preset NAME\|PATH`                                | Controller mapping preset                                                        |
| `--firmware-dir PATH`                                | Windows: location of separately obtained Realtek firmware files.                 |

Command-line values override configuration for the current run and are not saved.
