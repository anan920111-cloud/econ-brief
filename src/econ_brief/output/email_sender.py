"""Email sender via SMTP."""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import date

logger = logging.getLogger(__name__)


class EmailSender:
    """Send HTML emails via SMTP (Brevo, Gmail, or any SMTP provider)."""

    def __init__(self, config: dict):
        """
        Args:
            config: Dict with keys:
                host: SMTP server hostname
                port: SMTP port (usually 587 for TLS)
                username: SMTP login
                password: SMTP password / API key
                from_addr: Sender email address
                to_addrs: Comma-separated recipient email(s)
        """
        self.host = config["host"]
        self.port = int(config.get("port", 587))
        self.username = config["username"]
        self.password = config["password"]
        self.from_addr = config["from_addr"]
        self.to_addrs = [
            addr.strip()
            for addr in config.get("to_addrs", "").split(",")
            if addr.strip()
        ]

        if not self.to_addrs:
            logger.warning("No recipients configured; email will not be sent")

    def send(self, html_content: str, today: date | None = None) -> bool:
        """Send the briefing email.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not self.to_addrs:
            logger.warning("Skipping email: no recipients")
            return False

        today = today or date.today()
        subject = (
            f"Econ Brief {today.isoformat()} | "
            f"经济学每日科研简报"
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.to_addrs)
        msg["Message-ID"] = f"<econ-brief-{today.isoformat()}@local>"
        msg["Date"] = smtplib.email.utils.formatdate(localtime=True)

        # Attach HTML
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        try:
            with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.send_message(msg)
            logger.info(
                "Email sent to %d recipients via %s",
                len(self.to_addrs),
                self.host,
            )
            return True
        except smtplib.SMTPAuthenticationError as e:
            logger.error("SMTP authentication failed: %s", e)
            return False
        except smtplib.SMTPException as e:
            logger.error("SMTP error: %s", e)
            return False
        except OSError as e:
            logger.error("Network error sending email: %s", e)
            return False
