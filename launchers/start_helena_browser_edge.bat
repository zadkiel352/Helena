@echo off
for %%I in ("%~dp0..") do set "HELENA_ROOT=%%~fI"
set "BROWSER_EXE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not exist "%BROWSER_EXE%" set "BROWSER_EXE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if not exist "%BROWSER_EXE%" set "BROWSER_EXE=%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"
if not exist "%BROWSER_EXE%" (
  echo No se encontro Microsoft Edge.
  pause
  exit /b 1
)
echo Lanzando Edge con perfil aislado de Helena y extensión cargada...
start "" "%BROWSER_EXE%" ^
  --user-data-dir="%HELENA_ROOT%\browser_profiles\edge_helena" ^
  --load-extension="%HELENA_ROOT%\opera_extension" ^
  --remote-debugging-port=9222 ^
  --no-first-run
echo Navegador iniciado. Helena puede controlarlo via WebSocket (puerto 8766) y CDP (puerto 9222).
pause
