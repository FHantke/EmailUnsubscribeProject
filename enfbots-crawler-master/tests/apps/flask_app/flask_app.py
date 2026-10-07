# Store this code in 'app.py' file
import datetime
import logging
from collections import namedtuple
from pathlib import Path
from typing import Optional
import re

import requests

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    make_response,
    Blueprint,
)

from werkzeug import serving

bp = Blueprint(
    "website",
    __name__,
)

app = Flask(
    __name__,
    static_url_path="/website/static",
    static_folder="static",
    template_folder="templates",
)

app.secret_key = "your secret key"
app.config["show_links"] = True

User = namedtuple("User", "id username password email")
USERS: dict[str, User] = {}
CAPTCHA_RESPONSES: list[str] = []
INDEX_REDIRECT: Optional[str] = None
RE_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"

logger = logging.getLogger("enfbots_crawler.flask_app")

CONTENT = Path("./tests/enfbots_crawler/data/privacy_policy_sample.txt").open("r").read()


@bp.route("/")
def index():
    if INDEX_REDIRECT:
        return redirect(INDEX_REDIRECT)
    if "redirect_pp_to" in app.config:
        return render_template(
            "index.html",
            show_links=app.config["show_links"],
            redirect_pp_to=app.config["redirect_pp_to"],
        )
    else:
        return render_template(
            "index.html",
            show_links=app.config["show_links"],
            redirect_pp_to=url_for("website.policy"),
        )


@bp.route("/terms")
def terms():
    return render_template("terms.html")


@bp.route("/policy")
def policy():
    if "override_pp_content" in app.config:
        return render_template("policy.html", content=app.config["override_pp_content"])
    else:
        return render_template("policy.html", content=CONTENT)


@bp.route("/login", methods=["GET", "POST"])
def login():
    msg = ""
    if request.method == "POST" and "username" in request.form and "password" in request.form:
        username = request.form["username"]
        password = request.form["password"]
        if username in USERS and USERS[username].password == password:
            session["loggedin"] = True
            session["id"] = USERS[username].id
            session["username"] = USERS[username].username
            msg = "Logged in successfully !"
            return render_template("userspace.html", msg=msg)
        else:
            msg = "Incorrect username / password !"
    return render_template("login.html", msg=msg)


@bp.route("/logout")
def logout():
    session.pop("loggedin", None)
    session.pop("id", None)
    session.pop("username", None)
    return redirect(url_for("website.login"))


@bp.route("/verify", methods=["GET", "POST"])
def verify():
    msg = ""
    if (
        request.method == "POST"
        and "code" in request.form
        and request.form["code"] == app.config["verification_code"]
    ):
        logger.info("Successful registration. Verification code accepted by server")
        return make_response(redirect(url_for("website.confirm_reg")))
    elif request.method == "POST":
        msg = "Registration failed. Wrong verification code!"
    return render_template("verify.html", msg=msg)


@bp.route("/confirm_reg")
def confirm_reg():
    return render_template("confirm_reg.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    msg = ""
    if (
        request.method == "POST"
        and "username" in request.form
        and "password" in request.form
        and "email" in request.form
    ):
        username = request.form["username"]
        password = request.form["password"]
        email = request.form["email"]
        app.logger.info(f"REGISTRATION ATTEMPTS {msg}")
        app.logger.info(f"{username}, {password}, {email}")
        if username in USERS:
            msg = "Account already exists !"
        elif not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            msg = "Invalid email address !"
        elif not re.match(r"[A-Za-z0-9]+", username):
            msg = "Username must contain only characters and numbers !"
        elif not username or not password or not email:
            msg = "Please fill out the form !"
        else:
            USERS[username] = User(len(USERS), username, password, email)
            if "verification_code" in app.config:
                logger.info("Requesting code verification")
                resp = make_response(redirect(url_for("website.verify")))
            else:
                resp = make_response(redirect(url_for("website.index")))
            resp.set_cookie(
                "REGISTERED",
                "is_okay",
                expires=datetime.datetime.now() + datetime.timedelta(hours=1),
            )
            logger.info(f"Registration accepted for user {username}, {password}, {email}")
            return resp
    elif request.method == "POST":
        msg = "Please fill out the form !"
    return render_template("register.html", msg=msg, show_links=app.config["show_links"])


def verify_recaptcha_v2(user_token: str) -> bool:
    resp = requests.post(
        RE_VERIFY_URL, {"secret": app.config["secret_key_recaptcha_v2"], "response": user_token}
    )
    data = resp.json()
    logger.info(f"V2 verification data: {data}")
    return data["success"]


def verify_recaptcha_v3(user_token: str) -> bool:
    resp = requests.post(
        RE_VERIFY_URL, {"secret": app.config["secret_key_recaptcha_v3"], "response": user_token}
    )
    data = resp.json()
    logger.info(f"V3 verification data: {data}")

    return data["score"] >= 0.2 and data["action"] == "submit_action"


H_VERIFY_URL = "https://hcaptcha.com/siteverify"


def verify_hcaptcha(user_token: str) -> bool:
    resp = requests.post(
        H_VERIFY_URL, {"secret": app.config["secret_key_hcaptcha"], "response": user_token}
    )
    logger.info(user_token)
    data = resp.json()
    logger.info(f"H verification data: {data}")
    return data["success"]


@bp.route("/submit/<captcha_type>", methods=["POST"])
def captcha_submit(captcha_type: str):
    logger.info(f"Beginning {captcha_type} verification: {request.form}")
    if "my" in request.args:
        captcha_res = request.form.get("my-captcha-response")
    elif captcha_type == "hcaptcha":
        captcha_res = request.form.get("h-captcha-response")
    else:
        captcha_res = request.form.get("g-recaptcha-response")

    if not captcha_res:
        logger.warning("Captcha failed. No response.")
        return redirect(request.referrer)

    if captcha_res == f"mocked-{captcha_type}-response":
        logger.info("Mock captcha verified")
        return redirect(url_for("website.index"))

    if captcha_type == "recaptcha_v2" and verify_recaptcha_v2(captcha_res):
        logger.info("v2 ok")
        return redirect(url_for("website.index"))
    if captcha_type == "recaptcha_v3" and verify_recaptcha_v3(captcha_res):
        logger.info("v3 ok")
        return redirect(url_for("website.index"))
    if captcha_type == "hcaptcha" and verify_hcaptcha(captcha_res):
        logger.info("h ok")
        return redirect(url_for("website.index"))

    logger.info("Captcha verification failed. " + str(request.referrer))
    return redirect(request.referrer)


@bp.route("/hcaptcha/<scenario>")
def hcaptcha(scenario: str):
    return render_template(f"hcaptcha/{scenario}.html")


@bp.route("/recaptcha_v2/<scenario>")
def recaptcha_v2(scenario: str):
    return render_template(f"recaptcha_v2/{scenario}.html")


@bp.route("/recaptcha_v3/<scenario>")
def recaptcha_v3(scenario: str):
    return render_template(f"recaptcha_v3/{scenario}.html")


@bp.route("/image_captcha")
def image_captcha():
    return render_template(f"image_captcha.html")


@bp.route("/submit/image_captcha", methods=["POST"])
def image_captcha_submit():
    captcha_res = request.form.get("captcha")
    logger.info(f"received captcha response {captcha_res}")
    if captcha_res == "tqatps":
        return redirect(url_for("website.index"))

    logger.info(f"Captcha verification failed. Response was {captcha_res}")
    return redirect(request.referrer)


app.register_blueprint(bp, url_prefix="/website")


def create_server(
    show_links: bool, redirect_pp_to: Optional[str], override_pp_content: Optional[str] = None
):
    server = serving.make_server(host="127.0.0.1", port=0, app=app, threaded=True)
    port = server.socket.getsockname()[1]

    app.config["show_links"] = show_links
    app.config["redirect_pp_to"] = redirect_pp_to
    if override_pp_content is not None:
        app.config["override_pp_content"] = override_pp_content
    else:
        app.config["override_pp_content"] = CONTENT

    return server, port


if __name__ == "__main__":
    app.config["show_links"] = True
    app.config["redirect_pp_to"] = "http://127.0.0.1:5000/ifejfi"

    app.run()
