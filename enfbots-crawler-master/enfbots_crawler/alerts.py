import logging
import os.path
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from enfbots_crawler import Config

logger = logging.getLogger("enfbots_crawler")


def _send_email(
    to: str, subject: str, email_message: str, attachment_location: Optional[str] = None
) -> None:
    msg = MIMEMultipart()
    msg["From"] = Config().ALERT_EMAIL_USERNAME
    msg["To"] = to
    msg["Subject"] = subject

    msg.attach(MIMEText(email_message, "plain"))

    if attachment_location:
        filename = os.path.basename(attachment_location)
        attachment = open(attachment_location, "rb")
        part = MIMEBase("application", "octet-stream")
        part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment; filename= %s" % filename)
        msg.attach(part)

    try:
        host, port = Config().ALERT_EMAIL_SERVER.split(":")
        server = smtplib.SMTP(host, int(port))
        server.ehlo()
        server.starttls()
        server.login(Config().ALERT_EMAIL_USERNAME, Config().ALERT_EMAIL_PASSWORD)
        text = msg.as_string()
        server.sendmail(Config().ALERT_EMAIL_USERNAME, to, text)
        logging.info("Alert emails sent")
        server.quit()
    except smtplib.SMTPException:
        logging.exception("SMTP server connection error")


def send_alert(subject: str, message: str) -> None:
    for email in Config().ALERT_EMAIL_RECIPIENTS.split(","):
        _send_email(email, subject, message)
