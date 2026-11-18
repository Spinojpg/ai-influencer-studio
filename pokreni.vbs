Option Explicit
Dim sh, fso, appDir, dataDir, pyw, py, cmd, envRoot
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
dataDir = fso.GetParentFolderName(appDir) & "\data"
If fso.FolderExists(dataDir) Then
  sh.Environment("PROCESS")("STUDIO_DATA_DIR") = dataDir
End If
sh.Environment("PROCESS")("STUDIO_APP_DIR") = appDir
pyw = "C:\ComfyUI-Zluda\venv\Scripts\pythonw.exe"
py = "C:\ComfyUI-Zluda\venv\Scripts\python.exe"
If fso.FileExists(pyw) Then
  sh.Run """" & pyw & """ """ & appDir & "\launcher.py""", 0, False
  WScript.Quit 0
End If
If fso.FileExists(py) Then
  sh.Run """" & py & """ """ & appDir & "\launcher.py""", 0, False
  WScript.Quit 0
End If
On Error Resume Next
sh.Run "py -3.11 """ & appDir & "\launcher.py""", 0, False
If Err.Number = 0 Then WScript.Quit 0
Err.Clear
sh.Run "pythonw """ & appDir & "\launcher.py""", 0, False
If Err.Number = 0 Then WScript.Quit 0
Err.Clear
sh.Run "python """ & appDir & "\launcher.py""", 0, False
If Err.Number = 0 Then WScript.Quit 0
MsgBox "Nisam nasao Python. Ocekujem C:\ComfyUI-Zluda\venv ili py -3.11.", 16, "AI Influencer Studio"
WScript.Quit 1
