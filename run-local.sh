#!/bin/bash
cd "$(dirname "$0")"
unset CLAUDECODE
ENV_FILE=.env.local ./venv/bin/python bot.py
