# NVDA File Explorer Path Copy

An NVDA app module for Windows File Explorer that copies paths to the clipboard without moving focus from the file list.

| Gesture | Behaviour |
|---|---|
| NVDA+Z | Copy the current folder address. |
| NVDA+V | Copy the full path of each selected item, one per line. With nothing selected, copy the folder address. |

Both shortcuts also work on the Desktop and in Windows 11 Explorer tabs. Pasted paths follow the order Explorer shows them in. Virtual locations such as This PC or Recycle Bin report "Not a file system folder".

You can reassign the gestures in NVDA's Input Gestures dialog under the "File Explorer path copy" category.

## Installing (developer scratchpad)

This isn't packaged as an `.nvda-addon` yet. To try it:

1. In NVDA settings, under Advanced, enable loading custom code from the Developer Scratchpad directory.
2. Copy `appModules/explorer.py` to `%APPDATA%\nvda\scratchpad\appModules\`.
3. Press NVDA+Ctrl+F3 to reload plugins.

See `plan.md` for the design and development notes.
