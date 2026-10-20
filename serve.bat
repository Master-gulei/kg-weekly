@echo off
rem KG前沿论文解读 - 本地解读服务入口（双击即可：启动服务并自动打开浏览器）
setlocal
rem 输出为 UTF-8，把控制台切到 UTF-8 代码页避免中文乱码
chcp 65001 >nul
set "ROOT=%~dp0"
rem %~dp0 末尾带反斜杠，会破坏后面的引号，必须去掉
set "ROOT=%ROOT:~0,-1%"
set "PYTHONPATH=%ROOT%\src;%PYTHONPATH%"
rem 轮询等待服务就绪（最多约 20 秒）后自动用默认浏览器打开周报；服务起不来就不开浏览器
start /b "" powershell -NoProfile -WindowStyle Hidden -Command "$u='http://127.0.0.1:8000'; for($i=0;$i -lt 40;$i++){try{Invoke-WebRequest $u -UseBasicParsing -TimeoutSec 1|Out-Null; Start-Process $u; exit}catch{Start-Sleep -Milliseconds 500}}"
rem serve.bat 固定 8000 端口与默认入口；自定义端口/入口请用命令行：run.bat serve --port N --topic X
python -m kg_weekly.cli --project "%ROOT%" serve
endlocal
rem 服务异常退出时停住窗口，方便查看错误原因
pause
