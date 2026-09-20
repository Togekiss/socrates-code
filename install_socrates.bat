@echo off
echo Activating Python virtual environment...
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
    echo Downloading Socrates UI dependencies...
    cd ui
    call npm install
    cd ..
    echo UI dependencies installed successfully!
    pause
) else (
    echo WARNING: Virtual environment not found at .venv\Scripts\activate.bat
)

