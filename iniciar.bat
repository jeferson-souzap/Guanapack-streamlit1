@echo off
REM Abre o Guanapack PCP no navegador (http://localhost:8501)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Criando o ambiente virtual...
    python -m venv .venv || goto :erro
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :erro
)
start "" http://localhost:8501
".venv\Scripts\python.exe" -m streamlit run app.py
goto :eof
:erro
echo Falhou. Confira se o Python esta instalado.
pause
