"""Bounded Pillow-only visual hints, not an identity/duplicate decision.

No network or neural models. Persist a few small hashes/grids per unidentified
library image; hash bands shortlist before stricter pixel/color checks.
"""
import base64
import math
import statistics
import threading
from datetime import datetime
from functools import lru_cache
from itertools import islice
from pathlib import Path

from PIL import Image, ImageOps
from sqlalchemy import func, or_

from . import models
from .config import settings
from .services import ImageService

ALGORITHM = "visual64-grid-v1"
COS = [[math.cos(math.pi * (2*x+1)*k/32) for x in range(16)] for k in range(8)]
INDEX_LOCK = threading.Lock()
INDEX = (None, None)


def unidentified():
    return or_(models.Image.pid.is_(None), func.trim(models.Image.pid) == "")


def signature(path):
    stat = path.stat()
    return [str(path), stat.st_size, stat.st_mtime_ns]


def region_descriptor(image):
    rgb = image.convert("RGB")
    gray = bytes(rgb.convert("L").resize((16,16), Image.Resampling.LANCZOS).getdata())
    mean = sum(gray)/256
    variance = sum((x-mean)**2 for x in gray)/256
    if variance < 144:  # Flat pictures and UI backgrounds are poor evidence.
        return None
    rows = [[sum(gray[y*16+x]*COS[k][x] for x in range(16)) for y in range(16)] for k in range(8)]
    frequencies = [sum(rows[k][y]*COS[j][y] for y in range(16)) for j in range(8) for k in range(8) if k or j]
    median = statistics.median(frequencies)
    phash = sum((value>median)<<index for index,value in enumerate(frequencies))
    grid = list(rgb.convert("L").resize((9,8), Image.Resampling.LANCZOS).getdata())
    dhash = sum((grid[y*9+x]>grid[y*9+x+1])<<(y*8+x) for y in range(8) for x in range(8))
    return {"p":f"{phash:016x}","d":f"{dhash:016x}","g":base64.b64encode(gray).decode(),
            "c":base64.b64encode(rgb.resize((4,4),Image.Resampling.BILINEAR).tobytes()).decode(),
            "ratio":round(rgb.width/rgb.height,4)}


def content_boxes(image):
    """Find a large connected artwork on a mostly uniform screenshot background."""
    small = image.resize((64,64), Image.Resampling.BILINEAR)
    pixels = list(small.getdata())
    backgrounds = {pixels[index] for index in (0,63,4032,4095)}
    boxes = set()
    for background in list(backgrounds)[:4]:
        active = {i for i,color in enumerate(pixels) if max(abs(a-b) for a,b in zip(color,background))>30}
        best = []
        while active:
            todo=[active.pop()];component=[]
            while todo:
                point=todo.pop();component.append(point)
                x,y=point%64,point//64
                for nx,ny in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                    other=ny*64+nx
                    if 0<=nx<64 and 0<=ny<64 and other in active:
                        active.remove(other);todo.append(other)
            if len(component)>len(best):best=component
        if len(best)<400:continue
        left,right=min(i%64 for i in best),max(i%64 for i in best)+1
        top,bottom=min(i//64 for i in best),max(i//64 for i in best)+1
        if (right-left)*(bottom-top)>3900:continue
        if right-left<16 or bottom-top<16:continue
        boxes.add((round(left*image.width/64),round(top*image.height/64),round(right*image.width/64),round(bottom*image.height/64)))
    return sorted(boxes, key=lambda box:(box[2]-box[0])*(box[3]-box[1]), reverse=True)[:2]


def describe(path):
    with Image.open(path) as source:
        if source.width*source.height>50_000_000:raise ValueError("image too large")
        source.draft("RGB",(256,256))
        source.thumbnail((256,256),Image.Resampling.LANCZOS)
        image=ImageOps.exif_transpose(source).convert("RGB")
    width,height=image.size
    boxes=[(0,0,width,height),*content_boxes(image)]
    boxes += [(round(width*(1-scale)/2),round(height*(1-scale)/2),round(width*(1+scale)/2),round(height*(1+scale)/2)) for scale in (.9,.8)]
    if width!=height:
        side=min(width,height);left=(width-side)//2;top=(height-side)//2
        boxes.append((left,top,left+side,top+side))
    variants=[]
    for box in dict.fromkeys(boxes):
        descriptor=region_descriptor(image.crop(box))
        if descriptor and not any(row['p']==descriptor['p'] and row['d']==descriptor['d'] for row in variants):variants.append(descriptor)
    return {"variants":variants}


def index_missing_batch(db, limit=24):
    rows=db.query(models.Image).outerjoin(models.ImageVisualFingerprint).filter(
        unidentified(),models.Image.file_status=="available",
        or_(models.ImageVisualFingerprint.image_id.is_(None),models.ImageVisualFingerprint.algorithm!=ALGORITHM),
    ).order_by(models.Image.image_id).limit(limit).all()
    failed=0
    for image in rows:
        path=Path(ImageService.image_full_path(image))
        source=[]
        try:
            source=signature(path)
            thumb=Path(settings.THUMB_PATH)/f"{image.image_id}.webp"
            sample=thumb if image.thumb_status=='ready' and thumb.is_file() and thumb.stat().st_mtime_ns>=source[2] else path
            descriptor=describe(sample)
        except (OSError,ValueError,Image.DecompressionBombError):
            descriptor={"variants":[],"error":"unreadable"};failed+=1
        record=image.visual_fingerprint
        if record is None:
            record=models.ImageVisualFingerprint(image=image);db.add(record)
        record.algorithm,record.source_signature,record.descriptor=ALGORITHM,source,descriptor
        record.updated_at=datetime.utcnow()
    db.flush()
    return {"processed":len(rows),"failed":failed}


class HashIndex:
    def __init__(self, rows):
        self.entries=[];self.bands=[{} for _ in range(7)]
        for image_id,descriptor,source in rows:
            for variant in descriptor.get('variants',[]):
                value=int(variant['p'],16)
                packed=(value,int(variant['d'],16),base64.b64decode(variant['g']),base64.b64decode(variant['c']),variant['ratio'])
                entry=len(self.entries);self.entries.append((image_id,packed,source))
                for band,buckets in enumerate(self.bands):buckets.setdefault((value>>(band*9))&511,[]).append(entry)

    def nearest(self, value):
        # A 63-bit hash with <=6 changed bits must retain one of seven 9-bit bands.
        candidates=set()
        for band,buckets in enumerate(self.bands):candidates.update(buckets.get((value>>(band*9))&511,()))
        ranked=sorted(((value^self.entries[i][1][0]).bit_count(),i) for i in candidates)
        for distance,index in ranked:
            if distance>6:break
            yield self.entries[index]


def get_index(db):
    global INDEX
    query=db.query(models.ImageVisualFingerprint).join(models.Image).filter(unidentified(),models.Image.file_status=='available',models.ImageVisualFingerprint.algorithm==ALGORITHM)
    stamp=(id(db.get_bind()), *query.with_entities(func.count(models.ImageVisualFingerprint.image_id),func.max(models.ImageVisualFingerprint.updated_at),func.max(models.Image.updated_at)).one())
    with INDEX_LOCK:
        if INDEX[0]!=tuple(stamp):
            rows=query.with_entities(models.ImageVisualFingerprint.image_id,models.ImageVisualFingerprint.descriptor,models.ImageVisualFingerprint.source_signature).all()
            INDEX=(tuple(stamp),HashIndex(rows))
        return INDEX[1]


def correlation(left,right):
    a=base64.b64decode(left) if isinstance(left,str) else left
    b=base64.b64decode(right) if isinstance(right,str) else right
    ma,mb=sum(a)/256,sum(b)/256
    numerator=sum((x-ma)*(y-mb) for x,y in zip(a,b))
    denominator=math.sqrt(sum((x-ma)**2 for x in a)*sum((y-mb)**2 for y in b))
    return numerator/denominator if denominator else 0


@lru_cache(maxsize=256)
def cached_descriptor(path, size, mtime):
    return describe(Path(path))


def match_cached_preview(db, path, index=None):
    try:
        descriptor=cached_descriptor(*signature(path))
    except (OSError,ValueError,Image.DecompressionBombError):return []
    index=index or get_index(db);matches={}
    for variant in descriptor['variants']:
        for image_id,local,source in islice(index.nearest(int(variant['p'],16)),256):
            if abs(math.log(local[4]/variant['ratio']))>.12:continue
            dhash=(local[1]^int(variant['d'],16)).bit_count()
            if dhash>10:continue
            structure=correlation(local[2],variant['g'])
            if structure<.94:continue
            a,b=local[3],base64.b64decode(variant['c'])
            if sum(abs(x-y) for x,y in zip(a,b))/48>22:continue
            try:
                if source!=signature(Path(source[0])):continue
            except (OSError,IndexError):continue
            previous=matches.get(image_id,0)
            matches[image_id]=max(previous,round(structure*100,1))
    return [{"image_id":image_id,"score":score} for image_id,score in sorted(matches.items(),key=lambda row:(-row[1],row[0]))[:3]]
