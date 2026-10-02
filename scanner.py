import os
import re
import json
import urllib.request
import urllib.parse
import subprocess
from typing import Dict, Any, Optional, List

CONFIG_PATH = os.path.join(os.getenv("DATA_DIR", "data"), "config.json")

TAPE_STOP_WORDS = {
    "TDK", "MAXELL", "SONY", "BASF", "AGFA", "FUJI", "RTM", "PHILIPS", "DENON",
    "CHROME", "TYPE", "POSITION", "NORMAL", "HIGH", "BIAS", "EQ", "MIN", "MINUTES",
    "COMPACT", "CASSETTE", "SIDE", "PUSE", "RECORD", "TAPE", "DIGITAL", "AUDIO",
    "STEREO", "DOLBY", "SYSTEM", "HX", "PRO", "NR", "C60", "C90", "C120",
    "C-60", "C-90", "C-120", "IEC", "CRO2", "EXTRA", "SUPER", "DYNAMIC",
    "OUTPUT", "LOW", "NOISE", "FERRIC", "METAL", "ACOUSTIC", "FINE", "PRECISION",
    "RIGID", "MECHANISM", "HI-FI", "HIFI", "AUTO", "REVERSE", "CLEANING",
    "MADE", "IN", "JAPAN", "GERMANY", "USA", "EUROPE", "KOREA"
}

ENGLISH_STOP_WORDS = {
    "THE", "A", "AN", "AND", "OR", "OF", "IN", "ON", "AT", "TO", "FOR", "WITH",
    "FROM", "BY", "ABOUT", "AS", "INTO", "LIKE", "THROUGH", "AFTER", "OVER",
    "BETWEEN", "OUT", "AGAINST", "DURING", "WITHOUT", "BEFORE", "UNDER",
    "AROUND", "AMONG", "THIS", "THAT", "THESE", "THOSE", "IS", "ARE", "WAS", "WERE",
    "NOT", "BUT", "ALL", "SOME", "ANY", "EACH", "EVERY", "MORE", "MOST", "OTHER",
    "SUCH", "NO", "NOR", "TOO", "VERY", "CAN", "WILL", "JUST", "SHOULD", "NOW",
    "BEST", "HITS", "GREATEST", "COLLECTION", "VOL", "VOLUME", "PART"
}

ALL_STOP_WORDS = TAPE_STOP_WORDS.union(ENGLISH_STOP_WORDS)

def get_config() -> Dict[str, Any]:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"gemini_api_key": os.getenv("GEMINI_API_KEY", "")}

def save_config(cfg: Dict[str, Any]):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

def search_itunes_albums_multi(query: str, limit: int = 6) -> List[Dict[str, Any]]:
    """Search iTunes for multiple albums to let user pick the exact one"""
    cleaned_q = query.strip()
    if not cleaned_q or len(cleaned_q) < 2:
        return []
    try:
        url = f"https://itunes.apple.com/search?term={urllib.parse.quote(cleaned_q)}&entity=album&limit={limit}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=5) as res:
            data = json.loads(res.read().decode('utf-8'))
            results = []
            for r in data.get("results", []):
                year = None
                if "releaseDate" in r:
                    try:
                        year = int(r["releaseDate"][:4])
                    except:
                        pass
                results.append({
                    "collection_id": r.get("collectionId"),
                    "artist": r.get("artistName", ""),
                    "album": r.get("collectionName", ""),
                    "year": year,
                    "genre": r.get("primaryGenreName", "Pops / Roks"),
                    "artwork": r.get("artworkUrl100", "").replace("100x100bb", "300x300bb"),
                    "track_count": r.get("trackCount", 0)
                })
            return results
    except Exception as e:
        print(f"iTunes multi search error for '{cleaned_q}':", e)
    return []

def lookup_itunes_collection(collection_id: int) -> Optional[Dict[str, Any]]:
    """Fetch complete tracklist and metadata for a specific iTunes collection ID"""
    try:
        tracks_url = f"https://itunes.apple.com/lookup?id={collection_id}&entity=song"
        req_t = urllib.request.Request(tracks_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req_t, timeout=5) as res_t:
            t_data = json.loads(res_t.read().decode('utf-8'))
            results = t_data.get("results", [])
            if not results:
                return None
                
            album_info = results[0]
            song_results = [r for r in results if r.get("wrapperType") == "track"]
            
            tracks = []
            total_songs = len(song_results)
            half = (total_songs + 1) // 2
            
            for idx, s in enumerate(song_results):
                side = "A" if idx < half else "B"
                track_num = (idx + 1) if side == "A" else (idx - half + 1)
                dur_sec = s.get("trackTimeMillis", 210000) // 1000
                tracks.append({
                    "side": side,
                    "track_num": track_num,
                    "title": s.get("trackName", f"Dziesma {idx+1}"),
                    "duration_sec": dur_sec
                })
                
            year = None
            if "releaseDate" in album_info:
                try:
                    year = int(album_info["releaseDate"][:4])
                except:
                    pass
                    
            return {
                "artist": album_info.get("artistName", ""),
                "album": album_info.get("collectionName", ""),
                "year": year,
                "genre": album_info.get("primaryGenreName", "Pops / Roks"),
                "artwork": album_info.get("artworkUrl100", "").replace("100x100bb", "600x600bb"),
                "tracks": tracks,
                "source": "Auto-Match (iTunes)"
            }
    except Exception as e:
        print(f"iTunes collection lookup error for {collection_id}:", e)
    return None

def search_itunes_album(query: str) -> Optional[Dict[str, Any]]:
    """Single top match with full tracklist"""
    multi = search_itunes_albums_multi(query, limit=1)
    if multi:
        return lookup_itunes_collection(multi[0]["collection_id"])
    return None

def analyze_photo_with_gemini(image_path: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Use Gemini Vision API to extract artist, album, and tracklist from photo"""
    try:
        import base64
        with open(image_path, "rb") as img_f:
            b64_data = base64.b64encode(img_f.read()).decode("utf-8")
            
        ext = os.path.splitext(image_path)[1].lower()
        mime_type = "image/png" if ext == ".png" else "image/jpeg"
        
        prompt = """Look at this audio cassette, vinyl record, or tape J-card/sleeve/cover.
Extract the album artist, album title, release year, genre, and complete tracklist with Side A and Side B tracks.
Respond ONLY with a valid JSON object in this exact schema (no markdown fences, no backticks, no comments):
{
  "artist": "Artist name",
  "album": "Album name",
  "year": 1995,
  "genre": "Pop / Rock",
  "tracks": [
    {"side": "A", "track_num": 1, "title": "Track Title 1", "duration_sec": 210},
    {"side": "A", "track_num": 2, "title": "Track Title 2", "duration_sec": 195},
    {"side": "B", "track_num": 1, "title": "Track Title 3", "duration_sec": 240}
  ]
}
If durations are not listed, estimate around 210 seconds per track.
If Side A / Side B is not explicitly marked, divide tracks roughly in half between side A and B.
"""
        models = ["gemini-3.6-flash", "gemini-flash-lite-latest", "gemini-3.8-flash", "gemini-3.5-flash"]
        for m in models:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}"
                payload = {
                    "contents": [
                        {
                            "parts": [
                                {"text": prompt},
                                {
                                    "inline_data": {
                                        "mime_type": mime_type,
                                        "data": b64_data
                                    }
                                }
                            ]
                        }
                    ],
                    "generationConfig": {
                        "response_mime_type": "application/json",
                        "temperature": 0.1
                    }
                }
                
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    if raw_text.startswith("```"):
                        raw_text = re.sub(r"^```[a-z]*\n", "", raw_text)
                        raw_text = re.sub(r"\n```$", "", raw_text)
                    parsed = json.loads(raw_text)
                    if parsed.get("artist") or parsed.get("album"):
                        return parsed
            except Exception as e_model:
                print(f"Gemini model {m} failed:", e_model)
                continue
    except Exception as e:
        print("Gemini Vision error:", e)
    return None

def clean_ocr_text(text: str) -> List[str]:
    result = []
    for line in text.splitlines():
        line = line.strip()
        line = re.sub(r'^[^a-zA-Z0-9\u0100-\u024F]+', '', line)
        line = re.sub(r'[^a-zA-Z0-9\u0100-\u024F\.\,\(\)\-\'\s]+', '', line)
        line = line.strip()
        if len(line) >= 2:
            result.append(line)
    return result

def filter_meaningful_words(line: str) -> List[str]:
    words = re.findall(r'[a-zA-Z0-9\u0100-\u024F]{2,}', line)
    return [w for w in words if w.upper() not in ALL_STOP_WORDS]

def analyze_photo_with_ocr(image_path: str) -> Dict[str, Any]:
    """Local OCR with Tesseract -> Smart online lookup -> Parsed tracks"""
    raw_text = ""
    try:
        proc_path = "/tmp/ocr_prep.png"
        subprocess.run([
            "magick", image_path,
            "-colorspace", "Gray",
            "-auto-level",
            "-contrast-stretch", "2%x2%",
            "-sharpen", "0x1.5",
            proc_path
        ], check=False)
        target = proc_path if os.path.exists(proc_path) else image_path
        
        res = subprocess.run(["tesseract", target, "stdout", "-l", "eng", "--psm", "3"], capture_output=True, text=True, check=False)
        raw_text = res.stdout.strip()
        
        if len(raw_text) < 15:
            res11 = subprocess.run(["tesseract", target, "stdout", "-l", "eng", "--psm", "11"], capture_output=True, text=True, check=False)
            if len(res11.stdout.strip()) > len(raw_text):
                raw_text = res11.stdout.strip()
    except Exception as e:
        print("Local OCR error:", e)
        
    lines = clean_ocr_text(raw_text)
    
    # Extract meaningful non-stop words
    meaningful_lines = []
    all_meaningful_words = []
    for l in lines:
        filtered = filter_meaningful_words(l)
        if filtered:
            meaningful_lines.append(" ".join(filtered))
            all_meaningful_words.extend(filtered)
            
    # ONLY search iTunes if we have strong candidates (at least 2 words or a unique 5+ letter word)
    search_candidates = []
    if len(meaningful_lines) >= 2:
        search_candidates.append(f"{meaningful_lines[0]} {meaningful_lines[1]}")
    if len(meaningful_lines) >= 1 and (len(all_meaningful_words) >= 2 or (len(meaningful_lines[0]) >= 5)):
        search_candidates.append(meaningful_lines[0])
    if len(all_meaningful_words) >= 3:
        search_candidates.append(" ".join(all_meaningful_words[:3]))
        
    for cand in search_candidates:
        cand_words = set(w.upper() for w in re.findall(r'\w+', cand) if w.upper() not in ALL_STOP_WORDS)
        if not cand_words:
            continue
            
        matched = search_itunes_album(cand)
        if matched and matched.get("artist"):
            # Verify result has at least one matching non-stop word
            res_words = set(w.upper() for w in re.findall(r'\w+', f"{matched['artist']} {matched['album']}"))
            if cand_words.intersection(res_words):
                matched["source"] = "Auto-Match (iTunes)"
                return matched
                
    # If no online match, check if OCR lines look like a printed tracklist
    tracks = []
    track_pattern = re.compile(r'^(?:[a-bA-B]?\d+[\.\-\s\)]|[a-bA-B][\.\-\s])\s*(.+)$')
    time_pattern = re.compile(r'[\(\[]?(\d{1,2})[:\.](\d{2})[\)\]]?')
    current_side = "A"
    t_num = 1
    
    for line in lines:
        upper = line.upper()
        if "SIDE B" in upper or "PUSE B" in upper or upper == "B":
            current_side = "B"
            t_num = 1
            continue
        elif "SIDE A" in upper or "PUSE A" in upper or upper == "A":
            current_side = "A"
            t_num = 1
            continue
            
        m = track_pattern.match(line)
        if m:
            title = m.group(1).strip()
            dur_sec = 210
            tm = time_pattern.search(title)
            if tm:
                try:
                    dur_sec = int(tm.group(1)) * 60 + int(tm.group(2))
                    title = time_pattern.sub('', title).strip()
                except:
                    pass
            if len(title) >= 3:
                tracks.append({
                    "side": current_side,
                    "track_num": t_num,
                    "title": title,
                    "duration_sec": dur_sec
                })
                t_num += 1

    if tracks:
        return {
            "artist": meaningful_lines[0] if meaningful_lines else "Nezināms Izpildītājs",
            "album": meaningful_lines[1] if len(meaningful_lines) > 1 else "Kasetes Ieraksts",
            "year": None,
            "genre": "Pops / Roks",
            "tracks": tracks,
            "source": "Local OCR"
        }

    # Could not confidently recognize
    return {
        "artist": "",
        "album": "",
        "year": None,
        "genre": "",
        "tracks": [],
        "source": "Neatpazīts",
        "warning": "Vāciņa stilizēto fontu neizdevās precīzi nolasīt ar lokālo OCR. Ievadi nosaukumu ātrajā meklēšanā vai pieslēdz AI Vision!"
    }

def scan_cassette_image(image_path: str) -> Dict[str, Any]:
    cfg = get_config()
    api_key = cfg.get("gemini_api_key", "").strip()
    
    if api_key:
        result = analyze_photo_with_gemini(image_path, api_key)
        if result and (result.get("artist") or result.get("tracks")):
            result["source"] = "Gemini AI Vision"
            return result
            
    # Fallback to local OCR + verified online lookup
    return analyze_photo_with_ocr(image_path)
