@echo off
cd backend
if not exist .env copy .env.example .env
pip install -r requirements.txt
python main.py
