@echo off
rem KG paper digest - Windows entry (double-click with no args starts the local serve)
setlocal
chcp 65001 >nul
set "ROOT=%~dp0"
rem strip the trailing backslash of %~dp0, it breaks quoting below
set "ROOT=%ROOT:~0,-1%"
set "PYTHONPATH=%ROOT%\src;%PYTHONPATH%"
rem data dir may not exist on a fresh clone; the startup log needs it
if not exist "%ROOT%\data" mkdir "%ROOT%\data"
echo [%date% %time%] run.bat start args="[%*]" >> "%ROOT%\data\serve.log"
if "%~1"=="" goto serve
python -m kg_weekly.cli --project "%ROOT%" %*
echo [%date% %time%] cli exit %errorlevel% >> "%ROOT%\data\serve.log"
goto done
:serve
rem the server opens the browser itself once it is ready; keep the window open on error
python -m kg_weekly.cli --project "%ROOT%" serve
echo [%date% %time%] serve exit %errorlevel% >> "%ROOT%\data\serve.log"
pause
:done
endlocal
