import sqlite3
import os
from typing import List, Dict, Any, Optional

DB_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
DB_PATH = os.path.join(DB_DIR, "vault.db")

def get_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS media (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        media_type TEXT NOT NULL DEFAULT 'MC', -- MC (Cassette), LP (Vinyl), RT (Reel Tape)
        artist TEXT NOT NULL,
        album TEXT NOT NULL,
        year INTEGER,
        genre TEXT,
        photo_url TEXT,
        shelf_location TEXT DEFAULT 'Koferis 1',
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        media_id INTEGER NOT NULL,
        side TEXT NOT NULL DEFAULT 'A', -- A or B
        track_num INTEGER NOT NULL,
        title TEXT NOT NULL,
        duration_sec INTEGER DEFAULT 210, -- Default 3m 30s
        FOREIGN KEY (media_id) REFERENCES media (id) ON DELETE CASCADE
    );
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS mixtapes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        creator_name TEXT NOT NULL DEFAULT 'Draugs',
        target_media TEXT NOT NULL DEFAULT 'C60', -- C60, C90, C120
        status TEXT NOT NULL DEFAULT 'Gaidīšanā', -- Gaidīšanā, Ierakstīts, Pabeigts
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS mixtape_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mixtape_id INTEGER NOT NULL,
        track_id INTEGER NOT NULL,
        side TEXT NOT NULL DEFAULT 'A', -- Target mixtape side A or B
        position INTEGER NOT NULL,
        FOREIGN KEY (mixtape_id) REFERENCES mixtapes (id) ON DELETE CASCADE,
        FOREIGN KEY (track_id) REFERENCES tracks (id) ON DELETE CASCADE
    );
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS guest_passes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        pass_code TEXT UNIQUE NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_used_at TIMESTAMP
    );
    """)
    
    conn.commit()
    conn.close()

def list_guest_passes() -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM guest_passes ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def create_guest_pass(name: str, pass_code: str, notes: Optional[str] = None) -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO guest_passes (name, pass_code, is_active, notes)
        VALUES (?, ?, 1, ?)
    """, (name.strip(), pass_code.strip(), notes))
    pass_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return pass_id

def toggle_guest_pass(pass_id: int, is_active: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE guest_passes SET is_active = ? WHERE id = ?", (is_active, pass_id))
    conn.commit()
    conn.close()

def delete_guest_pass(pass_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM guest_passes WHERE id = ?", (pass_id,))
    conn.commit()
    conn.close()


def seed_sample_data(conn):
    cursor = conn.cursor()
    sample_media = [
        ("MC-0001", "MC", "Depeche Mode", "Violator", 1990, "Synthpop", "Koferis 1", "Oriģinālā vācu kasete, lielisks stāvoklis", [
            ("A", 1, "World in My Eyes", 266),
            ("A", 2, "Sweetest Perfection", 283),
            ("A", 3, "Personal Jesus", 296),
            ("A", 4, "Halo", 270),
            ("A", 5, "Waiting for the Night", 367),
            ("B", 1, "Enjoy the Silence", 372),
            ("B", 2, "Policy of Truth", 295),
            ("B", 3, "Blue Dress", 342),
            ("B", 4, "Clean", 328)
        ]),
        ("MC-0002", "MC", "Pink Floyd", "The Dark Side of the Moon", 1973, "Progressive Rock", "Koferis 2", "EMI/Harvest izdevums", [
            ("A", 1, "Speak to Me / Breathe", 238),
            ("A", 2, "On the Run", 215),
            ("A", 3, "Time", 425),
            ("A", 4, "The Great Gig in the Sky", 284),
            ("B", 1, "Money", 382),
            ("B", 2, "Us and Them", 469),
            ("B", 3, "Any Colour You Like", 205),
            ("B", 4, "Brain Damage", 228),
            ("B", 5, "Eclipse", 123)
        ]),
        ("MC-0003", "MC", "Zeļļi", "Vēl paliec te...", 1998, "Šlāgermūzika", "Koferis 1", "Gailītis G izdevums", [
            ("A", 1, "Vēl paliec te", 215),
            ("A", 2, "Rīta vēsma", 198),
            ("A", 3, "Zilie ezeri", 240),
            ("A", 4, "Atmiņu lietus", 210),
            ("B", 1, "Šodien un rīt", 225),
            ("B", 2, "Vakara saule", 205),
            ("B", 3, "Kad pērles birs", 250),
            ("B", 4, "Drauga vārds", 190)
        ]),
        ("MC-0004", "MC", "Kantoris 04", "Balts rīts", 1999, "Šlāgermūzika", "Koferis 1", "Studija Mix", [
            ("A", 1, "Balts rīts", 230),
            ("A", 2, "O, mana mazā!", 210),
            ("A", 3, "Lūgums", 245),
            ("B", 1, "Ar sauli sirdī", 220),
            ("B", 2, "Nakts meitene", 205),
            ("B", 3, "Vēju spēle", 215)
        ]),
        ("MC-0005", "MC", "Nirvana", "Nevermind", 1991, "Grunge", "Koferis 2", "Geffen Records", [
            ("A", 1, "Smells Like Teen Spirit", 301),
            ("A", 2, "In Bloom", 254),
            ("A", 3, "Come as You Are", 219),
            ("A", 4, "Breed", 183),
            ("A", 5, "Lithium", 257),
            ("A", 6, "Polly", 177),
            ("B", 1, "Territorial Pissings", 143),
            ("B", 2, "Drain You", 223),
            ("B", 3, "Lounge Act", 156),
            ("B", 4, "Stay Away", 212),
            ("B", 5, "On a Plain", 196),
            ("B", 6, "Something in the Way", 232)
        ]),
        ("LP-0001", "LP", "Smokie", "The Best of Smokie", 1978, "Rock / Pop", "Plaukts Vinils 1", "Melodija / EMI licence", [
            ("A", 1, "Living Next Door to Alice", 207),
            ("A", 2, "I'll Meet You at Midnight", 194),
            ("A", 3, "Lay Back in the Arms of Someone", 244),
            ("B", 1, "Needles and Pins", 163),
            ("B", 2, "Don't Play Your Rock 'n' Roll to Me", 197),
            ("B", 3, "Wild Wild Angels", 267)
        ])
    ]
    
    for code, mtype, artist, album, year, genre, shelf, notes, tracks in sample_media:
        cursor.execute("""
            INSERT INTO media (code, media_type, artist, album, year, genre, shelf_location, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (code, mtype, artist, album, year, genre, shelf, notes))
        media_id = cursor.lastrowid
        
        for side, num, title, dur in tracks:
            cursor.execute("""
                INSERT INTO tracks (media_id, side, track_num, title, duration_sec)
                VALUES (?, ?, ?, ?, ?)
            """, (media_id, side, num, title, dur))
            
    conn.commit()

def get_next_code(media_type: str = 'MC') -> str:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT code FROM media WHERE media_type = ? ORDER BY id DESC LIMIT 1", (media_type,))
    row = cursor.fetchone()
    conn.close()
    if row and row['code']:
        try:
            parts = row['code'].split('-')
            next_num = int(parts[1]) + 1
            return f"{media_type}-{next_num:04d}"
        except:
            pass
    return f"{media_type}-0001"
