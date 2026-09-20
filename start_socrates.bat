@echo off
echo Starting Socrates Backend (FastAPI)...
start "Socrates Backend" cmd /k ".\.venv\Scripts\activate.bat && uvicorn src.server:app"

echo Starting Socrates Frontend (Vite)...
start "Socrates Frontend" cmd /k ".\.venv\Scripts\activate.bat && cd ui && npm run dev"

echo.
echo Both servers are launching in separate windows!
echo Once they are ready, navigate to http://localhost:5173/ in your browser.
echo.
pause
