import json
import secrets
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path


class AccessKeyEngine:
    """Simple local access-key system for MarketOps.

    Plain English: this file creates, stores, redeems, renews, and checks keys.
    Payment is handled manually by Eduardo outside the bot for now.
    """

    KEY_FILE = Path("data/access_keys.json")

    def create_key(self, plan="beta", days=30, created_by="admin"):
        plan = (plan or "beta").strip().lower()
        if plan not in ("beta", "trial", "monthly", "lifetime", "admin"):
            plan = "beta"

        try:
            days = int(days)
        except (TypeError, ValueError):
            days = 30

        if plan == "lifetime" or days <= 0:
            days = 0

        key = self._generate_key(plan)
        data = self._read_data()
        data.setdefault("keys", {})
        data.setdefault("renewals", {})
        data["keys"][key] = {
            "key": key,
            "plan": plan,
            "days": days,
            "active": True,
            "created_by": str(created_by),
            "created_at": self._now_iso(),
            "redeemed_by": None,
            "redeemed_by_name": None,
            "redeemed_at": None,
            "access_expires_at": None,
            "revoked": False,
            "used_for": None,
        }
        self._write_data(data)
        return data["keys"][key]

    def redeem_key(self, key, user_id, username):
        clean_key = self._clean_key(key)
        if not clean_key:
            return {"ok": False, "message": "Use `!redeem YOUR-KEY-HERE`."}

        data = self._read_data()
        record = data.get("keys", {}).get(clean_key)
        validation = self._validate_unused_key(record, clean_key)
        if not validation["ok"]:
            return validation

        record["redeemed_by"] = str(user_id)
        record["redeemed_by_name"] = username
        record["redeemed_at"] = self._now_iso()
        record["access_expires_at"] = self._new_access_expiration(record)
        record["used_for"] = "new_access"
        data["keys"][clean_key] = record
        self._write_data(data)

        return {"ok": True, "message": f"Access granted. Plan: {record.get('plan', 'unknown')}.", "record": record}

    def request_renewal(self, key, user_id, username):
        clean_key = self._clean_key(key)
        if not clean_key:
            return {"ok": False, "message": "Use `!renew YOUR-KEY-HERE`."}

        data = self._read_data()
        data.setdefault("renewals", {})
        record = data.get("keys", {}).get(clean_key)
        validation = self._validate_unused_key(record, clean_key)
        if not validation["ok"]:
            return validation

        active_status = self.access_status(user_id)
        if not active_status.get("has_access"):
            return {
                "ok": False,
                "message": "No active access found. Use `!redeem KEY-HERE` for first-time access instead of renew.",
            }

        request_id = self._generate_request_id()
        request = {
            "request_id": request_id,
            "key": clean_key,
            "plan": record.get("plan", "unknown"),
            "days": record.get("days", 0),
            "user_id": str(user_id),
            "username": username,
            "status": "pending",
            "requested_at": self._now_iso(),
            "approved_by": None,
            "approved_at": None,
            "denied_by": None,
            "denied_at": None,
        }
        data["renewals"][request_id] = request
        self._write_data(data)
        return {
            "ok": True,
            "message": "Renewal request sent. Eduardo/admin must confirm payment and approve it.",
            "request": request,
            "record": record,
        }

    def approve_renewal(self, request_id, approved_by="admin"):
        clean_id = (request_id or "").strip().upper()
        if not clean_id:
            return {"ok": False, "message": "Use `!approverenew REQUEST-ID`."}

        data = self._read_data()
        request = data.get("renewals", {}).get(clean_id)
        if not request:
            return {"ok": False, "message": "Renewal request not found."}
        if request.get("status") != "pending":
            return {"ok": False, "message": f"That renewal is already {request.get('status')}."}

        key = request.get("key")
        record = data.get("keys", {}).get(key)
        validation = self._validate_unused_key(record, key)
        if not validation["ok"]:
            request["status"] = "blocked"
            data["renewals"][clean_id] = request
            self._write_data(data)
            return validation

        user_id = request.get("user_id")
        username = request.get("username", "Unknown")
        current_access = self.access_status(user_id).get("record")

        record["redeemed_by"] = str(user_id)
        record["redeemed_by_name"] = username
        record["redeemed_at"] = self._now_iso()
        record["access_expires_at"] = self._renewed_access_expiration(record, current_access)
        record["used_for"] = "renewal"
        record["renewal_request_id"] = clean_id

        request["status"] = "approved"
        request["approved_by"] = str(approved_by)
        request["approved_at"] = self._now_iso()

        data["keys"][key] = record
        data["renewals"][clean_id] = request
        self._write_data(data)

        return {
            "ok": True,
            "message": f"Renewal approved for {username}.",
            "request": request,
            "record": record,
        }

    def deny_renewal(self, request_id, denied_by="admin"):
        clean_id = (request_id or "").strip().upper()
        data = self._read_data()
        request = data.get("renewals", {}).get(clean_id)
        if not request:
            return {"ok": False, "message": "Renewal request not found."}
        if request.get("status") != "pending":
            return {"ok": False, "message": f"That renewal is already {request.get('status')}."}
        request["status"] = "denied"
        request["denied_by"] = str(denied_by)
        request["denied_at"] = self._now_iso()
        data["renewals"][clean_id] = request
        self._write_data(data)
        return {"ok": True, "message": f"Renewal {clean_id} denied.", "request": request}

    def pending_renewals(self):
        data = self._read_data()
        rows = [item for item in data.get("renewals", {}).values() if item.get("status") == "pending"]
        rows.sort(key=lambda item: item.get("requested_at") or "", reverse=True)
        return rows

    def access_status(self, user_id):
        records = self._user_records(user_id)
        active = [record for record in records if self._record_is_active(record)]

        if active:
            record = self._best_record(active)
            return {"ok": True, "has_access": True, "message": "Active MarketOps access found.", "record": record}

        expired = [record for record in records if self._is_expired(record)]
        if expired:
            return {
                "ok": False,
                "has_access": False,
                "message": "Your MarketOps key is expired. Buy/request a renewal key, then use `!renew KEY-HERE`.",
                "record": self._best_record(expired),
            }

        return {
            "ok": False,
            "has_access": False,
            "message": "No active MarketOps key found. Use `!redeem YOUR-KEY-HERE`.",
            "record": None,
        }

    def user_has_access(self, user_id):
        return self.access_status(user_id).get("has_access", False)

    def revoke_key(self, key):
        clean_key = self._clean_key(key)
        data = self._read_data()
        record = data.get("keys", {}).get(clean_key)
        if not record:
            return {"ok": False, "message": "Key not found."}
        record["revoked"] = True
        record["active"] = False
        data["keys"][clean_key] = record
        self._write_data(data)
        return {"ok": True, "message": f"Revoked `{clean_key}`.", "record": record}

    def list_users(self):
        data = self._read_data()
        rows = []
        for record in data.get("keys", {}).values():
            if record.get("redeemed_by"):
                rows.append(record)
        rows.sort(key=lambda item: item.get("redeemed_at") or "", reverse=True)
        return rows

    def format_expiration(self, record):
        if not record:
            return "No active key"
        if record.get("plan") == "lifetime" or not record.get("access_expires_at"):
            return "Lifetime"
        try:
            parsed = datetime.fromisoformat(record.get("access_expires_at"))
            remaining = parsed - datetime.now(timezone.utc)
            if remaining.total_seconds() <= 0:
                return "Expired"
            return f"{remaining.days} day(s) left"
        except Exception:
            return "Unknown"

    def _validate_unused_key(self, record, clean_key):
        if not record:
            return {"ok": False, "message": "That MarketOps key was not found."}
        if record.get("revoked") or not record.get("active", True):
            return {"ok": False, "message": "That MarketOps key is disabled."}
        if record.get("redeemed_by"):
            return {"ok": False, "message": "That MarketOps key was already used."}
        return {"ok": True}

    def _new_access_expiration(self, record):
        if record.get("plan") == "lifetime" or int(record.get("days") or 0) <= 0:
            return None
        return (datetime.now(timezone.utc) + timedelta(days=int(record.get("days") or 30))).isoformat()

    def _renewed_access_expiration(self, record, current_access):
        if record.get("plan") == "lifetime" or int(record.get("days") or 0) <= 0:
            return None

        days = int(record.get("days") or 30)
        start = datetime.now(timezone.utc)
        if current_access and current_access.get("access_expires_at"):
            try:
                current_expiration = datetime.fromisoformat(current_access.get("access_expires_at"))
                if current_expiration > start:
                    start = current_expiration
            except Exception:
                pass
        return (start + timedelta(days=days)).isoformat()

    def _record_is_active(self, record):
        if record.get("revoked") or not record.get("active", True):
            return False
        if not record.get("redeemed_by"):
            return False
        return not self._is_expired(record)

    def _is_expired(self, record):
        if record.get("plan") == "lifetime" or not record.get("access_expires_at"):
            return False
        try:
            parsed = datetime.fromisoformat(record.get("access_expires_at"))
            return datetime.now(timezone.utc) >= parsed
        except Exception:
            return False

    def _user_records(self, user_id):
        data = self._read_data()
        target = str(user_id)
        records = []
        for record in data.get("keys", {}).values():
            if str(record.get("redeemed_by")) == target:
                records.append(record)
        return records

    def _best_record(self, records):
        lifetime = [record for record in records if record.get("plan") == "lifetime" or not record.get("access_expires_at")]
        if lifetime:
            return lifetime[0]
        return sorted(records, key=lambda item: item.get("access_expires_at") or "", reverse=True)[0]

    def _generate_key(self, plan):
        prefix = {"beta": "BETA", "trial": "TRIAL", "monthly": "MONTHLY", "lifetime": "LIFE", "admin": "ADMIN"}.get(plan, "BETA")
        alphabet = string.ascii_uppercase + string.digits
        return f"{prefix}-{self._random_part(alphabet)}-{self._random_part(alphabet)}-{self._random_part(alphabet)}"

    def _generate_request_id(self):
        alphabet = string.ascii_uppercase + string.digits
        return f"RENEW-{self._random_part(alphabet)}-{self._random_part(alphabet)}"

    def _random_part(self, alphabet):
        return "".join(secrets.choice(alphabet) for _ in range(4))

    def _clean_key(self, key):
        return (key or "").strip().upper()

    def _now_iso(self):
        return datetime.now(timezone.utc).isoformat()

    def _read_data(self):
        if not self.KEY_FILE.exists():
            return {"keys": {}, "renewals": {}}
        try:
            with self.KEY_FILE.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except Exception:
            return {"keys": {}, "renewals": {}}
        if not isinstance(data, dict):
            return {"keys": {}, "renewals": {}}
        data.setdefault("keys", {})
        data.setdefault("renewals", {})
        return data

    def _write_data(self, data):
        self.KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with self.KEY_FILE.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)
