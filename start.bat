@echo off
echo Starting TestTool Web Server...
wsl -e bash -c "cd /home/maxinxin/testtool && source .venv/bin/activate && pkill -f gunicorn 2>/dev/null; sleep 1; gunicorn --workers 2 --bind 0.0.0.0:9090 --chdir /home/maxinxin/testtool 'test_tool.web:app' --timeout 180 --daemon && sleep 2 && echo Server started at http://127.0.0.1:9090/"
echo.
echo Opening browser...
start http://127.0.0.1:9090/
echo.
echo Press Ctrl+C to stop the server, then run: wsl -e bash -c "pkill -f gunicorn"
pause
