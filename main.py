import os
import shutil
import time
from typing import List, Optional
from fastapi import FastAPI, Request, Response, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import database
import scanner
import auth
import image_tools

app = FastAPI(title="Analog Mixtape Vault")

# Static files and data paths
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
PHOTOS_DIR = os.path.join(DATA_DIR, "photos")
os.makedirs(PHOTOS_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/photos", StaticFiles(directory=PHOTOS_DIR), name="photos")

# Initialize database on startup
@app.on_event("startup")
def startup_event():
    database.init_db()

# --- Pydantic Models ---
class LoginIn(BaseModel):
    code: str

class GuestPassIn(BaseModel):
    name: str
    pass_code: str
    notes: Optional[str] = None

class ChangePinIn(BaseModel):
    old_pin: str
    new_pin: str

class LocationUpdate(BaseModel):
    shelf_location: str

class TrackIn(BaseModel):
    side: str
    track_num: int
    title: str
    duration_sec: int = 210

class MediaCreate(BaseModel):
    code: str
    media_type: str = "MC"
    artist: str
    album: str
    year: Optional[int] = None
    genre: Optional[str] = None
    shelf_location: Optional[str] = "Koferis 1"
    notes: Optional[str] = None
    photo_url: Optional[str] = None
    tracks: List[TrackIn] = []

class MixtapeItemIn(BaseModel):
    track_id: int
    side: str # 'A' or 'B'
    position: int

class MixtapeCreate(BaseModel):
    title: str
    creator_name: str
    target_media: str = "C60" # C60, C90, C120
    notes: Optional[str] = None
    items: List[MixtapeItemIn] = []

class CropPhotoIn(BaseModel):
    photo_url: str
    box: Optional[List[int]] = None # [x, y, w, h]
    rotation: int = 0
    auto_detect: bool = False
    media_id: Optional[int] = None
    target_slot: Optional[str] = "cover" # cover, tape_a, tape_b

class AutoContourIn(BaseModel):
    photo_url: str
    aspect_ratio: Optional[float] = None


# --- Authentication Endpoints ---

@app.post("/api/auth/login")
def api_auth_login(data: LoginIn, request: Request, response: Response):
    client_ip = request.client.host if request.client else "127.0.0.1"
    forwarded = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
        
    res = auth.authenticate_code(data.code, client_ip)
    # Set persistent cookie
    response.set_cookie(
        key="vault_token",
        value=res["token"],
        max_age=30 * 86400,
        httponly=True,
        samesite="lax"
    )
    return res

@app.get("/api/auth/me")
def api_auth_me(request: Request):
    user = auth.get_current_user_from_req(request)
    if not user:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "role": user.get("role"),
        "name": user.get("name")
    }

@app.post("/api/auth/logout")
def api_auth_logout(response: Response):
    response.delete_cookie("vault_token")
    return {"success": True}

# --- Guest Passes Management (Admin Only) ---

@app.get("/api/guest-passes")
def api_list_guest_passes(request: Request):
    auth.require_admin(request)
    return database.list_guest_passes()

@app.post("/api/guest-passes")
def api_create_guest_pass(data: GuestPassIn, request: Request):
    auth.require_admin(request)
    try:
        pass_id = database.create_guest_pass(data.name, data.pass_code, data.notes)
        return {"success": True, "id": pass_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Kļūda izveidojot paroli: {e}")

@app.post("/api/guest-passes/{pass_id}/toggle")
def api_toggle_guest_pass(pass_id: int, request: Request):
    auth.require_admin(request)
    conn = database.get_db()
    c = conn.cursor()
    c.execute("SELECT is_active FROM guest_passes WHERE id = ?", (pass_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Parole nav atrasta")
    new_state = 0 if row["is_active"] == 1 else 1
    database.toggle_guest_pass(pass_id, new_state)
    return {"success": True, "is_active": new_state}

@app.delete("/api/guest-passes/{pass_id}")
def api_delete_guest_pass(pass_id: int, request: Request):
    auth.require_admin(request)
    database.delete_guest_pass(pass_id)
    return {"success": True}

@app.post("/api/admin/change-pin")
def api_change_pin(data: ChangePinIn, request: Request):
    auth.require_admin(request)
    cfg = auth.get_auth_config()
    if data.old_pin != cfg.get("master_pin", "1987"):
        raise HTTPException(status_code=400, detail="Vecais PIN ir nepareizs!")
    auth.set_master_pin(data.new_pin)
    return {"success": True}

# --- Catalog / Media Endpoints ---

@app.get("/api/next-code")
def api_next_code(request: Request, type: str = "MC"):
    auth.require_admin(request)
    return {"code": database.get_next_code(type)}

@app.get("/api/media")
def api_list_media(request: Request, q: Optional[str] = None, type: Optional[str] = None):
    user = auth.require_auth(request)
    conn = database.get_db()
    cursor = conn.cursor()
    
    query = "SELECT * FROM media WHERE 1=1"
    params = []
    
    if type and type != "ALL":
        query += " AND media_type = ?"
        params.append(type)
        
    if q and q.strip():
        search = f"%{q.strip()}%"
        query += """ AND (
            artist LIKE ? OR album LIKE ? OR genre LIKE ? OR code LIKE ? OR shelf_location LIKE ?
            OR id IN (SELECT media_id FROM tracks WHERE title LIKE ?)
        )"""
        params.extend([search, search, search, search, search, search])
        
    query += " ORDER BY id DESC"
    cursor.execute(query, params)
    media_rows = cursor.fetchall()
    
    result = []
    for m in media_rows:
        m_dict = dict(m)
        cursor.execute("SELECT * FROM tracks WHERE media_id = ? ORDER BY side ASC, track_num ASC", (m["id"],))
        m_dict["tracks"] = [dict(t) for t in cursor.fetchall()]
        
        # Security: Hide internal shelf location and private notes from guests
        if user.get("role") != "admin":
            m_dict["shelf_location"] = "Kolekcijā"
            m_dict["notes"] = None
            
        result.append(m_dict)
        
    conn.close()
    return result

@app.post("/api/media")
def api_create_media(data: MediaCreate, request: Request):
    auth.require_admin(request)
    conn = database.get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO media (code, media_type, artist, album, year, genre, shelf_location, notes, photo_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (data.code, data.media_type, data.artist, data.album, data.year, data.genre, data.shelf_location, data.notes, data.photo_url))
        media_id = cursor.lastrowid
        
        for t in data.tracks:
            cursor.execute("""
                INSERT INTO tracks (media_id, side, track_num, title, duration_sec)
                VALUES (?, ?, ?, ?, ?)
            """, (media_id, t.side, t.track_num, t.title, t.duration_sec))
            
        conn.commit()
        return {"success": True, "id": media_id, "code": data.code}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@app.delete("/api/media/{media_id}")
def api_delete_media(media_id: int, request: Request):
    auth.require_admin(request)
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tracks WHERE media_id = ?", (media_id,))
    cursor.execute("DELETE FROM media WHERE id = ?", (media_id,))
    conn.commit()
    conn.close()
    return {"success": True}

# --- Settings & Scanner Endpoints ---

@app.get("/api/config")
def api_get_config(request: Request):
    auth.require_admin(request)
    cfg = scanner.get_config()
    key = cfg.get("gemini_api_key", "")
    masked = key[:6] + "..." + key[-4:] if len(key) > 10 else ("ir iestatīta" if key else "")
    return {"has_key": bool(key), "masked_key": masked}

@app.post("/api/config")
def api_save_config(request: Request, gemini_api_key: str = Form(...)):
    auth.require_admin(request)
    cfg = scanner.get_config()
    cfg["gemini_api_key"] = gemini_api_key.strip()
    scanner.save_config(cfg)
    return {"success": True}

@app.get("/api/search-album")
def api_search_album(q: str, request: Request):
    auth.require_admin(request)
    res = scanner.search_itunes_album(q)
    if not res:
        raise HTTPException(status_code=404, detail="Albums netika atrasts")
    return res

@app.get("/api/search-albums")
def api_search_albums(q: str, request: Request):
    auth.require_admin(request)
    return scanner.search_itunes_albums_multi(q, limit=6)

@app.get("/api/album-details/{collection_id}")
def api_album_details(collection_id: int, request: Request):
    auth.require_admin(request)
    res = scanner.lookup_itunes_collection(collection_id)
    if not res:
        raise HTTPException(status_code=404, detail="Albuma dziesmas netika atrastas")
    return res

@app.post("/api/scan-photo")
async def api_scan_photo(request: Request, file: UploadFile = File(...)):
    auth.require_admin(request)
    try:
        orig_name = file.filename or "photo.jpg"
        ext = os.path.splitext(orig_name)[1].lower() or ".jpg"
        filename = f"scan_{int(os.times().elapsed * 1000)}{ext}"
        dest_path = os.path.join(PHOTOS_DIR, filename)
        
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        try:
            from PIL import Image
            orig_img = Image.open(dest_path)
            norm_img = image_tools.fix_orientation(orig_img)
            norm_img.save(dest_path, "JPEG", quality=92)
        except Exception:
            pass

        data = scanner.scan_cassette_image(dest_path)
        data["photo_url"] = f"/photos/{filename}"
        return data
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Skanēšanas kļūda: {str(e)}")

@app.post("/api/upload-photo")
async def api_upload_photo(request: Request, file: UploadFile = File(...)):
    auth.require_admin(request)
    try:
        orig_name = file.filename or "cover.jpg"
        ext = os.path.splitext(orig_name)[1].lower() or ".jpg"
        filename = f"cover_{int(time.time() * 1000)}{ext}"
        dest_path = os.path.join(PHOTOS_DIR, filename)
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        try:
            from PIL import Image
            orig_img = Image.open(dest_path)
            norm_img = image_tools.fix_orientation(orig_img)
            norm_img.save(dest_path, "JPEG", quality=92)
        except Exception:
            pass
        return {"success": True, "photo_url": f"/photos/{filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Augšupielādes kļūda: {str(e)}")

@app.post("/api/media/{media_id}/photo")
async def api_update_media_photo(media_id: int, request: Request, file: UploadFile = File(...)):
    auth.require_admin(request)
    try:
        orig_name = file.filename or "cover.jpg"
        ext = os.path.splitext(orig_name)[1].lower() or ".jpg"
        filename = f"cover_{media_id}_{int(time.time() * 1000)}{ext}"
        dest_path = os.path.join(PHOTOS_DIR, filename)
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        try:
            from PIL import Image
            orig_img = Image.open(dest_path)
            norm_img = image_tools.fix_orientation(orig_img)
            norm_img.save(dest_path, "JPEG", quality=92)
        except Exception:
            pass
        photo_url = f"/photos/{filename}"
        
        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE media SET photo_url = ? WHERE id = ?", (photo_url, media_id))
        conn.commit()
        conn.close()
        return {"success": True, "photo_url": photo_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Kļūda saglabājot vāciņu: {str(e)}")

@app.post("/api/media/{media_id}/tape-photo")
async def api_update_media_tape_photo(
    media_id: int,
    request: Request,
    file: UploadFile = File(...),
    side: str = Form("A")
):
    auth.require_admin(request)
    try:
        orig_name = file.filename or "tape.jpg"
        ext = os.path.splitext(orig_name)[1].lower() or ".jpg"
        side_clean = "b" if side.upper() == "B" else "a"
        filename = f"tape_{media_id}_{side_clean}_{int(time.time() * 1000)}{ext}"
        dest_path = os.path.join(PHOTOS_DIR, filename)
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        try:
            from PIL import Image
            orig_img = Image.open(dest_path)
            norm_img = image_tools.fix_orientation(orig_img)
            norm_img.save(dest_path, "JPEG", quality=92)
        except Exception:
            pass
        photo_url = f"/photos/{filename}"
        
        column = "tape_photo_b" if side_clean == "b" else "tape_photo_a"
        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute(f"UPDATE media SET {column} = ? WHERE id = ?", (photo_url, media_id))
        conn.commit()
        conn.close()
        return {"success": True, "side": side_clean.upper(), "photo_url": photo_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Kļūda saglabājot kasetes foto: {str(e)}")

@app.delete("/api/media/{media_id}/tape-photo")
def api_delete_media_tape_photo(media_id: int, request: Request, side: str = "A"):
    auth.require_admin(request)
    side_clean = "b" if side.upper() == "B" else "a"
    column = "tape_photo_b" if side_clean == "b" else "tape_photo_a"
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute(f"UPDATE media SET {column} = NULL WHERE id = ?", (media_id,))
    conn.commit()
    conn.close()
    return {"success": True, "side": side_clean.upper()}


@app.post("/api/auto-contour")
def api_auto_contour(data: AutoContourIn, request: Request):
    auth.require_admin(request)
    photo_rel = data.photo_url.lstrip("/")
    if photo_rel.startswith("photos/"):
        photo_rel = photo_rel[len("photos/"):]
    file_path = os.path.join(PHOTOS_DIR, photo_rel)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Attēls nav atrasts")
    try:
        from PIL import Image
        img = Image.open(file_path)
        img = image_tools.fix_orientation(img)
        w, h = img.size
        box = image_tools.auto_detect_object_bounds(img, target_aspect_ratio=data.aspect_ratio)
        return {
            "success": True,
            "box": {"x": box[0], "y": box[1], "w": box[2], "h": box[3]},
            "image_size": {"w": w, "h": h}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Kontūras analīzes kļūda: {str(e)}")

@app.post("/api/crop-photo")
def api_crop_photo(data: CropPhotoIn, request: Request):
    auth.require_admin(request)
    photo_rel = data.photo_url.lstrip("/")
    if photo_rel.startswith("photos/"):
        photo_rel = photo_rel[len("photos/"):]
    file_path = os.path.join(PHOTOS_DIR, photo_rel)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Attēls nav atrasts")
    try:
        box_tuple = None
        if data.auto_detect:
            from PIL import Image
            img = Image.open(file_path)
            img = image_tools.fix_orientation(img)
            box_tuple = image_tools.auto_detect_object_bounds(img)
        elif data.box and len(data.box) == 4:
            box_tuple = (int(data.box[0]), int(data.box[1]), int(data.box[2]), int(data.box[3]))
            
        prefix = f"cover_crop_{data.media_id}" if data.media_id else "cover_crop"
        new_filename = image_tools.crop_and_save_image(
            input_path=file_path,
            output_dir=PHOTOS_DIR,
            box=box_tuple,
            rotation=data.rotation,
            prefix=prefix
        )
        new_photo_url = f"/photos/{new_filename}"
        
        if data.media_id:
            col = "tape_photo_a" if data.target_slot == "tape_a" else ("tape_photo_b" if data.target_slot == "tape_b" else "photo_url")
            conn = database.get_db()
            cursor = conn.cursor()
            cursor.execute(f"UPDATE media SET {col} = ? WHERE id = ?", (new_photo_url, data.media_id))
            conn.commit()
            conn.close()
            
        return {
            "success": True,
            "photo_url": new_photo_url,
            "box": box_tuple
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Apgriešanas kļūda: {str(e)}")

@app.patch("/api/media/{media_id}/location")
@app.post("/api/media/{media_id}/location")
def api_update_media_location(media_id: int, data: LocationUpdate, request: Request):
    auth.require_admin(request)
    loc = (data.shelf_location or "").strip()
    if not loc:
        loc = "Plaukts"
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE media SET shelf_location = ? WHERE id = ?", (loc, media_id))
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Kasete netika atrasta")
    conn.commit()
    conn.close()
    return {"success": True, "id": media_id, "shelf_location": loc}

# --- Mixtapes Endpoints ---

@app.get("/api/mixtapes")
def api_list_mixtapes(request: Request):
    auth.require_admin(request)
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.*, COUNT(mi.id) as track_count,
               COALESCE(SUM(t.duration_sec), 0) as total_duration_sec
        FROM mixtapes m
        LEFT JOIN mixtape_items mi ON m.id = mi.mixtape_id
        LEFT JOIN tracks t ON mi.track_id = t.id
        GROUP BY m.id
        ORDER BY m.id DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/mixtapes/{mixtape_id}")
def api_get_mixtape(mixtape_id: int, request: Request):
    auth.require_admin(request)
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM mixtapes WHERE id = ?", (mixtape_id,))
    mix = cursor.fetchone()
    if not mix:
        conn.close()
        raise HTTPException(status_code=404, detail="Mixtape not found")
        
    mix_dict = dict(mix)
    
    # Get items with track and media info (essential for dubbing guide)
    cursor.execute("""
        SELECT mi.id as item_id, mi.side as mix_side, mi.position,
               t.id as track_id, t.title as track_title, t.duration_sec, t.side as orig_side, t.track_num as orig_track_num,
               m.code as media_code, m.media_type, m.artist, m.album, m.shelf_location
        FROM mixtape_items mi
        JOIN tracks t ON mi.track_id = t.id
        JOIN media m ON t.media_id = m.id
        WHERE mi.mixtape_id = ?
        ORDER BY mi.side ASC, mi.position ASC
    """, (mixtape_id,))
    
    items = [dict(r) for r in cursor.fetchall()]
    mix_dict["items_a"] = [i for i in items if i["mix_side"] == "A"]
    mix_dict["items_b"] = [i for i in items if i["mix_side"] == "B"]
    
    # Calculate durations
    dur_a = sum(i["duration_sec"] for i in mix_dict["items_a"])
    dur_b = sum(i["duration_sec"] for i in mix_dict["items_b"])
    mix_dict["duration_a_sec"] = dur_a
    mix_dict["duration_b_sec"] = dur_b
    mix_dict["total_duration_sec"] = dur_a + dur_b
    
    conn.close()
    return mix_dict

@app.post("/api/mixtapes")
def api_create_mixtape(data: MixtapeCreate, request: Request):
    user = auth.require_auth(request)
    creator = data.creator_name.strip()
    if not creator:
        creator = user.get("name", "Draugs")
        
    conn = database.get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO mixtapes (title, creator_name, target_media, notes)
            VALUES (?, ?, ?, ?)
        """, (data.title, creator, data.target_media, data.notes))
        mixtape_id = cursor.lastrowid
        
        for item in data.items:
            cursor.execute("""
                INSERT INTO mixtape_items (mixtape_id, track_id, side, position)
                VALUES (?, ?, ?, ?)
            """, (mixtape_id, item.track_id, item.side, item.position))
            
        conn.commit()
        return {"success": True, "id": mixtape_id}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@app.patch("/api/mixtapes/{mixtape_id}/status")
def api_update_mixtape_status(mixtape_id: int, request: Request, status: str = Form(...)):
    auth.require_admin(request)
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE mixtapes SET status = ? WHERE id = ?", (status, mixtape_id))
    conn.commit()
    conn.close()
    return {"success": True}

@app.delete("/api/mixtapes/{mixtape_id}")
def api_delete_mixtape(mixtape_id: int, request: Request):
    auth.require_admin(request)
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM mixtape_items WHERE mixtape_id = ?", (mixtape_id,))
    cursor.execute("DELETE FROM mixtapes WHERE id = ?", (mixtape_id,))
    conn.commit()
    conn.close()
    return {"success": True}

# --- Printable J-Card Inlay ---

@app.get("/jcard/{mixtape_id}")
def generate_jcard_html(mixtape_id: int, request: Request):
    auth.require_admin(request)
    mix = api_get_mixtape(mixtape_id, request)
    
    def fmt(sec):
        m = sec // 60
        s = sec % 60
        return f"{m}:{s:02d}"

    tracks_a_html = "".join([f"<li><span class='num'>{i+1}.</span> <span class='title'>{t['artist']} - {t['track_title']}</span> <span class='time'>({fmt(t['duration_sec'])})</span></li>" for i, t in enumerate(mix['items_a'])])
    tracks_b_html = "".join([f"<li><span class='num'>{i+1}.</span> <span class='title'>{t['artist']} - {t['track_title']}</span> <span class='time'>({fmt(t['duration_sec'])})</span></li>" for i, t in enumerate(mix['items_b'])])

    html_content = f"""
    <!DOCTYPE html>
    <html lang="lv">
    <head>
      <meta charset="UTF-8">
      <title>J-Card: {mix['title']}</title>
      <style>
        @page {{ size: A4; margin: 10mm; }}
        body {{
          font-family: 'Courier New', Courier, monospace;
          background: #e5e5e5;
          margin: 0;
          padding: 20px;
          display: flex;
          flex-direction: column;
          align-items: center;
        }}
        .no-print {{
          margin-bottom: 20px;
          text-align: center;
        }}
        .btn-print {{
          background: #d97706;
          color: #fff;
          border: none;
          padding: 10px 20px;
          font-weight: bold;
          cursor: pointer;
          border-radius: 6px;
          font-size: 14px;
        }}
        .jcard-container {{
          display: flex;
          background: #fff;
          border: 1px dashed #333;
          box-shadow: 0 4px 10px rgba(0,0,0,0.15);
          width: 206mm;
          height: 102mm;
          overflow: hidden;
          box-sizing: border-box;
          color: #000;
        }}
        .panel-front {{
          width: 65mm;
          height: 102mm;
          border-right: 1px dashed #777;
          box-sizing: border-box;
          padding: 8mm 6mm;
          display: flex;
          flex-direction: column;
          justify-content: space-between;
          background: #faf8f5;
        }}
        .front-header {{
          border-bottom: 2px solid #000;
          padding-bottom: 4mm;
        }}
        .front-brand {{
          font-size: 10px;
          font-weight: bold;
          letter-spacing: 2px;
          color: #666;
        }}
        .front-title {{
          font-size: 16px;
          font-weight: 900;
          margin: 4mm 0 2mm 0;
          line-height: 1.2;
          text-transform: uppercase;
        }}
        .front-creator {{
          font-size: 11px;
          color: #333;
        }}
        .front-footer {{
          border-top: 1px solid #999;
          padding-top: 3mm;
          display: flex;
          justify-content: space-between;
          font-size: 10px;
          font-weight: bold;
        }}
        .panel-spine {{
          width: 13mm;
          height: 102mm;
          border-right: 1px dashed #777;
          box-sizing: border-box;
          padding: 4mm 2mm;
          display: flex;
          flex-direction: column;
          justify-content: space-between;
          align-items: center;
          background: #f0ede6;
          writing-mode: vertical-rl;
          text-orientation: mixed;
          font-size: 11px;
          font-weight: bold;
          letter-spacing: 1px;
          text-transform: uppercase;
        }}
        .panel-flap {{
          width: 128mm;
          height: 102mm;
          box-sizing: border-box;
          padding: 4mm 6mm;
          display: flex;
          gap: 6mm;
          background: #fff;
          font-size: 8.5px;
          line-height: 1.25;
        }}
        .flap-side {{
          flex: 1;
          display: flex;
          flex-direction: column;
        }}
        .flap-side h4 {{
          margin: 0 0 2mm 0;
          font-size: 10px;
          border-bottom: 1.5px solid #000;
          padding-bottom: 1mm;
          display: flex;
          justify-content: space-between;
        }}
        ul {{
          list-style: none;
          padding: 0;
          margin: 0;
        }}
        li {{
          display: flex;
          justify-content: space-between;
          margin-bottom: 1.2mm;
        }}
        .num {{ font-weight: bold; margin-right: 3px; }}
        .title {{ flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding-right: 4px; }}
        .time {{ color: #444; font-size: 8px; }}
        @media print {{
          body {{ background: #fff; padding: 0; }}
          .no-print {{ display: none; }}
          .jcard-container {{ box-shadow: none; }}
        }}
      </style>
    </head>
    <body>
      <div class="no-print">
        <button class="btn-print" onclick="window.print()">🖨️ Izdrukāt J-Card (100% mērogs)</button>
        <p style="font-size: 11px; color: #555; margin-top: 5px;">Iestatījumos norādi mērogu 100% (Actual Size), lai izmērs atbilstu kasetes kastītei (102mm x 206mm).</p>
      </div>

      <div class="jcard-container">
        <div class="panel-front">
          <div class="front-header">
            <div class="front-brand">ANALOG VAULT • TAPE DUB</div>
            <div class="front-title">{mix['title']}</div>
            <div class="front-creator">Izlase: {mix['creator_name']}</div>
          </div>
          <div class="front-footer">
            <span>{mix['target_media']}</span>
            <span>{fmt(mix['total_duration_sec'])}</span>
          </div>
        </div>

        <div class="panel-spine">
          <span>{mix['title']}</span>
          <span>{mix['target_media']} • {mix['creator_name']}</span>
        </div>

        <div class="panel-flap">
          <div class="flap-side">
            <h4><span>PUSE A</span> <span>{fmt(mix['duration_a_sec'])}</span></h4>
            <ul>{tracks_a_html}</ul>
          </div>
          <div class="flap-side">
            <h4><span>PUSE B</span> <span>{fmt(mix['duration_b_sec'])}</span></h4>
            <ul>{tracks_b_html}</ul>
          </div>
        </div>
      </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.get("/")
def serve_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
