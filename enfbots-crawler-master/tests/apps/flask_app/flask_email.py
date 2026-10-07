import datetime
import logging
from collections import namedtuple
from typing import Optional

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
import re

from email.mime.text import MIMEText
from smtplib import SMTP

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

logger = logging.getLogger("enfbots_crawler.flask_email")


# SMTP settings for sending the verification email
server = "infsec-server.inf.ethz.ch"
sender = "flask_app@infsec-server.inf.ethz.ch"
flask_host = "127.0.0.1"


def send_email_infsec_server(subject, content, dest_email) -> None:
    message = MIMEText(content, "plain")

    message["Subject"] = subject
    message["From"] = sender
    message["To"] = dest_email

    connection = SMTP(server)
    connection.send_message(message, sender, dest_email)


# Set the verification code such that we send an email with it and
# the bot must click on it which calls /verify
app.config["verification_code"] = "94Dg94Brkd_code"

app.secret_key = "your secret key"

User = namedtuple("User", "id username password email verified")
USERS: dict[str, User] = {}
CAPTCHA_RESPONSES: list[str] = []
INDEX_REDIRECT: Optional[str] = None
SHOW_LINKS = True


@bp.route("/")
def index():
    if INDEX_REDIRECT:
        return redirect(INDEX_REDIRECT)
    return render_template("index.html", show_links=SHOW_LINKS)


@bp.route("/terms")
def terms():
    return render_template("terms.html")


@bp.route("/policy")
def policy():
    return render_template("policy.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    msg = ""
    if request.method == "POST" and "username" in request.form and "password" in request.form:
        username = request.form["username"]
        password = request.form["password"]
        if username in USERS and USERS[username].password == password:
            if USERS[username].verified:
                session["loggedin"] = True
                session["id"] = USERS[username].id
                session["username"] = USERS[username].username
                msg = "Logged in successfully !"
                return render_template("userspace.html", msg=msg)
            else:
                msg = "Not verified yet !"
        else:
            msg = "Incorrect username / password !"
    return render_template("login.html", msg=msg)


@bp.route("/logout")
def logout():
    session.pop("loggedin", None)
    session.pop("id", None)
    session.pop("username", None)
    return redirect(url_for("website.login"))


# TODO: Implement this and have a startup parameter for this to create tests
# Verification with simple GET
@bp.route("/verify_get/<user>/<vcode>", methods=["GET"])
def verify_get(user, vcode):
    if vcode == app.config["verification_code"]:
        USERS[user] = USERS[user]._replace(verified=True)
        app.logger.info("Successful registration. Verification code accepted by server")
    else:
        expected_code = app.config["verification_code"]
        app.logger.warn(
            f"Failed registration. Verification code received: {vcode} but expected {expected_code}"
        )


@bp.route("/verify_post", methods=["POST", "GET"])
def verify_post():
    msg = ""
    if (
        request.method == "POST"
        and "code" in request.form
        and request.form["code"] == app.config["verification_code"]
    ):
        username = session.get("username")
        USERS[username] = USERS[username]._replace(verified=True)
        app.logger.info(
            f"Successful registration. Verification code accepted by server for {username}"
        )
        return make_response(redirect(url_for("website.confirm_reg")))
    elif request.method == "POST":
        msg = "Registration failed. Wrong verification code!"
        app.logger.info("Registration failed. Wrong verification code!")
    return render_template("verify.html", msg=msg)


@bp.route("/confirm_reg")
def confirm_reg():
    app.logger.debug("confirmed registration")
    return render_template("confirm_reg.html")


@bp.route("/sent_verification")
def sent_verification():
    app.logger.debug("sent verification")
    return render_template("sent_verification.html")


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
            USERS[username] = User(len(USERS), username, password, email, False)
            if "verification_code" in app.config:
                app.logger.info("Requesting code verification")
                resp = make_response(redirect(url_for("website.sent_verification")))

                # Send email
                # content = """\
                # Hello user, \nThis is your verification code: {}
                # """.format(app.config["verification_code"])

                # Basic email. TODO: Email with href, Email with code only
                content = """\
                    Hello {},

                    Click this link to verify your account: <a href="{}/verify_get/{}">click</a>
                    """.format(
                    username, request.base_url, app.config["verification_code"]
                )
                send_email_infsec_server("Please verify your account", content, email)
                app.logger.info(f"Sent verification email for user {username}")
            else:
                resp = make_response(redirect(url_for("website.index")))
                app.logger.info(f"Registration accepted for user {username}, {password}, {email}")
            resp.set_cookie(
                "REGISTERED",
                "is_okay",
                expires=datetime.datetime.now() + datetime.timedelta(hours=1),
            )
            return resp
    elif request.method == "POST":
        msg = "Please fill out the form !"
    return render_template("register.html", msg=msg)


RE_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"


def verify_recaptcha_v2(user_token: str) -> bool:
    resp = requests.post(
        RE_VERIFY_URL, {"secret": app.config["secret_key_recaptcha_v2"], "response": user_token}
    )
    data = resp.json()
    app.logger.info(f"V2 verification data: {data}")
    return data["success"]


def verify_recaptcha_v3(user_token: str) -> bool:
    resp = requests.post(
        RE_VERIFY_URL, {"secret": app.config["secret_key_recaptcha_v3"], "response": user_token}
    )
    data = resp.json()
    app.logger.info(f"V3 verification data: {data}")

    return data["score"] >= 0.2 and data["action"] == "submit_action"


H_VERIFY_URL = "https://hcaptcha.com/siteverify"


def verify_hcaptcha(user_token: str) -> bool:
    resp = requests.post(
        H_VERIFY_URL, {"secret": app.config["secret_key_hcaptcha"], "response": user_token}
    )
    app.logger.info(user_token)
    data = resp.json()
    app.logger.info(f"H verification data: {data}")
    return data["success"]


@bp.route("/submit/<captcha_type>", methods=["POST"])
def captcha_submit(captcha_type: str):
    app.logger.info(f"Beginning {captcha_type} verification: {request.form}")
    if "my" in request.args:
        captcha_res = request.form.get("my-captcha-response")
    elif captcha_type == "hcaptcha":
        captcha_res = request.form.get("h-captcha-response")
    else:
        captcha_res = request.form.get("g-recaptcha-response")

    if not captcha_res:
        app.logger.warning("Captcha failed. No response.")
        return redirect(request.referrer)

    if captcha_res == f"mocked-{captcha_type}-response":
        app.logger.info("Mock captcha verified")
        return redirect(url_for("website.index"))

    if captcha_type == "recaptcha_v2" and verify_recaptcha_v2(captcha_res):
        app.logger.info("v2 ok")
        return redirect(url_for("website.index"))
    if captcha_type == "recaptcha_v3" and verify_recaptcha_v3(captcha_res):
        app.logger.info("v3 ok")
        return redirect(url_for("website.index"))
    if captcha_type == "hcaptcha" and verify_hcaptcha(captcha_res):
        app.logger.info("h ok")
        return redirect(url_for("website.index"))

    app.logger.info("Captcha verification failed. " + str(request.referrer))
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
    app.logger.info(f"received captcha response {captcha_res}")
    if captcha_res == "tqatps":
        return redirect(url_for("website.index"))

    app.logger.info(f"Captcha verification failed. Response was {captcha_res}")
    return redirect(request.referrer)


app.register_blueprint(bp, url_prefix="/website")


def create_server():
    app.logger.setLevel(logging.DEBUG)
    logging.getLogger("root").setLevel(logging.DEBUG)
    server = serving.make_server(host=flask_host, port=0, app=app, threaded=True)
    port = server.socket.getsockname()[1]
    return server, port


if __name__ == "__main__":
    app.logger.setLevel(logging.DEBUG)
    app.run()
