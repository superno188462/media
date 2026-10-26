@echo off
setlocal
for %%I in ("%~dp0..\..") do set "PROJECT_ROOT=%%~fI"
set "BILI_CLI_HOME=%~dp0.runtime\bili-home"
set "PYTHONIOENCODING=utf-8"
set "UV_TOOL_DIR=%~dp0.runtime\uv-tools"
set "UV_TOOL_BIN_DIR=%~dp0.runtime\bin"
"%~dp0.runtime\bin\bili.exe" %*
exit /b %errorlevel%
