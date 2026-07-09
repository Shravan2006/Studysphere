#!/bin/bash
cd "$(dirname "$0")/backend"
[ -f .env ] || cp .env.example .env
pip install -r requirements.txt
python3 main.py
