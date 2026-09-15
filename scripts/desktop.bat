@echo off
REM Builds the Job Watcher Windows app: installs the desktop dependencies into
REM backend\.venv, draws the icon, compiles desktop\JobWatcher.exe and creates the
REM Desktop, Start Menu and Startup shortcuts. Safe to run again.
REM
REM Code changes do NOT require running this again: the exe only opens
REM desktop\app.py, which uses the backend as is and rebuilds a stale frontend.
REM
REM Set JOB_WATCHER_NO_PAUSE=1 to skip the final pause (non interactive runs).

cd /d "%~dp0.."

if not exist "backend\.venv\Scripts\python.exe" (
    echo Virtual environment not found at backend\.venv
    echo Run:  python -m venv backend\.venv
    goto :fail
)
if not exist "frontend\node_modules" (
    echo Frontend dependencies are not installed.
    echo Run:  cd frontend ^&^& corepack pnpm install
    goto :fail
)

set "PY=backend\.venv\Scripts\python.exe"
set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"

echo [1/5] Desktop dependencies in the venv...
"%PY%" -m pip install --disable-pip-version-check -q -r backend\requirements-desktop.txt || goto :fail

echo [2/5] Icon...
"%PY%" desktop\icon.py || goto :fail

echo [3/5] Frontend build...
pushd frontend
call corepack pnpm exec vite build || (popd & goto :fail)
popd

echo [4/5] Compiling JobWatcher.exe...
"%CSC%" /nologo /codepage:65001 /target:winexe /win32icon:desktop\job-watcher.ico /r:System.Windows.Forms.dll /r:System.Core.dll /out:desktop\JobWatcher.exe desktop\Launcher.cs || goto :fail

echo [5/5] Shortcuts (Desktop, Start Menu, start with Windows)...
powershell -NoProfile -Command "$s = New-Object -ComObject WScript.Shell; $exe = '%CD%\desktop\JobWatcher.exe'; foreach ($d in [Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs')) { $l = $s.CreateShortcut((Join-Path $d 'Job Watcher.lnk')); $l.TargetPath = $exe; $l.WorkingDirectory = '%CD%\desktop'; $l.IconLocation = $exe + ',0'; $l.Description = 'Job Watcher'; $l.Save() }; $l = $s.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) 'Job Watcher.lnk')); $l.TargetPath = $exe; $l.Arguments = '--background'; $l.WorkingDirectory = '%CD%\desktop'; $l.IconLocation = $exe + ',0'; $l.Description = 'Job Watcher'; $l.Save()" || goto :fail

echo.
echo Done. Open "Job Watcher" from the Desktop or the Start Menu.
echo It also starts hidden with Windows; toggle that in the tray icon menu.
if not "%JOB_WATCHER_NO_PAUSE%"=="1" pause
exit /b 0

:fail
echo.
echo Failed at the step above.
if not "%JOB_WATCHER_NO_PAUSE%"=="1" pause
exit /b 1
