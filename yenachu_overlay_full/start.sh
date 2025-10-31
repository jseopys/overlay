#!/bin/bash
# Node 서버 실행 (백그라운드)
node chzzk_vts_throw.js &

# Python 서버 실행 (포그라운드)
python run.py