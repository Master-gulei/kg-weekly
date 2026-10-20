@echo off
rem KG前沿论文解读 - Windows 入口
setlocal
rem 输出为 UTF-8，把控制台切到 UTF-8 代码页避免中文乱码
chcp 65001 >nul
set "ROOT=%~dp0"
rem %~dp0 末尾带反斜杠，会破坏后面的引号，必须去掉
set "ROOT=%ROOT:~0,-1%"
set "PYTHONPATH=%ROOT%\src;%PYTHONPATH%"
rem 无参数双击时默认启动本地解读服务（服务异常退出会停住窗口显示错误原因）
if "%~1"=="" goto serve
python -m kg_weekly.cli --project "%ROOT%" %*
goto done
:serve
rem 轮询等待服务就绪（最多约 20 秒）后自动用默认浏览器打开周报；服务起不来就不开浏览器
start /b "" powershell -NoProfile -WindowStyle Hidden -Command "$u='http://127.0.0.1:8000'; for($i=0;$i -lt 40;$i++){try{Invoke-WebRequest $u -UseBasicParsing -TimeoutSec 1|Out-Null; Start-Process $u; exit}catch{Start-Sleep -Milliseconds 500}}"
python -m kg_weekly.cli --project "%ROOT%" serve
pause
:done
endlocal
