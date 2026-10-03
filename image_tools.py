import os
import time
from typing import Dict, Any, Optional, Tuple
from PIL import Image, ImageOps
import numpy as np

def fix_orientation(img: Image.Image) -> Image.Image:
    """Normalize image orientation according to EXIF data"""
    try:
        return ImageOps.exif_transpose(img)
    except Exception:
        return img

def auto_detect_object_bounds(
    img: Image.Image,
    target_aspect_ratio: Optional[float] = None
) -> Tuple[int, int, int, int]:
    """
    Detect the bounding box of a physical object (cassette, vinyl, tape box)
    resting on a table/desk background by sampling the outer borders and
    finding high-contrast foreground contours.
    Optionally snaps to a target aspect ratio (e.g. 70/108 for cassette, 1.0 for vinyl).
    """
    w, h = img.size
    max_dim = 600
    scale = max_dim / max(w, h)
    small_w = max(1, int(w * scale))
    small_h = max(1, int(h * scale))
    
    # Downsample for fast robust color clustering
    small = img.resize((small_w, small_h), Image.Resampling.BILINEAR)
    if small.mode != 'RGB':
        small = small.convert('RGB')
    arr = np.array(small, dtype=float)
    
    # Sample border pixels (outer 5%) to model background table/desk
    border_px = np.concatenate([
        arr[:max(2, int(small_h * 0.05)), :, :].reshape(-1, 3),
        arr[-max(2, int(small_h * 0.05)):, :, :].reshape(-1, 3),
        arr[:, :max(2, int(small_w * 0.05)), :].reshape(-1, 3),
        arr[:, -max(2, int(small_w * 0.05)):, :].reshape(-1, 3),
    ], axis=0)
    
    bg_median = np.median(border_px, axis=0)
    bg_std = np.std(border_px, axis=0)
    bg_threshold = max(24.0, float(np.mean(bg_std) * 2.2))
    
    # Euclidean distance from background color
    dist = np.sqrt(np.sum((arr - bg_median) ** 2, axis=2))
    fg_mask = dist > bg_threshold
    
    row_counts = np.sum(fg_mask, axis=1)
    col_counts = np.sum(fg_mask, axis=0)
    
    # Object must occupy at least 10% of width/height
    min_col_count = small_w * 0.10
    min_row_count = small_h * 0.10
    
    active_rows = np.where(row_counts > min_col_count)[0]
    active_cols = np.where(col_counts > min_row_count)[0]
    
    if len(active_rows) > 0 and len(active_cols) > 0:
        y1, y2 = int(active_rows[0]), int(active_rows[-1])
        x1, x2 = int(active_cols[0]), int(active_cols[-1])
        
        # Scale back to full resolution
        orig_x1 = max(0, int(x1 / scale))
        orig_y1 = max(0, int(y1 / scale))
        orig_x2 = min(w, int(x2 / scale))
        orig_y2 = min(h, int(y2 / scale))
        
        bw = orig_x2 - orig_x1
        bh = orig_y2 - orig_y1
        
        # Ensure detected box is reasonably sized (at least 20% of image)
        if bw > w * 0.2 and bh > h * 0.2:
            bx = orig_x1
            by = orig_y1
            if target_aspect_ratio and target_aspect_ratio > 0 and bh > 0:
                cur_ratio = bw / bh
                if cur_ratio > target_aspect_ratio:
                    new_w = int(bh * target_aspect_ratio)
                    bx = max(0, min(w - new_w, bx + (bw - new_w) // 2))
                    bw = new_w
                else:
                    new_h = int(bw / target_aspect_ratio)
                    by = max(0, min(h - new_h, by + (bh - new_h) // 2))
                    bh = new_h
            return (bx, by, bw, bh)
            
    return (0, 0, w, h)

def crop_and_save_image(
    input_path: str,
    output_dir: str,
    box: Optional[Tuple[int, int, int, int]] = None,
    rotation: int = 0,
    prefix: str = "cover"
) -> str:
    """
    Crops, rotates, and saves an image, returning the filename.
    box is (x, y, width, height) in image coordinates.
    """
    img = Image.open(input_path)
    img = fix_orientation(img)
    
    # Apply user rotation if requested (90, 180, 270)
    if rotation in (90, 180, 270):
        # PIL rotate is counter-clockwise, so -rotation or transpose
        if rotation == 90:
            img = img.transpose(Image.Transpose.ROTATE_270)
        elif rotation == 180:
            img = img.transpose(Image.Transpose.ROTATE_180)
        elif rotation == 270:
            img = img.transpose(Image.Transpose.ROTATE_90)
            
    w, h = img.size
    
    if box:
        bx, by, bw, bh = box
        # Clamp to bounds
        bx = max(0, min(w - 10, bx))
        by = max(0, min(h - 10, by))
        bw = max(10, min(w - bx, bw))
        bh = max(10, min(h - by, bh))
        img = img.crop((bx, by, bx + bw, by + bh))
        
    # Resize if excessively large to keep storage light and snappy (max 1800px)
    max_dim = 1800
    if img.width > max_dim or img.height > max_dim:
        scale = max_dim / max(img.width, img.height)
        new_w = int(img.width * scale)
        new_h = int(img.height * scale)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        
    if img.mode != 'RGB':
        img = img.convert('RGB')
        
    filename = f"{prefix}_{int(time.time() * 1000)}.jpg"
    dest_path = os.path.join(output_dir, filename)
    img.save(dest_path, "JPEG", quality=92, optimize=True)
    return filename
