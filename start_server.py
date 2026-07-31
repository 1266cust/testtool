#!/usr/bin/env python3
"""启动Web服务，监听0.0.0.0:8080"""
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

from test_tool.web import app
from test_tool.core.logging import setup_logging

setup_logging()
app.run(host="0.0.0.0", port=9090, debug=False)
