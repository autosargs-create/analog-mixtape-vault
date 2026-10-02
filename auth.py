import os
import hmac
import hashlib
import json
import base64
import time
import secrets
from typing import Optional, Dict, Any
from fastapi import Request, HTTPException, Depends
import database
import scanner

CONFIG_PATH = os.path.join(os.getenv("DATA_DIR", "data"), "config.json")

# In-memory rate limiting against brute force: {ip: [timestamp, ...]}
FAILED_ATTEMPTS: Dict[str, list] = {}
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 60

def get_auth_config() -> Dict[str, Any]:
    cfg = scanner.get_config()
    changed = False
    if "master_pin" not in cfg:
        cfg["master_pin"] = "1987" # Default master PIN
        changed = True
    if "jwt_secret" not in cfg:
        cfg["jwt_secret"] = secrets.token_hex(32)
        changed = True
    if changed:
        scanner.save_config(cfg)
    return cfg

def set_master_pin(new_pin: str):
    cfg = scanner.get_config()
    cfg["master_pin"] = str(new_pin).strip()
    scanner.save_config(cfg)

def check_rate_limit(client_ip: str):
    now = time.time()
    attempts = FAILED_ATTEMPTS.get(client_ip, [])
    # Filter attempts in last LOCKOUT_SECONDS
    recent = [t for t in attempts if now - t < LOCKOUT_SECONDS]
    FAILED_ATTEMPTS[client_ip] = recent
    if len(recent) >= MAX_ATTEMPTS:
        remaining = int(LOCKOUT_SECONDS - (now - recent[0]))
        raise HTTPException(
            status_code=429,
            detail=f"Pārāk daudz neveiksmīgu mēģinājumu! Drošības dēļ pieeja bloķēta uz {remaining} sekundēm."
        )

def record_failed_attempt(client_ip: str):
    now = time.time()
    attempts = FAILED_ATTEMPTS.get(client_ip, [])
    attempts.append(now)
    FAILED_ATTEMPTS[client_ip] = attempts

def reset_failed_attempts(client_ip: str):
    if client_ip in FAILED_ATTEMPTS:
        del FAILED_ATTEMPTS[client_ip]

def create_session_token(role: str, name: str) -> str:
    cfg = get_auth_config()
    secret = cfg["jwt_secret"].encode("utf-8")
    payload = {
        "role": role, # "admin" or "guest"
        "name": name,
        "exp": int(time.time()) + (30 * 86400) # 30 days
    }
    b64_payload = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
    signature = hmac.new(secret, b64_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{b64_payload}.{signature}"

def verify_session_token(token: str) -> Optional[Dict[str, Any]]:
    if not token or "." not in token:
        return None
    try:
        b64_payload, signature = token.split(".", 1)
        cfg = get_auth_config()
        secret = cfg["jwt_secret"].encode("utf-8")
        expected_sig = hmac.new(secret, b64_payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return None
            
        # Add padding back if necessary
        padded = b64_payload + "=" * (-len(b64_payload) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8"))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception as e:
        return None

def authenticate_code(code: str, client_ip: str) -> Dict[str, Any]:
    check_rate_limit(client_ip)
    cleaned = code.strip()
    if not cleaned:
        record_failed_attempt(client_ip)
        raise HTTPException(status_code=401, detail="Lūdzu ievadi piekļuves kodu vai PIN")
        
    cfg = get_auth_config()
    master_pin = cfg.get("master_pin", "1987")
    
    # 1. Check Master PIN
    if cleaned == master_pin:
        reset_failed_attempts(client_ip)
        token = create_session_token("admin", "Meistars (Jānis)")
        return {
            "success": True,
            "role": "admin",
            "name": "Meistars (Jānis)",
            "token": token
        }
        
    # 2. Check Active Guest Passes
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM guest_passes 
        WHERE pass_code = ? AND is_active = 1
    """, (cleaned,))
    row = cursor.fetchone()
    
    if row:
        cursor.execute("UPDATE guest_passes SET last_used_at = CURRENT_TIMESTAMP WHERE id = ?", (row["id"],))
        conn.commit()
        conn.close()
        reset_failed_attempts(client_ip)
        guest_name = row["name"]
        token = create_session_token("guest", guest_name)
        return {
            "success": True,
            "role": "guest",
            "name": guest_name,
            "token": token
        }
        
    conn.close()
    record_failed_attempt(client_ip)
    raise HTTPException(status_code=401, detail="Nepareizs piekļuves kods vai parole!")

def get_current_user_from_req(request: Request) -> Optional[Dict[str, Any]]:
    # Check Bearer Header or Cookie
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = request.cookies.get("vault_token")
    if not token:
        token = request.query_params.get("token")
    if not token:
        return None
    return verify_session_token(token)

def require_auth(request: Request) -> Dict[str, Any]:
    user = get_current_user_from_req(request)
    if not user:
        raise HTTPException(status_code=401, detail="Pieeja liegta! Nepieciešama autorizācija.")
    return user

def require_admin(request: Request) -> Dict[str, Any]:
    user = require_auth(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Darbība atļauta tikai Meistaram!")
    return user
