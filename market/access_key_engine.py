import json
import secrets
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path


class AccessKeyEngine:
    """Simple local access-key system for MarketOps.

    Plain English: this file creates, stores, redeems, and checks keys.
    It does not talk to Stripe yet. It saves everything locally in data/access_keys.json.
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
            expires_at = None
            days = 0
        else:
            expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

        key = self._generate_key(plan)
        data = self._read_data()
        data.setdefault("keys", {})
        data["keys"][key] = {
            "key": key,
            "plan": plan,
            "days": days,
            "active": True,
            "created_by": str(created_by),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": expires_at,
            "redeemed_by": None,
            "redeemed_by_name": None,
            "redeemed_at": None,
            "revoked": False,
        }
        self._write_data(data)
        return data["keys"][key]

    def redeem_key(self, key, user_id, username):
        clean_key = self._clean_key(key)
        if not clean_key:
            return {"ok": False, "message": "Use `!redeem YOUR-KEY-HERE`."}

        data = self._read_data()
        record = data.get("keys", {}).get(clean_key)
        if not record:
            return {"ok": False, "message": "That MarketOps key was not found."}

        if record.get("revoked") or not record.get("active", True):
            return {"ok": False, "message": "That MarketOps key is disabled."}

        existing_user = record.get("redeemed_by")
        if existing_user and str(existing_user) != str(user_id):
            return {"ok": False, "message": "That MarketOps key was already redeemed by another user."}

        if self._is_expired(record):
            return {"ok": False, "message": "That MarketOps key is expired."}

        record["redeemed_by"] = str(user_id)
        record["redeemed_by_name"] = username
        record["redeemed_at"] = record.get("redeemed_at") or datetime.now(timezone.utc).isoformat()
        data["keys"][clean_key] = record
        self._write_data(data)

        return {"ok": True, "message": f"Access granted. Plan: {record.get('plan', 'unknown')}.", "record": record}

    def access_status(self, user_id):
        records = self._user_records(user_id)
        active = [record for record in records if self._record_is_active(record)]

        if active:
            record = self._best_record(active)
            return {
                "ok": True,
                "has_access": True,
                "message": "Active MarketOps access found.",
                "record": record,
            }

        expired = [record for record in records if self._is_expired(record)]
        if expired:
            return {
                "ok": False,
                "has_access": False,
                "message": "Your MarketOps key is expired. Redeem a new key.",
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
            if not record.get("redeemed_by"):
                continue
            rows.append(record)
        rows.sort(key=lambda item: item.get("redeemed_at") or "", reverse=True)
        return rows

    def format_expiration(self, record):
        if not record:
            return "No active key"
        expires_at = record.get("expires_at")
        if not expires_at:
            return "Lifetime"
        try:
            parsed = datetime.fromisoformat(expires_at)
            remaining = parsed - datetime.now(timezone.utc)
            if remaining.total_seconds() <= 0:
                return "Expired"
            return f"{remaining.days} day(s) left"
        except Exception:
            return "Unknown"

    def _record_is_active(self, record):
        if record.get("revoked") or not record.get("active", True):
            return False
        if not record.get("redeemed_by"):
            return False
        return not self._is_expired(record)

    def _is_expired(self, record):
        expires_at = record.get("expires_at")
        if not expires_at:
            return False
        try:
            parsed = datetime.fromisoformat(expires_at)
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
        lifetime = [record for record in records if not record.get("expires_at")]
        if lifetime:
            return lifetime[0]
        return sorted(records, key=lambda item: item.get("expires_at") or "", reverse=True)[0]

    def _generate_key(self, plan):
        prefix = {
            "beta": "BETA",
            "trial": "TRIAL",
            "monthly": "MONTHLY",
            "lifetime": "LIFE",
            "admin": "ADMIN",
        }.get(plan, "BETA")
        alphabet = string.ascii_uppercase + string.digits
        part1 = "".join(secrets.choice(alphabet) for _ in range(4))
        part2 = "".join(secrets.choice(alphabet) for _ in range(4))
        part3 = "".join(secrets.choice(alphabet) for _ in range(4))
        return f"{prefix}-{part1}-{part2}-{part3}"

    def _clean_key(self, key):
        return (key or "").strip().upper()

    def _read_data(self):
        if not self.KEY_FILE.exists():
            return {"keys": {}}
        try:
            with self.KEY_FILE.open("r", encoding="utf-8") as file:
                data = json.load(file)
                return data if isinstance(data, dict) else {"keys": {}}
        except Exception:
            return {"keys": {}}

    def _write_data(self, data):
        self.KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with self.KEY_FILE.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)
