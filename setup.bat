@echo off
chcp 65001 >nul
title Cai dat He thong Invoice Processor
cd /d "%~dp0"

echo ========================================================
echo       CAI DAT HE THONG INVOICE PROCESSOR
echo ========================================================
echo.

:: 1. Kiem tra va cai dat uv (Python Tool va Package Manager)
echo [1/4] Kiem tra moi truong Python va uv...
set "PATH=%USERPROFILE%\.local\bin;%LOCALAPPDATA%\uv\bin;%PATH%"
where uv >nul 2>&1
if %errorlevel% equ 0 goto UV_READY

echo   - uv chua co tren he thong. Dang tu dong tai va cai dat uv...
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex" >nul 2>&1
set "PATH=%USERPROFILE%\.local\bin;%LOCALAPPDATA%\uv\bin;%PATH%"

where uv >nul 2>&1
if %errorlevel% equ 0 goto UV_READY

echo   - Dang thu cai dat uv qua winget...
winget install --id=astral-sh.uv -e --accept-source-agreements --accept-package-agreements >nul 2>&1
set "PATH=%USERPROFILE%\.local\bin;%LOCALAPPDATA%\uv\bin;%PATH%"

where uv >nul 2>&1
if %errorlevel% equ 0 goto UV_READY

:: Neu khong co uv, kiem tra python thuong
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [LOI] Khong tim thay Python hoac uv tren may!
    echo Vui long cai dat Python 3.10 hoac tai uv tu https://astral.sh/uv
    goto FAILED
)

echo   - Su dung Python co san de tao virtualenv...
python -m venv "%~dp0.venv"
call "%~dp0.venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r "%~dp0requirements.txt"
goto PYTHON_DONE

:UV_READY
echo   - uv da san sang. Dang khoi tao moi truong ao Python 3.10...
call uv venv "%~dp0.venv" --python 3.10
if %errorlevel% neq 0 (
    echo [LOI] Khong the tao moi truong ao voi Python 3.10.
    goto FAILED
)
echo   - Dang cai dat cac thu vien Python (requirements.txt)...
call uv pip install -r "%~dp0requirements.txt"
if %errorlevel% neq 0 (
    echo [LOI] Khong the cai dat cac goi trong requirements.txt.
    goto FAILED
)

:PYTHON_DONE
echo   [OK] Backend Python dependencies da duoc cai dat thanh cong.
echo.

:: 2. Kiem tra Node.js va pnpm
echo [2/4] Kiem tra Node.js va pnpm...
set "PATH=C:\Program Files\nodejs;%APPDATA%\npm;%PATH%"
where node >nul 2>&1
if %errorlevel% equ 0 goto NODE_READY

echo   - Node.js chua duoc cai dat. Dang thu cai dat Node.js LTS qua winget...
winget install OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
set "PATH=C:\Program Files\nodejs;%APPDATA%\npm;%PATH%"

where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [LOI] Khong the tu dong cai dat Node.js.
    echo Vui long tai va cai dat Node.js LTS tu: https://nodejs.org/
    echo Sau khi cai dat xong, vui long chay lai setup.bat.
    goto FAILED
)

:NODE_READY
for /f "tokens=*" %%v in ('node -v 2^>nul') do echo   - Node.js version: %%v

where pnpm >nul 2>&1
if %errorlevel% equ 0 goto PNPM_READY

echo   - pnpm chua duoc cai dat. Dang cai dat pnpm toan cuc qua npm...
call npm install -g pnpm
set "PATH=%APPDATA%\npm;%PATH%"

where pnpm >nul 2>&1
if %errorlevel% neq 0 (
    echo   - Thu bat corepack pnpm...
    call corepack enable >nul 2>&1
    call corepack prepare pnpm@latest --activate >nul 2>&1
)

:PNPM_READY
for /f "tokens=*" %%v in ('pnpm -v 2^>nul') do echo   - pnpm version: %%v
echo.

:: 3. Cai dat Frontend dependencies
echo [3/4] Dang cai dat dependencies cho Frontend Dashboard...
cd /d "%~dp0frontend"
call pnpm install
if %errorlevel% neq 0 (
    echo [LOI] pnpm install that bai tai thu muc frontend.
    cd /d "%~dp0"
    goto FAILED
)
cd /d "%~dp0"
echo   [OK] Frontend dependencies da duoc cai dat thanh cong.
echo.

:: 4. Kiem tra thu muc cache, output va file cau hinh .env
echo [4/4] Khoi tao thu muc va file cau hinh...
if not exist "%~dp0cache" mkdir "%~dp0cache"
if not exist "%~dp0output" mkdir "%~dp0output"

if not exist "%~dp0.env.ggproproxyserver" (
    echo # Dien API Token LLM vao day: OPENAI_API_KEY=your_token_here> "%~dp0.env.ggproproxyserver"
    echo   - Da tao file mau .env.ggproproxyserver.
    echo   - LUU Y: Vui long mo file .env.ggproproxyserver va dien API Token truoc khi chay he thong!
) else (
    echo   - File .env.ggproproxyserver da ton tai.
)

echo.
echo ========================================================
echo  * CAI DAT HE THONG HOAN TAT THANH CONG!
echo.
echo  De khoi dong he thong, chay file: start.bat
echo ========================================================
echo.
pause
exit /b 0

:FAILED
echo.
echo ========================================================
echo  [!] QUA TRINH CAI DAT CHUA HOAN TAT DO CO LOI.
echo  Vui long kiem tra lai cac buoc tren.
echo ========================================================
echo.
pause
exit /b 1
