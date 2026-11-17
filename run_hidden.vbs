Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strPath = fso.GetParentFolderName(WScript.ScriptFullName)

WshShell.CurrentDirectory = strPath
WshShell.Run """C:\Users\GANDU\AppData\Local\Programs\Python312\python.exe"" """ & strPath & "\app.py""", 0, False
WScript.Sleep 3000
WshShell.Run """" & strPath & "\cloudflared.exe"" tunnel --url http://localhost:14146", 0, False
