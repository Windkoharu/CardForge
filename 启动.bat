@echo off
rem ===================================================================
rem  CardForge 2.0 - Windows one-click launcher
rem
rem  IMPORTANT - do not "beautify" this file:
rem    * keep it ASCII-only  (Chinese text placed here gets mis-decoded
rem      by cmd under the GBK codepage, and a stray byte can swallow the
rem      next command line - the launcher then does nothing at all)
rem    * keep it CRLF        (LF-only batch files break cmd block parsing)
rem    All Chinese messages are printed by "cardforge launch" in UTF-8.
rem
rem  Usage: double-click for the default flow, or pass a cardforge
rem         subcommand, e.g.  <this-file> doctor  /  <this-file> render --demo
rem ===================================================================
setlocal
title CardForge
chcp 65001 >nul 2>&1
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (where python >nul 2>&1 && set "PY=python")
if not defined PY (where python3 >nul 2>&1 && set "PY=python3")
if not defined PY goto nopython

if not "%~1"=="" goto passthrough

echo.
echo   CardForge - starting (self-check, server, then opening the browser)...
echo.
%PY% -m cardforge launch
goto after

:passthrough
%PY% -m cardforge %*
goto after

:after
if errorlevel 1 goto failed
endlocal
exit /b 0

:failed
echo.
echo   [X] The command exited with an error. The reason is in the messages above.
pause
endlocal
exit /b 1

:nopython
echo.
echo   [X] Python 3.10+ was not found.
echo       Install it from https://www.python.org/downloads/
echo       and remember to tick "Add Python to PATH" during setup.
pause
exit /b 1
