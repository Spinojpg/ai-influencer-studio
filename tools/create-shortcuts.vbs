Option Explicit
Dim sh, fso, appDir, iconPath, pyw, py, target, args, desktop, startDir, s
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
If WScript.Arguments.Count < 1 Then
  WScript.Echo "Usage: create-shortcuts.vbs APPDIR [ICON]"
  WScript.Quit 1
End If
appDir = WScript.Arguments(0)
iconPath = ""
If WScript.Arguments.Count >= 2 Then iconPath = WScript.Arguments(1)
If iconPath = "" Then iconPath = appDir & "\app.ico"
pyw = "C:\ComfyUI-Zluda\venv\Scripts\pythonw.exe"
py = "C:\ComfyUI-Zluda\venv\Scripts\python.exe"
If fso.FileExists(pyw) Then
  target = pyw
  args = """" & appDir & "\launcher.py"""
ElseIf fso.FileExists(py) Then
  target = py
  args = """" & appDir & "\launcher.py"""
ElseIf fso.FileExists(appDir & "\pokreni.vbs") Then
  target = sh.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\wscript.exe"
  args = """" & appDir & "\pokreni.vbs"""
Else
  target = "py"
  args = "-3.11 """ & appDir & "\launcher.py"""
End If
desktop = sh.SpecialFolders("Desktop")
startDir = sh.SpecialFolders("StartMenu") & "\Programs"
If Not fso.FolderExists(startDir) Then fso.CreateFolder startDir
Sub WriteLnk(path)
  Dim s
  Set s = sh.CreateShortcut(path)
  s.TargetPath = target
  s.Arguments = args
  s.WorkingDirectory = appDir
  s.WindowStyle = 7
  s.Description = "AI Influencer Studio"
  If fso.FileExists(iconPath) Then s.IconLocation = iconPath
  s.Save
End Sub
WriteLnk desktop & "\AI Influencer Studio.lnk"
WriteLnk startDir & "\AI Influencer Studio.lnk"
