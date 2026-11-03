Option Explicit
Dim fso, shell, root, pythonw, command
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = root & "\.venv\Scripts\pythonw.exe"
If fso.FileExists(pythonw) Then
    command = Chr(34) & pythonw & Chr(34) & " " & Chr(34) & root & "\main.py" & Chr(34)
ElseIf fso.FileExists(root & "\main.exe") Then
    command = Chr(34) & root & "\main.exe" & Chr(34)
Else
    MsgBox "InputShare Python environment was not found.", vbExclamation, "InputShare"
    WScript.Quit 1
End If
shell.CurrentDirectory = root
shell.Run command, 0, False
