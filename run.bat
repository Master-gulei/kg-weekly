@echo off
rem KG 每周前沿 - Windows 入口
setlocal
rem 输出为 UTF-8，把控制台切到 UTF-8 代码页避免中文乱码
chcp 65001 >nul
set "ROOT=%~dp0"
rem %~dp0 末尾带反斜杠，会破坏后面的引号，必须去掉
set "ROOT=%ROOT:~0,-1%"
set "PYTHONPATH=%ROOT%\src;%PYTHONPATH%"
python -m kg_weekly.cli --project "%ROOT%" %*
endlocal
