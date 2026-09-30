# File Explorer path copying — scratchpad prototype (steps 1–4: address, selection, Windows 11 tabs, Desktop)

import functools
from ctypes import POINTER, WinDLL, byref, c_int, c_uint, c_void_p, wintypes, wstring_at

import api
import ui
import winUser
from logHandler import log
from scriptHandler import script
import comtypes.client
from comtypes import COMMETHOD, GUID, HRESULT, IServiceProvider, IUnknown, STDMETHOD

# Extend NVDA's built-in Explorer support rather than replacing it.
from nvdaBuiltin.appModules.explorer import AppModule as BuiltinExplorerAppModule

SCRIPT_CATEGORY = "File Explorer path copy"

# Private DLL instances so setting argtypes doesn't affect the rest of NVDA.
_user32 = WinDLL("user32")
_user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
_user32.FindWindowExW.restype = wintypes.HWND
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL
_shlwapi = WinDLL("shlwapi")
_shlwapi.StrCmpLogicalW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
_shlwapi.StrCmpLogicalW.restype = c_int
_ole32 = WinDLL("ole32")
_ole32.CoTaskMemFree.argtypes = [c_void_p]
_ole32.CoTaskMemFree.restype = None

SID_STopLevelBrowser = GUID("{4C96BE40-915C-11CF-99D3-00AA004AE837}")
SVGIO_SELECTION = 0x1
SVGIO_FLAG_VIEWORDER = 0x80000000
# Same string as FolderItem.Path: a file system path, or "::{GUID}" for virtual items.
SIGDN_DESKTOPABSOLUTEPARSING = 0x80028000
# IShellWindows.FindWindowSW arguments for finding the Desktop.
CSIDL_DESKTOP = 0
SWC_DESKTOP = 8
SWFO_NEEDDISPATCH = 1
# Window classes of the Desktop's top-level window. WorkerW is used when a wallpaper slideshow is active.
DESKTOP_WINDOW_CLASSES = ("Progman", "WorkerW")


# Minimal shell interface declarations. Methods we never call are declared only to fill vtable slots.

class IOleWindow(IUnknown):
	_iid_ = GUID("{00000114-0000-0000-C000-000000000046}")
	_methods_ = [
		COMMETHOD([], HRESULT, "GetWindow", (["out"], POINTER(wintypes.HWND), "phwnd")),
		STDMETHOD(HRESULT, "ContextSensitiveHelp", [wintypes.BOOL]),
	]


class IShellBrowser(IOleWindow):
	_iid_ = GUID("{000214E2-0000-0000-C000-000000000046}")
	_methods_ = [
		STDMETHOD(HRESULT, "InsertMenusSB", []),
		STDMETHOD(HRESULT, "SetMenuSB", []),
		STDMETHOD(HRESULT, "RemoveMenusSB", []),
		STDMETHOD(HRESULT, "SetStatusTextSB", []),
		STDMETHOD(HRESULT, "EnableModelessSB", []),
		STDMETHOD(HRESULT, "TranslateAcceleratorSB", []),
		STDMETHOD(HRESULT, "BrowseObject", []),
		STDMETHOD(HRESULT, "GetViewStateStream", []),
		STDMETHOD(HRESULT, "GetControlWindow", []),
		STDMETHOD(HRESULT, "SendControlMsg", []),
		STDMETHOD(HRESULT, "QueryActiveShellView", [POINTER(POINTER(IUnknown))]),
	]


class IShellItem(IUnknown):
	_iid_ = GUID("{43826D1E-E718-42EE-BC55-A1E261C37BFE}")
	_methods_ = [
		STDMETHOD(HRESULT, "BindToHandler", []),
		STDMETHOD(HRESULT, "GetParent", []),
		COMMETHOD([], HRESULT, "GetDisplayName",
			(["in"], c_uint, "sigdnName"),
			(["out"], POINTER(c_void_p), "ppszName")),
	]


class IShellItemArray(IUnknown):
	_iid_ = GUID("{B63EA76D-1F85-456F-A19C-48159EFA858B}")
	_methods_ = [
		STDMETHOD(HRESULT, "BindToHandler", []),
		STDMETHOD(HRESULT, "GetPropertyStore", []),
		STDMETHOD(HRESULT, "GetPropertyDescriptionList", []),
		STDMETHOD(HRESULT, "GetAttributes", []),
		COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(wintypes.DWORD), "pdwNumItems")),
		COMMETHOD([], HRESULT, "GetItemAt",
			(["in"], wintypes.DWORD, "dwIndex"),
			(["out"], POINTER(POINTER(IShellItem)), "ppsi")),
	]


class IFolderView(IUnknown):
	_iid_ = GUID("{CDE725B0-CCC9-4519-917E-325D72FAB4CE}")
	_methods_ = [
		STDMETHOD(HRESULT, "GetCurrentViewMode", []),
		STDMETHOD(HRESULT, "SetCurrentViewMode", []),
		STDMETHOD(HRESULT, "GetFolder", []),
		STDMETHOD(HRESULT, "Item", []),
		STDMETHOD(HRESULT, "ItemCount", [c_uint, POINTER(c_int)]),
		STDMETHOD(HRESULT, "Items", [c_uint, POINTER(GUID), POINTER(POINTER(IShellItemArray))]),
	]


def _getActiveTabHwnd(hwnd):
	"""Return the hwnd of the visible tab (ShellTabWindowClass) in an Explorer window, or None."""
	child = None
	while True:
		child = _user32.FindWindowExW(hwnd, child, "ShellTabWindowClass", None)
		if not child:
			return None
		if _user32.IsWindowVisible(child):
			return child


def _getShellBrowser(win):
	# win is a dynamic dispatch wrapper; _comobj is its raw IDispatch pointer.
	provider = win._comobj.QueryInterface(IServiceProvider)
	return provider.QueryService(SID_STopLevelBrowser, IShellBrowser)


def _getDesktopWindow(windows):
	"""Return (shell window, IShellBrowser) for the Desktop, which isn't included in shell.Windows()."""
	# The hwnd argument is an out parameter that dynamic dispatch doesn't return; 0 is a placeholder.
	win = windows.FindWindowSW(CSIDL_DESKTOP, None, SWC_DESKTOP, 0, SWFO_NEEDDISPATCH)
	if win is None:
		return None, None
	try:
		return win, _getShellBrowser(win)
	except Exception:
		log.debugWarning("Error getting shell browser for the Desktop", exc_info=True)
		return win, None


def _getExplorerWindow(hwnd):
	"""Return (shell window, IShellBrowser) for the active tab of the given top-level hwnd, or for the Desktop.
	The browser is None if it couldn't be obtained; both are None if there is no such window."""
	shell = comtypes.client.CreateObject("Shell.Application", dynamic=True)
	windows = shell.Windows()
	if winUser.getClassName(hwnd) in DESKTOP_WINDOW_CLASSES:
		return _getDesktopWindow(windows)
	matches = []
	for i in range(windows.Count):
		try:
			win = windows.Item(i)
			if win is not None and win.HWND == hwnd:
				matches.append(win)
		except Exception:
			log.debugWarning("Error inspecting shell window %d" % i, exc_info=True)
	if not matches:
		return None, None
	# Every tab in a window shares the top-level hwnd, so match each tab's own hwnd to the visible one.
	activeTab = _getActiveTabHwnd(hwnd) if len(matches) > 1 else None
	first = None
	for win in matches:
		try:
			browser = _getShellBrowser(win)
			if first is None:
				first = (win, browser)
			if len(matches) == 1 or (activeTab and browser.GetWindow() == activeTab):
				return win, browser
		except Exception:
			log.debugWarning("Error getting shell browser for Explorer tab", exc_info=True)
	log.debugWarning("Could not identify the active Explorer tab; using the first match")
	return first or (matches[0], None)


def _getFolderPath(win):
	return win.Document.Folder.Self.Path


def _getParsingName(item):
	p = item.GetDisplayName(SIGDN_DESKTOPABSOLUTEPARSING)
	try:
		return wstring_at(p)
	finally:
		_ole32.CoTaskMemFree(p)


def _getSelectedPathsInViewOrder(browser):
	view = POINTER(IUnknown)()
	browser.QueryActiveShellView(byref(view))
	folderView = view.QueryInterface(IFolderView)
	count = c_int()
	folderView.ItemCount(SVGIO_SELECTION, byref(count))
	if not count.value:
		return []
	items = POINTER(IShellItemArray)()
	folderView.Items(SVGIO_SELECTION | SVGIO_FLAG_VIEWORDER, byref(IShellItemArray._iid_), byref(items))
	return [_getParsingName(items.GetItemAt(i)) for i in range(items.GetCount())]


def _getSelectedPaths(win, browser):
	"""Return the selected paths in the order Explorer displays them.
	Falls back to Shell.Application's selection, sorted by name the way Explorer sorts names."""
	if browser is not None:
		try:
			return _getSelectedPathsInViewOrder(browser)
		except Exception:
			log.debugWarning("Could not get selection in view order; sorting by name", exc_info=True)
	items = win.Document.SelectedItems()
	paths = [items.Item(i).Path for i in range(items.Count)]
	return sorted(paths, key=functools.cmp_to_key(_shlwapi.StrCmpLogicalW))


def _isFileSystemPath(path):
	# Virtual locations such as This PC or Home report "::{GUID}" paths.
	return bool(path) and not path.startswith("::")


def _copy(text, message):
	if api.copyToClip(text, notify=False):
		ui.message(message)
	else:
		ui.message("Could not copy to clipboard")


class AppModule(BuiltinExplorerAppModule):

	def _getForegroundExplorerWindow(self):
		"""Return (shell window, IShellBrowser) for the foreground Explorer tab, announcing if there is none."""
		win, browser = _getExplorerWindow(api.getForegroundObject().windowHandle)
		if win is None:
			ui.message("Not in a File Explorer window")
		return win, browser

	@script(
		description="Copies the address of the current File Explorer folder to the clipboard",
		gesture="kb:NVDA+z",
		category=SCRIPT_CATEGORY,
	)
	def script_copyAddress(self, gesture):
		try:
			win, browser = self._getForegroundExplorerWindow()
			if win is None:
				return
			path = _getFolderPath(win)
		except Exception:
			log.error("Failed to get File Explorer address", exc_info=True)
			ui.message("Could not get address")
			return
		if not _isFileSystemPath(path):
			ui.message("Not a file system folder")
			return
		_copy(path, "Copied %s" % path)

	@script(
		description=(
			"Copies the full path of each selected item in File Explorer to the clipboard, one per line. "
			"If nothing is selected, copies the current folder address"
		),
		gesture="kb:NVDA+v",
		category=SCRIPT_CATEGORY,
	)
	def script_copyAddressAndSelection(self, gesture):
		try:
			win, browser = self._getForegroundExplorerWindow()
			if win is None:
				return
			allSelected = _getSelectedPaths(win, browser)
			selected = [p for p in allSelected if _isFileSystemPath(p)]
			folder = None if allSelected else _getFolderPath(win)
		except Exception:
			log.error("Failed to get File Explorer selection", exc_info=True)
			ui.message("Could not get selection")
			return
		if len(selected) == 1:
			_copy(selected[0], "Copied %s" % selected[0])
		elif selected:
			_copy("\r\n".join(selected), "Copied %d paths" % len(selected))
		elif allSelected:
			# Only virtual items such as Recycle Bin or This PC are selected.
			ui.message("Not a file system folder")
		elif _isFileSystemPath(folder):
			_copy(folder, "No selection. Copied %s" % folder)
		else:
			ui.message("Not a file system folder")
