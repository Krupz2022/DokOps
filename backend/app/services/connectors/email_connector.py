import aiosmtplib
from email.message import EmailMessage
from typing import Any, Dict
from .base import ConnectorBase


def _sanitize_header(value: str) -> str:
    """Strip CR and LF to prevent email header injection."""
    return value.replace("\r", "").replace("\n", "")


class EmailConnector(ConnectorBase):
    """Email connector via SMTP. config: smtp_host, smtp_port, username, password, from_addr, to_addr, subject, body."""

    @property
    def actions(self) -> list[str]:
        return ["send_email"]

    async def execute(self, config: Dict[str, Any], tool_inputs: Dict[str, Any]) -> Dict[str, Any]:
        smtp_host = config.get("smtp_host", "")
        try:
            smtp_port = int(config.get("smtp_port", 587))
        except (ValueError, TypeError):
            smtp_port = 587
        username = config.get("username", "")
        password = config.get("password", "")
        from_addr = config.get("from_addr", username)
        to_addr = config.get("to_addr", "")
        subject = config.get("subject", tool_inputs.get("subject", "DokOps Alert"))
        body = config.get("body", tool_inputs.get("body", ""))

        if not smtp_host or not to_addr:
            return {"success": False, "error": "smtp_host and to_addr are required", "data": None}

        msg = EmailMessage()
        msg["From"] = _sanitize_header(from_addr)
        msg["To"] = _sanitize_header(to_addr)
        msg["Subject"] = _sanitize_header(subject)
        msg.set_content(body)

        try:
            await aiosmtplib.send(
                msg,
                hostname=smtp_host,
                port=smtp_port,
                username=username,
                password=password,
                start_tls=True,
            )
            return {"success": True, "data": {"sent_to": to_addr}, "error": None}
        except Exception as e:
            return {"success": False, "error": str(e), "data": None}
