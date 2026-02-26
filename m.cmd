@echo off
setlocal
set ROOT=%~dp0
set PYTHONPATH=%ROOT%;%PYTHONPATH%
pushd "%ROOT%"
python -m musichub.cli %*
set ERR=%ERRORLEVEL%
popd
exit /b %ERR%

