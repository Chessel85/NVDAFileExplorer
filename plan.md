# File Explorer Path Copy — NVDA add-on plan

See `requirements.txt` for the original request.

## Goal

Two File Explorer shortcuts, without moving focus from the file list:

| Gesture | Script | Behaviour |
|---|---|---|
| NVDA+Z | `script_copyAddress` | Copy the current folder address. |
| NVDA+V | `script_copyAddressAndSelection` | Copy the full path of each selected item, one per line (`\r\n`). With nothing selected, copy the folder address. |

Gestures belong to the `explorer` app module, so they apply only in File Explorer and take priority over global NVDA gestures there. The user can reassign them in Input Gestures under the "File Explorer path copy" category.

## Prior research (done)

- No existing NVDA add-on does this. The closest is copyURL, which only works in web browsers. Clip Contents Designer and NVDA Clipboard only manage what's already on the clipboard.
- A built-in alternative is Windows 11 **Ctrl+Shift+C** (Copy as path). It wraps each path in quotes and doesn't handle the no-selection case, so the user still wants the add-on.
- None of the user's installed add-ons include an `explorer` app module, so there's no conflict.

## Code location

- Prototype: `%APPDATA%\nvda\scratchpad\appModules\explorer.py` (the NVDA developer scratchpad is enabled).
- Repo copy: `appModules/explorer.py` in github.com/Chessel85/NVDAFileExplorer. Copy the scratchpad file here after changes.
- Reload after edits with NVDA+Ctrl+F3. The NVDA log is at NVDA+F1.

## Design

- `AppModule` subclasses `nvdaBuiltin.appModules.explorer.AppModule` so NVDA's built-in Explorer support keeps working. Don't replace it.
- Paths come from COM `Shell.Application` via `comtypes.client.CreateObject("Shell.Application", dynamic=True)`:
  - `shell.Windows()`: find the entry whose `.HWND` equals `api.getForegroundObject().windowHandle`.
  - Folder: `win.Document.Folder.Self.Path`
  - Selection: in view order through the tab's `IShellBrowser` (see Step 3). Fallback: `win.Document.SelectedItems()` sorted with `StrCmpLogicalW` (Explorer-style name order).
- Paths starting with `::` are virtual locations (This PC, Home, Libraries, Recycle Bin), which the add-on treats as "not a file system folder".
- Clipboard: `api.copyToClip(text, notify=False)`, then `ui.message(...)`.

## Status

### Step 1: copy address (NVDA+Z). DONE, tested by user, works.

### Step 2: copy selection (NVDA+V). DONE, awaiting user testing.
- 0 selected: copies the folder and says "No selection. Copied …".
- 1 selected: copies that path and says "Copied …".
- 2 or more selected: copies the paths joined with `\r\n` and says "Copied N paths".
- Selected items with `::` paths are dropped. Real files selected inside a virtual folder (e.g. Home) still copy.

### Step 3: Windows 11 tabs + selection order. DONE, tested by user, works.
Problem 1: every tab in one Explorer window shares the same top-level HWND, so the first matching tab was used even if it wasn't the active one.
Problem 2 (user report from Step 2): pasted paths weren't in Explorer's display order. `SelectedItems()` returns the view's internal item order, which ignores the sort column and grouping.

Implementation:
- Active tab: the first visible `ShellTabWindowClass` child of the foreground window (`FindWindowExW` + `IsWindowVisible`).
- For each shell window with a matching HWND: `win._comobj` → `IServiceProvider.QueryService(SID_STopLevelBrowser, IShellBrowser)` → `GetWindow()`, which gives the tab's HWND. The one that matches the active tab wins. With a single match it's used directly. If nothing resolves, the first match is used and a debug warning is logged.
- Selection order: `IShellBrowser.QueryActiveShellView` → `IFolderView.Items(SVGIO_SELECTION | SVGIO_FLAG_VIEWORDER)` → `IShellItemArray` → `IShellItem.GetDisplayName(SIGDN_DESKTOPABSOLUTEPARSING)`, which gives the same string as `FolderItem.Path`, so `::` filtering still works. If this fails, the add-on falls back to `SelectedItems()` sorted by `StrCmpLogicalW`.
- Minimal comtypes declarations for `IOleWindow`, `IShellBrowser`, `IFolderView`, `IShellItemArray` and `IShellItem`. `IServiceProvider` comes from comtypes.
- Tested outside NVDA (comtypes 1.4.13, the version NVDA bundles): the active tab HWND matched, and the selection followed a descending name sort. Multiple tabs are untested because `Navigate2` with `navOpenInNewTab` reused the same tab.

### Step 4: edge cases. DONE, tested by user, works.
- Virtual folders (This PC, Home, Libraries, Recycle Bin): user chose to keep the current behaviour. NVDA+Z, and NVDA+V with nothing selected, say "Not a file system folder" and copy nothing.
- Desktop: user chose to support it. The Desktop isn't in `shell.Windows()`, so when the foreground window's class is `Progman` or `WorkerW` (WorkerW is used with a wallpaper slideshow), the add-on calls `shell.Windows().FindWindowSW(CSIDL_DESKTOP, None, SWC_DESKTOP, 0, SWFO_NEEDDISPATCH)`. The returned object works like an Explorer window: `Document.Folder.Self.Path` gives the Desktop folder, and `IServiceProvider` → `IShellBrowser` gives the selection in view order. Tested outside NVDA: the folder was `C:\Users\chess\OneDrive\Desktop` and the selected shortcut was returned. Desktop icons such as Recycle Bin and This PC have `::` paths and are dropped.
- Follow-up from user testing: when only virtual items are selected (e.g. Recycle Bin on the Desktop), NVDA+V used to say "No selection" and copy the folder. It now says "Not a file system folder" and copies nothing. With a mix of real and virtual items, the real paths are still copied.
- Performance: no lag seen, so COM calls stay on the main thread. If lag appears, move them to a background thread and use `queueHandler.queueFunction(queueHandler.eventQueue, ui.message, ...)`.
- Out of scope unless requested: Save/Open dialogs (they belong to other processes, so this would need a global plugin).

User to test: select only Recycle Bin on the Desktop and press NVDA+V.

### Step 5: package as an add-on. TODO
- Use the NVDA add-on template (github.com/nvaccess/AddonTemplate) or a manual layout:
  ```
  FileExplorer/
    manifest.ini
    appModules/explorer.py
    doc/en/readme.md
  ```
- `manifest.ini`: name, summary, description, author, version, `minimumNVDAVersion`, `lastTestedNVDAVersion`.
- Build the `.nvda-addon` as a zip with a renamed extension. Install it, and remove the scratchpad copy so the two don't clash.
- Optional: wrap user-facing strings in `_()` for translation (`addonHandler.initTranslation()`).
