@echo off
rem KG paper digest - local serve entry (double-click to start the server and open the browser)
setlocal
chcp 65001 >nul
set "ROOT=%~dp0"
rem strip the trailing backslash of %~dp0, it breaks quoting below
set "ROOT=%ROOT:~0,-1%"
set "PYTHONPATH=%ROOT%\src;%PYTHONPATH%"
rem data dir may not exist on a fresh clone; the startup log needs it
if not exist "%ROOT%\data" mkdir "%ROOT%\data"
echo [%date% %time%] serve.bat start >> "%ROOT%\data\serve.log"
rem the server opens the browser itself once it is ready; keep the window open on error
python -m kg_weekly.cli --project "%ROOT%" serve
echo [%date% %time%] serve.bat exit %errorlevel% >> "%ROOT%\data\serve.log"
endlocal
pause
