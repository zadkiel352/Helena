@echo off
for %%I in ("%~dp0..") do set "HELENA_ROOT=%%~fI"
set "BROWSER_EXE=%LOCALAPPDATA%\Programs\Opera GX\opera.exe"
if not exist "%BROWSER_EXE%" set "BROWSER_EXE=%ProgramFiles%\Opera GX\opera.exe"
if not exist "%BROWSER_EXE%" set "BROWSER_EXE=%ProgramFiles(x86)%\Opera GX\opera.exe"
if not exist "%BROWSER_EXE%" (
  echo No se encontro Opera GX.
  pause
  exit /b 1
)
echo Lanzando Opera Gx con perfil aislado de Helena y extensión cargada (sin CDP)...
start "" "%BROWSER_EXE%" ^
  --user-data-dir="%HELENA_ROOT%\browser_profiles\opera_gx_helena" ^
  --load-extension="%HELENA_ROOT%\opera_extension" ^
  --no-first-run
echo Navegador iniciado. Helena puede controlarlo via WebSocket (puerto 8766).
pause
