'==============================================================================
' start_kb.vbs —— Obsidian 知识库一键启动器(Windows)
'
' 双击运行即可:
'   1. 探测 5173 端口的知识库健康检查;已在跑就直接开浏览器,不重复启动
'   2. 没在跑就启动 python scripts\kb.py serve(完全隐藏窗口,无黑窗)
'   3. 轮询健康检查,最多等 ~30 秒
'   4. 用默认浏览器打开 http://127.0.0.1:5173
'
' 实现要点(实测验证):
'   - wscript 宿主运行,本身不弹控制台窗口。
'   - 用 "cmd /c <python> <kb.py> serve > <log> 2>&1" + 窗口风格 0(SW_HIDE):
'       * cmd /c 让 stdout/stderr 有有效句柄(python 直接 Run 在隐藏下会失效)
'       * > log 重定向便于排查启动失败
'       * cmd /c 派生的进程生命周期独立,wscript 退出后服务继续运行
'   - 路径无空格,故不嵌套双引号(实测嵌套引号会让 shell.Run 静默失败)。
'   - 项目根 = 本脚本所在目录,换机器 / 移动目录都不失效。
'==============================================================================
Option Explicit

Const BASE_URL = "http://127.0.0.1:5173"

Dim fso, shell
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

Dim pth
pth = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = pth

Dim kbDir, logPath
kbDir = fso.BuildPath(pth, ".kb")
logPath = fso.BuildPath(kbDir, "serve_out.log")

Dim pyExe
If fso.FileExists("D:\Python\python.exe") Then
    pyExe = "D:\Python\python.exe"
Else
    pyExe = "python"
End If

Dim kbPy
kbPy = fso.BuildPath(fso.BuildPath(pth, "scripts"), "kb.py")
If Not fso.FileExists(kbPy) Then
    Dim m1
    m1 = "找不到 scripts\kb.py:" & vbCrLf & kbPy & vbCrLf & vbCrLf & "请确认 start_kb.vbs 位于项目根目录。"
    Call MsgBox(m1, vbCritical, "知识库启动失败")
    WScript.Quit(1)
End If

' --- 端口探测:已在跑就直接打开浏览器,不重复启动 ---
If IsServerUp() Then
    shell.Run BASE_URL & "/"
    WScript.Quit(0)
End If

' --- 启动服务(完全隐藏窗口,不阻塞本脚本)---
Dim cmd
cmd = "cmd /c " & pyExe & " " & kbPy & " serve > " & logPath & " 2>&1"
shell.Run cmd, 0, False

' --- 轮询健康检查,最多等 ~30 秒 ---
Dim waited, READY
waited = 0
READY = False
Do While waited <= 30
    WScript.Sleep 1000
    waited = waited + 1
    If IsServerUp() Then
        READY = True
        Exit Do
    End If
Loop

If Not READY Then
    Dim failMsg, failTitle
    failMsg = "启动超时(>30s),知识库服务未就绪。" & vbCrLf & vbCrLf & "请手动在项目根目录运行查看错误:" & vbCrLf & "  python scripts\kb.py serve" & vbCrLf & vbCrLf & "日志文件:" & vbCrLf & logPath
    failTitle = "知识库启动失败"
    Call MsgBox(failMsg, vbExclamation, failTitle)
    WScript.Quit(1)
End If

' --- 打开默认浏览器 ---
shell.Run BASE_URL & "/"
WScript.Quit(0)


'------------------------------------------------------------------------------
' IsServerUp():GET /api/health,每步显式 Err.Clear + 检查;返回 True 仅当 HTTP 200。
' 注1:必须用 GET。/api/health 路由只注册了 GET,用 HEAD 会被 FastAPI 返回 405,
'      导致启动器永远等不到 200,轮询满 30s 误报"未响应"(实测踩坑)。
' 注2:VBS 的 Err 对象全局累积,On Error Resume Next 不会自动清零;
'      若不在每步 Err.Clear,前一步的错误码会让后续判断产生竞态性误报。
'------------------------------------------------------------------------------
Function IsServerUp()
    IsServerUp = False  ' 兜底默认
    Dim http
    On Error Resume Next
    Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
    If Err.Number <> 0 Then Exit Function
    Err.Clear
    http.setTimeouts 1000, 1000, 1000, 1000
    If Err.Number <> 0 Then Exit Function
    Err.Clear
    http.Open "GET", BASE_URL & "/api/health", False
    If Err.Number <> 0 Then Exit Function
    Err.Clear
    http.Send
    If Err.Number <> 0 Then Exit Function
    If http.Status = 200 Then IsServerUp = True
    On Error GoTo 0
End Function
