# Store this code in 'app.py' file
import datetime
import logging
from collections import namedtuple
from typing import Optional

import requests
from flask import Flask, render_template, request, redirect, url_for, session, make_response
import re

from werkzeug import serving

app = Flask(__name__)

User = namedtuple("User", "id username password email")
USERS: dict[str, User] = {}
CAPTCHA_RESPONSES: list[str] = []
INDEX_REDIRECT: Optional[str] = None

logger = logging.getLogger("enfbots_crawler.flask_app")


@app.route("/")
def index():
    if INDEX_REDIRECT:
        return redirect(INDEX_REDIRECT)
    return render_template("baidu.html")


def create_server():
    server = serving.make_server(host="127.0.0.1", port=0, app=app, threaded=True)
    port = server.socket.getsockname()[1]
    return server, port


if __name__ == "__main__":
    app.run()
