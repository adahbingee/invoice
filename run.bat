@echo off
REM invoice runner批次檔
REM 修改下面的 INPUT_DIR 與 OUTPUT_DIR 來指定輸入與輸出資料夾
set "INPUT_DIR=.\input"
set "OUTPUT_DIR=.\output"

REM 以 main.py 進行處理
python "%~dp0main.py" "%INPUT_DIR%" "%OUTPUT_DIR%"

pause
