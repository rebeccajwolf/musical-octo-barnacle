#!/bin/sh
git pull > /dev/null
# nohup uvicorn keep_alive:app --host 0.0.0.0 --port 7860 &
# execute CMD
bash mkconf.sh &&
python3 main.py -v -l en -g US