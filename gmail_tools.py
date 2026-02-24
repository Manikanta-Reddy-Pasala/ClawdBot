import imaplib
import email
from email.header import decode_header
from collections import Counter
from config import config


def _decode_header_value(value):
    """Decode email header to string."""
    if value is None:
        return ""
    decoded = decode_header(value)
    parts = []
    for part, charset in decoded:
        if isinstance(part, bytes):
            parts.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(part)
    return " ".join(parts)


def _connect():
    """Connect to Gmail via IMAP."""
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
    return mail


def gmail_search(query: str, folder: str = "INBOX", limit: int = 20) -> str:
    """Search emails. Query uses IMAP search syntax or Gmail X-GM-RAW extension."""
    try:
        mail = _connect()
        mail.select(folder, readonly=True)

        # Use Gmail's X-GM-RAW for natural search if it looks like a natural query
        if any(c in query for c in [":", "@", "from", "subject", "is:", "label:"]):
            status, data = mail.search(None, f'X-GM-RAW "{query}"')
        else:
            status, data = mail.search(None, f'X-GM-RAW "{query}"')

        if status != "OK" or not data[0]:
            mail.logout()
            return "No emails found."

        msg_ids = data[0].split()
        # Take the latest N
        msg_ids = msg_ids[-limit:]
        msg_ids.reverse()

        results = []
        for mid in msg_ids:
            status, msg_data = mail.fetch(mid, "(RFC822.HEADER)")
            if status != "OK":
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            sender = _decode_header_value(msg.get("From", ""))
            subject = _decode_header_value(msg.get("Subject", ""))
            date = msg.get("Date", "")
            results.append(f"ID:{mid.decode()} | {date[:22]} | {sender[:40]} | {subject[:60]}")

        mail.logout()
        return f"Found {len(data[0].split())} emails (showing {len(results)}):\n" + "\n".join(results)

    except Exception as e:
        return f"Gmail error: {e}"


def gmail_stats(folder: str = "INBOX") -> str:
    """Get email stats - count by top senders, unread count."""
    try:
        mail = _connect()
        mail.select(folder, readonly=True)

        # Total count
        status, data = mail.search(None, "ALL")
        total = len(data[0].split()) if data[0] else 0

        # Unread count
        status, data = mail.search(None, "UNSEEN")
        unread = len(data[0].split()) if data[0] else 0

        # Top senders (sample last 200 emails)
        status, data = mail.search(None, "ALL")
        all_ids = data[0].split() if data[0] else []
        sample_ids = all_ids[-200:]

        senders = Counter()
        for mid in sample_ids:
            status, msg_data = mail.fetch(mid, "(RFC822.HEADER)")
            if status == "OK":
                msg = email.message_from_bytes(msg_data[0][1])
                sender = _decode_header_value(msg.get("From", "unknown"))
                # Extract just the email address
                if "<" in sender:
                    addr = sender.split("<")[-1].rstrip(">")
                else:
                    addr = sender
                senders[addr] += 1

        mail.logout()

        top = senders.most_common(15)
        sender_lines = "\n".join(f"  {count:3d} | {addr}" for addr, count in top)

        return (
            f"Folder: {folder}\n"
            f"Total: {total} | Unread: {unread}\n\n"
            f"Top senders (from last {len(sample_ids)} emails):\n{sender_lines}"
        )

    except Exception as e:
        return f"Gmail error: {e}"


def gmail_delete(query: str, folder: str = "INBOX", limit: int = 100) -> str:
    """Delete emails matching a query. Moves to Trash."""
    try:
        mail = _connect()
        mail.select(folder)

        status, data = mail.search(None, f'X-GM-RAW "{query}"')
        if status != "OK" or not data[0]:
            mail.logout()
            return "No matching emails found."

        msg_ids = data[0].split()
        to_delete = msg_ids[:limit]

        for mid in to_delete:
            mail.store(mid, "+X-GM-LABELS", "\\Trash")

        mail.logout()
        return f"Moved {len(to_delete)} emails to Trash (of {len(msg_ids)} matching)."

    except Exception as e:
        return f"Gmail error: {e}"


def gmail_bulk_clean(sender_pattern: str, folder: str = "INBOX") -> str:
    """Delete all emails from a sender pattern. E.g. 'noreply@linkedin.com'."""
    try:
        mail = _connect()
        mail.select(folder)

        status, data = mail.search(None, f'FROM "{sender_pattern}"')
        if status != "OK" or not data[0]:
            mail.logout()
            return f"No emails from '{sender_pattern}'."

        msg_ids = data[0].split()
        for mid in msg_ids:
            mail.store(mid, "+X-GM-LABELS", "\\Trash")

        mail.logout()
        return f"Moved {len(msg_ids)} emails from '{sender_pattern}' to Trash."

    except Exception as e:
        return f"Gmail error: {e}"


def gmail_list_folders() -> str:
    """List all Gmail folders/labels."""
    try:
        mail = _connect()
        status, folders = mail.list()
        mail.logout()
        if status != "OK":
            return "Failed to list folders."
        lines = []
        for f in folders:
            decoded = f.decode() if isinstance(f, bytes) else str(f)
            # Extract folder name
            parts = decoded.split('"')
            if len(parts) >= 3:
                lines.append(parts[-2])
        return "Gmail folders:\n" + "\n".join(f"  {f}" for f in lines[:30])
    except Exception as e:
        return f"Gmail error: {e}"
