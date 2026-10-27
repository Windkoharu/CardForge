@echo off
rem ===================================================================
rem  CardForge 2.0 - Windows one-click launcher
rem
rem  IMPORTANT - do not "beautify" this file:
rem    * keep it ASCII-only  (Chinese text placed here gets mis-decoded
rem      by cmd under the GBK codepage, and a stray byte can swallow the
rem      next command line - the launcher then does nothing at all)
rem    * keep it CRLF        (LF-only batch files break cmd block parsing)
rem    All Chinese messages are printed by "cardforge launch" (UTF-8) or
rem    by tools\install_python.ps1 (UTF-8 with BOM, bilingual).
rem
rem  Usage: double-click for the default flow, or pass a cardforge
rem         subcommand, e.g.  <this-file> doctor  /  <this-file> render --demo
rem
rem  WHY THIS FILE PROBES INSTEAD OF TRUSTING "where"
rem  ------------------------------------------------
rem  Defect #36: on a fresh PC, "where py" / "where python" can both
rem  "succeed" while the thing they find cannot start at all - most
rem  often the Windows Store "app execution alias" (a dead stub left
rem  behind when the Store Python is not installed or was removed).
rem  Running it prints
rem      The system cannot execute the specified program.
rem  and the launcher dies before Python ever prints a banner.
rem
rem  So every candidate below is ACTUALLY EXECUTED with a >=3.10
rem  version probe, and a broken one is skipped instead of used.
rem  The search covers: explicit override -> project venv -> py
rem  launcher -> PATH -> common install folders (python.org / conda /
rem  uv / Store).  If nothing works, a helper offers to install
rem  Python 3.12 for the current user and then restarts this script.
rem ===================================================================
setlocal EnableExtensions DisableDelayedExpansion
title CardForge
chcp 65001 >nul 2>&1
pushd "%~dp0" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [X] Cannot open the CardForge folder:
    echo       %~dp0
    echo       If it lives on a network share, copy it to a local disk first.
    echo.
    pause
    exit /b 1
)
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
if not defined TEMP set "TEMP=%CD%"
set "CF_PROBE=%TEMP%\cardforge_py_probe_%RANDOM%%RANDOM%.txt"

:restart
set "PY="
set "PYARG="
set "PYVER="
set "PYFAILED="
set "PYOLD="

rem ---- 1. explicit override (portable Python, conda env, ...) -------
if defined CARDFORGE_PYTHON call :probe "%CARDFORGE_PYTHON%"
if defined PY goto :have_python
if defined CARDFORGE_PYTHON echo   [!] CARDFORGE_PYTHON is set but cannot run Python 3.10+; ignored.

rem ---- 2. project venv (optional; see README "develop" section) ----
if exist ".venv\Scripts\python.exe" call :probe "%CD%\.venv\Scripts\python.exe"
if defined PY goto :have_python

rem ---- 3. the official py launcher --------------------------------
call :probe "py" "-3.13"
if defined PY goto :have_python
call :probe "py" "-3.12"
if defined PY goto :have_python
call :probe "py" "-3.11"
if defined PY goto :have_python
call :probe "py" "-3.10"
if defined PY goto :have_python
call :probe "py" "-3"
if defined PY goto :have_python

rem ---- 4. PATH ----------------------------------------------------
call :probe "python"
if defined PY goto :have_python
call :probe "python3"
if defined PY goto :have_python

rem ---- 5. common install folders (real files beat dead aliases) ----
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do call :probe "%%~fD\python.exe"
if defined PY goto :have_python
for /d %%D in ("%ProgramFiles%\Python3*") do call :probe "%%~fD\python.exe"
if defined PY goto :have_python
for /d %%D in ("%ProgramFiles(x86)%\Python3*") do call :probe "%%~fD\python.exe"
if defined PY goto :have_python
for /d %%D in ("C:\Python3*") do call :probe "%%~fD\python.exe"
if defined PY goto :have_python
for /d %%D in ("%APPDATA%\uv\python\cpython-3*") do call :probe "%%~fD\python.exe"
if defined PY goto :have_python
if exist "%USERPROFILE%\anaconda3\python.exe" call :probe "%USERPROFILE%\anaconda3\python.exe"
if defined PY goto :have_python
if exist "%USERPROFILE%\miniconda3\python.exe" call :probe "%USERPROFILE%\miniconda3\python.exe"
if defined PY goto :have_python
if exist "%ProgramData%\anaconda3\python.exe" call :probe "%ProgramData%\anaconda3\python.exe"
if defined PY goto :have_python
if exist "%ProgramData%\miniconda3\python.exe" call :probe "%ProgramData%\miniconda3\python.exe"
if defined PY goto :have_python
if exist "%USERPROFILE%\scoop\apps\python\current\python.exe" call :probe "%USERPROFILE%\scoop\apps\python\current\python.exe"
if defined PY goto :have_python

rem ---- 6. Windows Store alias, last resort ------------------------
if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe" call :probe "%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe"
if defined PY goto :have_python

goto :nopython

rem ===================================================================
rem  :probe  %1 = executable, %2 = optional args (e.g. -3.12)
rem  Sets PY/PYARG/PYVER on success; records PYOLD / PYFAILED on
rem  failure so the error message can tell the two apart.
rem ===================================================================
:probe
if defined PY goto :eof
set "CF_EXE=%~1"
set "CF_ARG=%~2"
"%CF_EXE%" %CF_ARG% -c "import sys;print('.'.join(map(str,sys.version_info[:3])));raise SystemExit(0 if sys.version_info>=(3,10) else 3)" >"%CF_PROBE%" 2>nul
if errorlevel 3 if not errorlevel 4 goto :probe_old
if errorlevel 1 goto :probe_bad
set /p PYVER=<"%CF_PROBE%"
if not defined PYVER goto :probe_bad
set "PY=%CF_EXE%"
set "PYARG=%CF_ARG%"
goto :eof

:probe_old
set "PYOLD=1"
goto :eof

:probe_bad
set "PYFAILED=1"
goto :eof

rem ===================================================================
:have_python
echo   Using Python %PYVER%  [%PY% %PYARG%] 1>&2
if not "%~1"=="" goto :passthrough

echo.
echo   CardForge - starting (self-check, server, then opening the browser)...
echo.
"%PY%" %PYARG% -m cardforge launch
goto :after

:passthrough
"%PY%" %PYARG% -m cardforge %*
goto :after

:after
if errorlevel 1 goto :failed
del "%CF_PROBE%" >nul 2>&1
popd
endlocal
exit /b 0

:failed
echo.
echo   [X] The command exited with an error. The reason is in the messages above.
echo.
echo       Next steps:
echo         * run  "%~nx0 doctor"  for the full environment report
echo         * a firewall / proxy can block the first-run Pillow install;
echo           set CARDFORGE_NO_PIP=1 to skip that prompt
echo.
pause
del "%CF_PROBE%" >nul 2>&1
popd
endlocal
exit /b 1

rem ===================================================================
rem  No usable interpreter.  Explain why, then offer a one-click
rem  installer (bilingual UI lives in install_python.ps1).
rem ===================================================================
:nopython
echo.
if defined PYFAILED goto :np_broken
if defined PYOLD goto :np_old
echo   [X] No Python 3.10+ was found on this computer.
goto :np_offer

:np_broken
echo   [X] A Python was found, but Windows could not start it.
echo       This is usually the dead Microsoft Store "app execution alias"
echo       ^(Settings ^> Apps ^> Advanced app settings ^> App execution aliases^),
echo       or a damaged Python installation.
goto :np_offer

:np_old
echo   [X] Python was found, but it is older than 3.10.

:np_offer
echo.
if defined CF_RELAUNCHED goto :np_manual
if not exist "tools\install_python.ps1" goto :np_manual
echo   CardForge can install Python 3.12 for you
echo   ^(current user only, no administrator rights, about 30 MB^).
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\install_python.ps1"
if errorlevel 1 goto :np_manual
set "CF_RELAUNCHED=1"
echo.
echo   Python is ready - restarting CardForge...
echo.
goto :restart

:np_manual
echo   Manual fix:
echo     1. Install Python 3.10+ from https://www.python.org/downloads/windows/
echo        and tick "Add python.exe to PATH" during setup.
echo     2. Double-click this file again.
echo.
echo   Using a portable/conda Python? Set CARDFORGE_PYTHON to its python.exe.
echo.
pause
del "%CF_PROBE%" >nul 2>&1
popd
exit /b 1
