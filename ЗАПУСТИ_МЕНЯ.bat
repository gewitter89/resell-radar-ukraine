@echo off
chcp 65001 >nul
echo.
echo ========================================
echo   AUTO SHOPPER - ЗАПУСК
echo ========================================
echo.
echo Останавливаем старые процессы...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq auto_shopper*" >nul 2>&1
del "C:\Users\HOMEH\Desktop\БОТЫ\Фрианс_автоматизация\resell_upgrades\shopper.lock" >nul 2>&1

echo Запускаем Auto Shopper...
cd /d "C:\Users\HOMEH\Desktop\БОТЫ\Фрианс_автоматизация\resell_upgrades"
python auto_shopper.py --loop

pause
