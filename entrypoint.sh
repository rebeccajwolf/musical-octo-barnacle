#!/bin/sh
sh -c /usr/bin/supervisord -n && \
    if [ \"$RUN_ON_START\" = \"true\" ]; then bash run_daily.sh >/proc/1/fd/1 2>/proc/1/fd/2; fi
