@echo off
call "%~dp0services\bilibili\bili.cmd" %*
exit /b %errorlevel%
