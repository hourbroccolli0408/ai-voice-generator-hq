Option Explicit

Dim shell, environment, filesystem, projectDirectory, command
Set shell = CreateObject("WScript.Shell")
Set environment = shell.Environment("Process")
Set filesystem = CreateObject("Scripting.FileSystemObject")

projectDirectory = filesystem.GetParentFolderName(WScript.ScriptFullName)
environment("VOICEFORGE_ENGINE") = "chatterbox"
environment("VOICEFORGE_DEVICE") = "cpu"
environment("VOICEFORGE_DATA_DIR") = "data"
environment("HF_HOME") = projectDirectory & "\.cache\huggingface"
environment("HF_HUB_DISABLE_SYMLINKS_WARNING") = "1"
shell.CurrentDirectory = projectDirectory

command = Chr(34) & projectDirectory & "\.venv311\Scripts\python.exe" & Chr(34) & _
          " -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
shell.Run command, 0, False

