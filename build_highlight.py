# -*- coding: utf-8 -*-
"""build_highlight.py — highlight the target parcel (the teig at the property's
address point) by flood-filling the boundary-line image from the centre.
Rewrites each _bnd.png (neighbour lines + highlighted target fill+outline) and
rebuilds _tex.jpg (aerial + highlighted boundaries) for the 3D drape."""
import os, json
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
farms=json.load(open("data/farms.json",encoding="utf-8"))
M="data/media"
FILL=(50,200,255,105); OUTLINE=(0,234,255,255); LINE=(255,214,0,255)
for f in farms:
    fk=f["finnkode"]; bp=f"{M}/{fk}_bnd.png"; ap=f"{M}/{fk}_aer.jpg"
    if not os.path.exists(bp): print(fk,"no bnd"); continue
    bnd=Image.open(bp).convert("RGBA"); W,H=bnd.size; a=np.array(bnd)
    # only YELLOW pixels are boundary lines (ignore any prior cyan highlight -> idempotent)
    yellow=(a[:,:,0]>180)&(a[:,:,1]>140)&(a[:,:,2]<130)&(a[:,:,3]>40)
    lines=np.zeros((H,W,4),np.uint8); lines[yellow]=LINE; linesimg=Image.fromarray(lines,"RGBA")
    wall=yellow
    canv=np.full((H,W,3),255,np.uint8); canv[wall]=0
    canv[:2,:]=0;canv[-2:,:]=0;canv[:,:2]=0;canv[:,-2:]=0
    cimg=Image.fromarray(canv)
    cx,cy=W//2,H//2
    def openpix():
        for r in range(0,50):
            for dx in range(-r,r+1):
                for dy in range(-r,r+1):
                    x,y=cx+dx,cy+dy
                    if 0<=x<W and 0<=y<H and not wall[y,x]: return x,y
        return cx,cy
    sx,sy=openpix()
    ImageDraw.floodfill(cimg,(sx,sy),(255,0,0),thresh=10)
    fill=np.array(cimg); region=(fill[:,:,0]==255)&(fill[:,:,1]==0)&(fill[:,:,2]==0)
    frac=float(region.mean())
    ov=np.zeros((H,W,4),np.uint8)
    good=0.002<frac<0.7
    if good:
        ov[region]=FILL
        rimg=Image.fromarray((region*255).astype(np.uint8))
        edge=np.array(rimg.filter(ImageFilter.MaxFilter(9)))>0
        edge=edge & ~(np.array(rimg.filter(ImageFilter.MinFilter(3)))>0)
        ov[edge]=OUTLINE
    ovimg=Image.fromarray(ov,"RGBA"); ovimg.paste(linesimg,(0,0),linesimg)  # yellow lines on top
    ovimg.save(bp,"PNG",optimize=True)
    if os.path.exists(ap):
        base=Image.open(ap).convert("RGB"); base.paste(ovimg,(0,0),ovimg)
        base.save(f"{M}/{fk}_tex.jpg","JPEG",quality=82,optimize=True)
    print(f"{fk} {f['place']:15} frac={frac:.3f} highlight={'yes' if good else 'SKIP'}")
print("done")
