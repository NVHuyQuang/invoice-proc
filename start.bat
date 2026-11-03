@echo off
chcp 65001 >nul
title Khởi động Hệ thống Invoice Processor
cd /d "%~dp0"

echo ========================================================
echo       HỆ THỐNG INVOICE PROCESSOR (FASTAPI + NEXTJS)
echo ========================================================
echo.

echo [1/2] Đang khởi động FastAPI Microservice Backend (Port 8000)...
start "FastAPI Backend (Port 8000)" /d "%~dp0" cmd /k "uv run uvicorn service:app --reload --port 8000"

echo [2/2] Đang khởi động Next.js Frontend Dashboard (Port 3000)...
start "Next.js Frontend (Port 3000)" /d "%~dp0frontend" cmd /k "pnpm dev"

echo.
echo Đang mở trình duyệt tới http://localhost:3000 ...
%SystemRoot%\System32	imeout.exe /t 3 /nobreak >nul 2>&1 || ping -n 4 127.0.0.1 >nul
start http://localhost:3000

echo.
echo ========================================================
echo  ✓ Hệ thống đã được khởi động thành công!
echo  - Backend API: http://127.0.0.1:8000 (Docs: http://127.0.0.1:8000/docs)
echo  - Frontend Dashboard: http://localhost:3000
echo.
echo  LƯU Ý: Không tắt 2 cửa sổ cmd chạy nền (Backend và Frontend).
echo  Bạn có thể đóng cửa sổ này bất kỳ lúc nào.
echo ========================================================
echo.
pause
