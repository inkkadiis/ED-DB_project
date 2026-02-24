@echo off
echo ====================================
echo  공장 DB 검수 시스템 시작
echo ====================================
echo.
echo Flask 맵 서버와 Streamlit 앱을 시작합니다...
echo.

REM Flask 서버를 새 창에서 시작
start "Flask Map Server (Port 5001)" cmd /k python map_server.py

REM 2초 대기 (Flask 서버가 먼저 시작되도록)
timeout /t 2 /nobreak >nul

REM Streamlit 앱 시작
start "Streamlit App (Port 8502)" cmd /k streamlit run app.py

echo.
echo ====================================
echo  두 서버가 시작되었습니다!
echo  - Flask 서버: http://localhost:5001
echo  - Streamlit 앱: http://localhost:8502
echo ====================================
echo.
echo 이 창을 닫아도 서버는 계속 실행됩니다.
echo 서버를 종료하려면 각 터미널 창을 닫으세요.
echo.
pause
