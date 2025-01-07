#!/bin/sh
git pull > /dev/null

# env >> /etc/environment
# Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp -nolisten unix &
# nohup gunicorn keep_alive:app --bind 0.0.0.0:7860 &
# nohup flask --app keep_alive run --host 0.0.0.0 --port 7860 &
nohup uvicorn keep_alive_v2:app --host 0.0.0.0 --port 7860 &
# execute CMD
bash mkconf.sh &&
python3 main.py -v -l en -g US
