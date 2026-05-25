#!/usr/bin/env python3
"""
AIRBUS A321neo — CYBERSECURITY EMERGENCY  (v2 · 10 seconds)
ELK421  LEMD → KJFK  |  FL350  |  North Atlantic

SCENARIO (inspired by real events):
  At 02:14 UTC, EUROLINK 421 receives its routine ACARS uplink.
  Unknown to the crew, the FAA NOTAM server has been fed a corrupted
  dataset — identical to the January 2023 incident where a contractor
  accidentally overwrote both the live and backup navigation databases.
  An attacker, exploiting ACARS's known lack of encryption/authentication,
  injects false waypoint data. The crew's FMS starts showing impossible
  positions. MASTER CAUTION, then MASTER WARNING. Unable to verify their
  oceanic position, they declare an emergency and divert.

Real incidents:
  • Jan 11 2023  FAA NOTAM database corruption → first US nationwide ground stop since 9/11
  • ACARS plaintext VHF data-link: any SDR can intercept or inject (peer-reviewed research)
  • Oct 2025     Airbus A320 ELAC data corruption → emergency software rollback across 6,000 a/c
"""
import os, math, wave, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import cv2

# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════
W, H   = 1920, 1080
FPS    = 30
DUR    = 10.0
NF     = int(FPS * DUR)      # 300 frames
SRATE  = 44100

OUT   = "/home/user/GATE-SAFE-VIDEO/cockpit_emergency_v2.mp4"
TMP_V = "/tmp/ck2_raw.mp4"
TMP_A = "/tmp/ck2_audio.wav"

# ═══════════════════════════════════════════════════════════════════════
# TIMELINE  (seconds)
# ═══════════════════════════════════════════════════════════════════════
T_LABEL   = 0.3    # display labels fade in
T_ANOMALY = 1.8    # first corrupted ACARS packet
T_CAUTION = 2.8    # MASTER CAUTION
T_WARNING = 4.2    # MASTER WARNING — full cascade
T_DECISION= 5.8    # crew deliberating
T_DIVERT  = 7.0    # emergency declared
T_HOLD    = 8.4    # dramatic hold on emergency state
T_FADE    = 9.4    # fade to citation
T_END     = 10.0

# ═══════════════════════════════════════════════════════════════════════
# PALETTE  (RGB)
# ═══════════════════════════════════════════════════════════════════════
BG       = ( 8,   8,  12)
PANEL    = (18,  18,  24)
SKY_C    = (24,  66, 136)
GND_C    = (68,  44,   7)
HRZ_C    = (210, 196, 172)
GREEN    = (  0, 218,  48)
AMBER    = (255, 178,   0)
RED      = (218,  20,  20)
CYAN     = (  0, 215, 252)
WHITE    = (255, 255, 255)
LGRAY    = (158, 158, 168)
MGRAY    = ( 78,  78,  88)
DGRAY    = ( 28,  28,  36)
MAGENTA  = (210,   0, 210)
YELLOW   = (255, 218,   0)
DKRED    = ( 70,   6,   6)
DKAMB    = ( 65,  40,   0)
BLACK    = (  0,   0,   0)
DKGREEN  = (  0,  60,  18)
ORANGE   = (255, 120,  10)

# ═══════════════════════════════════════════════════════════════════════
# LAYOUT
# ═══════════════════════════════════════════════════════════════════════
HDR_H  = 52
FTR_H  = 36
PAD    = 8
DISP_H = 790       # display panel height
DY1    = HDR_H + PAD          # 60
DY2    = DY1 + DISP_H         # 850

# Below displays: narrative + dialogue strips
NAR_Y1 = DY2 + 6;  NAR_Y2 = NAR_Y1 + 62    # 856..918  narrative beat
DLG_Y1 = NAR_Y2 + 4;  DLG_Y2 = H - FTR_H - 4  # 922..1006

# Three display panels
PFD_R  = (PAD,   DY1, 710,    DY2)   # w=702
ECAM_R = (718,   DY1, 1116,   DY2)   # w=398
ND_R   = (1124,  DY1, W-PAD,  DY2)   # w=788

def rW(r): return r[2]-r[0]
def rH(r): return r[3]-r[1]
def rCX(r): return (r[0]+r[2])//2
def rCY(r): return (r[1]+r[3])//2

# ═══════════════════════════════════════════════════════════════════════
# FONTS
# ═══════════════════════════════════════════════════════════════════════
_FPB = next((p for p in [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
] if os.path.exists(p)), None)
_FPR = next((p for p in [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
] if os.path.exists(p)), _FPB)

def F(sz, bold=True):
    fp = _FPB if bold else _FPR
    return ImageFont.truetype(fp, sz) if fp else ImageFont.load_default()

_sizes_b = [10,11,12,13,14,15,16,17,18,20,22,24,26,28,30,32,36,40,48,56,64,72,80]
_sizes_r = [10,11,12,13,14,15,16,17,18,20,22,24,26,28,32,36,40,48]
Fs = {sz: F(sz, True)  for sz in _sizes_b}
Fr = {sz: F(sz, False) for sz in _sizes_r}

# ═══════════════════════════════════════════════════════════════════════
# MATH / HELPERS
# ═══════════════════════════════════════════════════════════════════════
def ph(t, t0, t1):
    if t1 <= t0: return float(t >= t0)
    return max(0., min(1., (t-t0)/(t1-t0)))

def sm(p): return p*p*(3-2*p)
def lerp(a, b, p): return a + (b-a)*p
def blink(t, hz=2): return math.sin(t * hz * math.pi * 2) > 0
def fade_in(t, t0, dur=0.4): return sm(ph(t, t0, t0+dur))
def fade_out(t, t0, dur=0.4): return 1.0 - sm(ph(t, t0, t0+dur))
def pulse(t, hz=1): return (math.sin(t * hz * math.pi * 2) + 1) / 2

_rng = np.random.default_rng(42)

def cn(val, corr, n=3):
    """Corrupt numeric string."""
    if corr < 0.04: return str(int(val))
    if _rng.random() < corr * 0.6:
        spread = max(2, int(abs(val) * 0.07 * corr))
        return str(int(val) + int(_rng.integers(-spread, spread+1)))
    if _rng.random() < corr * 0.5:
        return "".join(str(_rng.integers(0, 10)) for _ in range(n))
    return str(int(val))

def tbbox(draw, txt, f):
    bb = draw.textbbox((0,0), txt, font=f)
    return bb[2]-bb[0], bb[3]-bb[1]

def tc(draw, cx, cy, txt, f, fill, anchor=None):
    w, h = tbbox(draw, txt, f)
    draw.text((cx-w//2, cy-h//2), txt, font=f, fill=fill)

def tl(draw, x, cy, txt, f, fill):
    _, h = tbbox(draw, txt, f)
    draw.text((x, cy-h//2), txt, font=f, fill=fill)

def tr(draw, rx, cy, txt, f, fill):
    w, h = tbbox(draw, txt, f)
    draw.text((rx-w, cy-h//2), txt, font=f, fill=fill)

def box(draw, x1,y1,x2,y2, fill=None, outline=None, lw=1):
    draw.rectangle([x1,y1,x2,y2], fill=fill, outline=outline, width=lw)

def ln(draw, x1,y1,x2,y2, fill=WHITE, w=1):
    draw.line([(x1,y1),(x2,y2)], fill=fill, width=w)

def circ(draw, cx,cy,r, fill=None, outline=None, lw=1):
    draw.ellipse([cx-r,cy-r,cx+r,cy+r], fill=fill, outline=outline, width=lw)

def alpha_txt(draw, cx, cy, txt, f, fill, alpha):
    if alpha <= 0.02: return
    r, g, b = fill
    col = (int(r*alpha), int(g*alpha), int(b*alpha))
    tc(draw, cx, cy, txt, f, col)

# ═══════════════════════════════════════════════════════════════════════
# ADI
# ═══════════════════════════════════════════════════════════════════════
def make_adi(R, pitch, roll):
    D  = R * 2
    S  = int(D * 1.5) + 12
    cx = S // 2
    adi = Image.new("RGB", (S, S), SKY_C)
    ad  = ImageDraw.Draw(adi)
    ppd = R / 20.0
    hy  = cx + int(pitch * ppd)
    if hy < S:
        ad.rectangle([0, max(0,hy), S, S], fill=GND_C)
    ad.rectangle([0, hy-3, S, hy+3], fill=HRZ_C)
    for deg in range(-30, 31, 5):
        if deg == 0: continue
        y = int(hy - deg * ppd)
        if not (4 < y < S-4): continue
        bw = int(R * (0.46 if abs(deg)%10==0 else 0.25))
        lw = 2 if abs(deg)%10==0 else 1
        ad.rectangle([cx-bw, y-lw, cx+bw, y+lw], fill=WHITE)
        if abs(deg)%10==0 and bw > 18:
            lbl = str(abs(deg))
            ad.text((cx-bw-28, y-9), lbl, font=Fs[12], fill=WHITE)
            ad.text((cx+bw+6,  y-9), lbl, font=Fs[12], fill=WHITE)
    # Sky chevrons at horizon
    for side in [-1, 1]:
        cx2 = cx + side * int(R*0.8)
        ad.rectangle([cx2-int(R*0.18), hy-2, cx2+int(R*0.18), hy+2], fill=HRZ_C)
    adi_r = adi.rotate(-roll, center=(cx,cx), expand=False, fillcolor=SKY_C)
    off = (S - D)//2
    adi_c = adi_r.crop([off, off, off+D, off+D])
    mask = Image.new("L", (D,D), 0)
    ImageDraw.Draw(mask).ellipse([0,0,D-1,D-1], fill=255)
    out = Image.new("RGBA", (D,D), (0,0,0,0))
    out.paste(adi_c, (0,0), mask=mask)
    return out

# ═══════════════════════════════════════════════════════════════════════
# HEADER
# ═══════════════════════════════════════════════════════════════════════
def draw_header(draw, t):
    corr   = sm(ph(t, T_ANOMALY, T_WARNING))
    severe = sm(ph(t, T_WARNING, T_DIVERT))

    box(draw, 0, 0, W, HDR_H, fill=(12,12,18))
    ln(draw, 0, HDR_H-2, W, HDR_H-2, MGRAY, 2)

    # Left: callsign
    tl(draw, 14, HDR_H//2, "ELK421", Fs[30], GREEN)
    tl(draw, 140, HDR_H//2, "EUROLINK 421  ·  A321neo", Fr[18], LGRAY)

    # Center: route
    route_col = AMBER if corr > 0.25 else WHITE
    tc(draw, W//2, HDR_H//2, "LEMD  ────  KJFK", Fs[22], route_col)

    # FL
    fl_col = RED if severe > 0.3 else (AMBER if corr > 0.3 else CYAN)
    fl_txt = cn(350, corr*0.3, 3)
    tc(draw, W//2 + 300, HDR_H//2, f"FL{fl_txt}", Fs[22], fl_col)

    # UTC time
    tl(draw, W//2 + 430, HDR_H//2, "02:14 UTC", Fr[16], LGRAY)

    # Right: squawk or normal
    if t >= T_DIVERT:
        sq_col = RED if blink(t, 2) else DKRED
        tr(draw, W-14, HDR_H//2, "▲ SQUAWK 7700 ▲", Fs[22], sq_col)
    elif t >= T_WARNING:
        tr(draw, W-14, HDR_H//2, "⚠ EMERGENCY ⚠", Fs[20], RED if blink(t,2) else AMBER)
    else:
        tr(draw, W-14, HDR_H//2, "SQUAWK 2143", Fr[16], LGRAY)

# ═══════════════════════════════════════════════════════════════════════
# DISPLAY LABELS  (first 3 seconds — teach the viewer what each is)
# ═══════════════════════════════════════════════════════════════════════
def draw_display_labels(draw, t):
    if t > 3.5: return
    a = min(fade_in(t, T_LABEL, 0.5), fade_out(t, 2.8, 0.5))
    if a < 0.02: return

    labels = [
        (rCX(PFD_R),  "PRIMARY FLIGHT DISPLAY",    "Attitude · Speed · Altitude · Heading"),
        (rCX(ECAM_R), "SYSTEMS & WARNINGS",         "Engine · Fuel · Failure Messages"),
        (rCX(ND_R),   "NAVIGATION DISPLAY",          "Route · Waypoints · ACARS Data Link"),
    ]
    for cx, title, sub in labels:
        # Backing
        tw, _ = tbbox(draw, title, Fs[16])
        bx = cx - tw//2 - 12
        box(draw, bx, DY1-28, bx+tw+24, DY1-4,
            fill=(int(20*a), int(20*a), int(28*a)),
            outline=(int(80*a), int(80*a), int(90*a)), lw=1)
        col = (int(200*a), int(200*a), int(210*a))
        col2 = (int(100*a), int(100*a), int(110*a))
        tc(draw, cx, DY1-16, title, Fs[16], col)

# ═══════════════════════════════════════════════════════════════════════
# PRIMARY FLIGHT DISPLAY
# ═══════════════════════════════════════════════════════════════════════
def draw_pfd(frame, draw, t):
    x1, y1, x2, y2 = PFD_R
    cx = rCX(PFD_R)
    w, h = rW(PFD_R), rH(PFD_R)

    corr   = sm(ph(t, T_ANOMALY, T_WARNING))
    severe = sm(ph(t, T_WARNING, T_DECISION))
    divert = sm(ph(t, T_DIVERT, T_END))

    box(draw, x1, y1, x2, y2, fill=PANEL, outline=MGRAY, lw=2)

    FMA_H = 68

    # ── FMA ──────────────────────────────────────────────────────────────
    box(draw, x1, y1, x2, y1+FMA_H, fill=(15,15,22), outline=MGRAY, lw=1)
    fma_data = [
        ("A/THR",  GREEN),
        ("OP CLB", GREEN),
        ("NAV",    CYAN),
        ("SRS",    MGRAY),
        ("AP1",    GREEN),
    ]
    cw = w // 5
    for i, (lbl, col) in enumerate(fma_data):
        fcx = x1 + i*cw + cw//2
        fcy = y1 + FMA_H//2
        if i == 2:  # NAV
            if severe > 0.4:
                col, lbl = RED, "NAV FAIL"
            elif corr > 0.15:
                col = AMBER if blink(t, 4) else CYAN
                lbl = "NAV*" if corr > 0.4 else "NAV?"
        if i == 4 and severe > 0.5:
            col, lbl = AMBER, "AP OFF"
        tc(draw, fcx, fcy, lbl, Fs[20], col)
        if i < 4:
            ln(draw, x1+(i+1)*cw, y1+8, x1+(i+1)*cw, y1+FMA_H-8, MGRAY, 1)
    ln(draw, x1+2, y1+FMA_H, x2-2, y1+FMA_H+1, MGRAY, 2)

    # ── SPEED TAPE ────────────────────────────────────────────────────────
    SX1=x1+4; SX2=x1+88; SY1=y1+FMA_H+4; SY2=y2-100
    SH=SY2-SY1; SCX=(SX1+SX2)//2; SCY=(SY1+SY2)//2

    box(draw, SX1, SY1, SX2, SY2, fill=(14,14,20))
    spd = 480 + 8*math.sin(t*0.35)
    spd_txt = cn(spd, corr*0.95, 3)
    spd_col = (RED if corr>0.7 else AMBER if corr>0.3 else WHITE)
    for ds in range(-60,61,10):
        ty = SCY - int(ds*SH/220)
        if SY1+4 < ty < SY2-4:
            ln(draw, SX2-20,ty, SX2-4,ty, LGRAY, 1)
            sv = int(spd+ds)
            if sv > 0: tr(draw, SX2-22, ty, str(sv), Fr[11], LGRAY)
    vls_y = SCY + int(18*SH/220)
    ln(draw, SX1+4, vls_y, SX2-4, vls_y, AMBER, 2)
    box(draw, SX1+2, SCY-28, SX2-2, SCY+28, fill=BLACK, outline=WHITE, lw=2)
    tc(draw, SCX, SCY, spd_txt, Fs[28], spd_col)

    # Speed label
    if fade_in(t, T_LABEL, 0.5) > 0.1 and t < 3.5:
        a = min(fade_in(t, T_LABEL, 0.5), fade_out(t, 2.8, 0.5))
        tc(draw, SCX, SY1+20, "IAS", Fr[12], (int(140*a),int(140*a),int(150*a)))
        tc(draw, SCX, SY1+36, "KT",  Fr[11], (int(100*a),int(100*a),int(110*a)))

    # ── ALTITUDE TAPE ──────────────────────────────────────────────────────
    AX1=x2-100; AX2=x2-4; AY1=y1+FMA_H+4; AY2=y2-100
    AH=AY2-AY1; ACX=(AX1+AX2)//2; ACY=(AY1+AY2)//2

    box(draw, AX1, AY1, AX2, AY2, fill=(14,14,20))
    alt = 35000 + 60*math.sin(t*0.22)
    alt_txt = cn(alt, corr*0.6, 5)
    alt_col = (RED if severe>0.5 else AMBER if corr>0.4 else WHITE)
    for da in range(-5000,5001,500):
        ty = ACY - int(da*AH/18000)
        if AY1+4 < ty < AY2-4:
            ln(draw, AX1+4,ty, AX1+20,ty, LGRAY, 1)
            av = int(alt+da)
            if av%1000==0: tl(draw, AX1+24, ty, str(av), Fr[10], LGRAY)
    tgt_alt = 35000 if divert < 0.05 else int(lerp(35000, 12000, sm(divert)))
    tgt_txt = cn(tgt_alt, corr*0.15, 5)
    tl(draw, AX1+4, AY1+18, tgt_txt, Fr[13], CYAN)
    box(draw, AX1+2, ACY-27, AX2-2, ACY+27, fill=BLACK, outline=WHITE, lw=2)
    tc(draw, ACX, ACY, alt_txt, Fs[24], alt_col)

    if fade_in(t, T_LABEL, 0.5) > 0.1 and t < 3.5:
        a = min(fade_in(t, T_LABEL, 0.5), fade_out(t, 2.8, 0.5))
        tc(draw, ACX, AY1+20, "ALT", Fr[12], (int(140*a),int(140*a),int(150*a)))
        tc(draw, ACX, AY1+36, "FT",  Fr[11], (int(100*a),int(100*a),int(110*a)))

    # ── ADI ────────────────────────────────────────────────────────────────
    AIX1=SX2+4; AIX2=AX1-4; AIY1=y1+FMA_H+4; AIY2=y2-100
    AICX=(AIX1+AIX2)//2; AICY=(AIY1+AIY2)//2
    AIR = min((AIX2-AIX1)//2-8, (AIY2-AIY1)//2-8)

    pitch = 2.2 + math.sin(t*0.38)*0.8 - sm(ph(t,T_DIVERT,T_END))*5
    roll  = math.sin(t*0.28)*2.0 - sm(ph(t,T_DIVERT,T_END))*22

    # Shake during warning
    shake = severe * 0.6
    if shake > 0.1:
        AICX += int(_rng.normal(0, shake*4))
        AICY += int(_rng.normal(0, shake*2))

    adi_img = make_adi(AIR, pitch, roll)
    px = AICX - AIR; py = AICY - AIR
    frame.paste(adi_img, (max(0,px), max(0,py)), adi_img)

    draw.ellipse([AICX-AIR-3, AICY-AIR-3, AICX+AIR+3, AICY+AIR+3], outline=MGRAY, width=3)

    # Red X on ADI when data compromised
    if severe > 0.65 and blink(t, 2.5):
        r2 = AIR - 10
        ln(draw, AICX-r2, AICY-r2, AICX+r2, AICY+r2, RED, 5)
        ln(draw, AICX+r2, AICY-r2, AICX-r2, AICY+r2, RED, 5)
        # "ATTITUDE  UNRELIABLE" text on ADI
        box(draw, AICX-130, AICY-18, AICX+130, AICY+18, fill=(100,0,0))
        tc(draw, AICX, AICY, "ATTITUDE  UNRELIABLE", Fs[16], WHITE)

    # Aircraft symbol
    sw = AIR // 2
    draw.line([(AICX-sw,AICY),(AICX-sw//3,AICY+sw//5),(AICX,AICY)], fill=YELLOW, width=4)
    draw.line([(AICX,AICY),(AICX+sw//3,AICY+sw//5),(AICX+sw,AICY)], fill=YELLOW, width=4)
    draw.line([(AICX-sw//4,AICY+sw//3),(AICX+sw//4,AICY+sw//3)], fill=YELLOW, width=3)
    circ(draw, AICX, AICY, 5, fill=YELLOW)

    # FPV
    fpv_x = AICX + int(roll*1.8)
    fpv_y = AICY - int(pitch*AIR/20)
    if AIY1<fpv_y<AIY2 and AIX1<fpv_x<AIX2:
        fpv_col = AMBER if corr > 0.3 else GREEN
        circ(draw, fpv_x, fpv_y, 9, outline=fpv_col, lw=2)
        ln(draw, fpv_x-22,fpv_y, fpv_x+22,fpv_y, fpv_col, 2)
        ln(draw, fpv_x,fpv_y, fpv_x,fpv_y-16, fpv_col, 2)

    # Roll arc
    arc_r = AIR + 16
    for deg in [-60,-45,-30,-20,-10,10,20,30,45,60]:
        a_rad = math.radians(90+deg)
        tl2 = 16 if abs(deg) in [30,60] else 9
        tx1 = AICX+int((arc_r-tl2)*math.cos(a_rad)); ty1=AICY-int((arc_r-tl2)*math.sin(a_rad))
        tx2 = AICX+int(arc_r*math.cos(a_rad));       ty2=AICY-int(arc_r*math.sin(a_rad))
        draw.line([(tx1,ty1),(tx2,ty2)], fill=WHITE, width=1)
    ridx_a = math.radians(90+roll)
    rx = AICX+int((arc_r-9)*math.cos(ridx_a)); ry=AICY-int((arc_r-9)*math.sin(ridx_a))
    circ(draw, rx, ry, 5, fill=YELLOW)

    # MASTER CAUTION / WARNING flag
    if t >= T_CAUTION:
        is_warn = t >= T_WARNING
        fc  = (RED if blink(t,2) else DKRED) if is_warn else (AMBER if blink(t,2) else DKAMB)
        txt = "MASTER WARNING" if is_warn else "MASTER CAUTION"
        box(draw, x1+6, y1+FMA_H+6, x1+225, y1+FMA_H+42, fill=fc, outline=WHITE, lw=2)
        tl(draw, x1+12, y1+FMA_H+24, txt, Fs[16], WHITE)

    # VS
    vs = int(sm(ph(t,T_DIVERT,T_END)) * -2400)
    vs_str = ("+" if vs>=0 else "") + str(vs) + " FT/M"
    vs_col = CYAN if vs==0 else (AMBER if vs<-800 else GREEN)
    tr(draw, AX2-4, AY2-16, vs_str, Fr[13], vs_col)

    # ── HEADING SCALE ─────────────────────────────────────────────────────
    HY1=y2-98; HY2=y2-6; HCY=(HY1+HY2)//2
    box(draw, x1+4, HY1, x2-4, HY2, fill=(15,15,22))
    hdg = 286.4 + math.sin(t*0.18)*0.5
    hdg_txt = cn(hdg, corr*0.3, 3)
    hsw = (x2-x1-20)
    for dh in range(-50,51,10):
        tx = cx + int(dh*hsw/160)
        if x1+8 < tx < x2-8:
            tlen = 22 if dh%20==0 else 14
            ln(draw, tx, HY1+6, tx, HY1+6+tlen, (WHITE if dh%20==0 else LGRAY), (2 if dh%20==0 else 1))
            hv = int(hdg+dh)%360
            tc(draw, tx, HY1+40, str(hv), Fr[11], LGRAY)
    box(draw, cx-42, HY1+4, cx+42, HY2-4, fill=BLACK, outline=WHITE, lw=2)
    tc(draw, cx, HCY, hdg_txt+"°", Fs[24], WHITE)

# ═══════════════════════════════════════════════════════════════════════
# ECAM
# ═══════════════════════════════════════════════════════════════════════
def draw_ecam(draw, t):
    x1,y1,x2,y2 = ECAM_R
    cx = rCX(ECAM_R); w = rW(ECAM_R)
    corr   = sm(ph(t, T_ANOMALY, T_WARNING))
    severe = sm(ph(t, T_WARNING, T_DECISION))
    divert = ph(t, T_DIVERT, T_END)

    UY2 = y1 + int(rH(ECAM_R)*0.44)
    LY1 = UY2 + 6

    # ── UPPER — engine gauges ─────────────────────────────────────────────
    box(draw, x1, y1, x2, UY2, fill=PANEL, outline=MGRAY, lw=2)
    # Small label
    tc(draw, cx, y1+16, "ENGINE", Fr[13], LGRAY)

    n1 = 88.4 + math.sin(t*0.4)*0.3
    egt= 650  + int(math.sin(t*0.3)*8)

    for i in range(2):
        ecx = x1 + w//4 + i*(w//2)
        ecy = y1 + (UY2-y1)//2 + 36
        gR  = 74

        # Arc background
        draw.arc([ecx-gR,ecy-gR,ecx+gR,ecy+gR], 145,35, fill=DGRAY, width=7)
        n1_c = cn(n1+i*0.2, corr*0.65, 4)
        try:    n1_v = float(n1_c)
        except: n1_v = n1
        n1_ang = 145 + (min(n1_v,110)/110)*250
        nc = (RED if n1_v>102 or corr>0.75 else AMBER if n1_v>96 else GREEN)
        draw.arc([ecx-gR,ecy-gR,ecx+gR,ecy+gR], 145, min(n1_ang,395), fill=nc, width=7)
        tc(draw, ecx, ecy+8, n1_c+"%", Fs[22], nc)
        tc(draw, ecx, ecy-gR-20, f"ENG{i+1}", Fr[13], LGRAY)
        egt_c = cn(egt+i*3, corr*0.5, 3)
        ec = AMBER if egt_c.isdigit() and int(egt_c)>720 else GREEN
        tc(draw, ecx, ecy+gR+14, f"EGT  {egt_c}°", Fr[13], ec)

    fuel = cn(18400, corr*0.25, 5)
    fc = AMBER if corr>0.65 else GREEN
    tc(draw, cx, UY2-20, f"FOB  {fuel} KG", Fr[14], fc)

    # ── LOWER — warnings ──────────────────────────────────────────────────
    box(draw, x1, LY1, x2, y2, fill=PANEL, outline=MGRAY, lw=2)
    tc(draw, cx, LY1+16, "SYS", Fr[13], LGRAY)

    # Build warning list
    msgs = []
    if t >= T_ANOMALY:
        msgs += [(DKAMB, AMBER, Fs[15], "ACARS 1  FAULT")]
    if t >= T_ANOMALY+0.4:
        msgs += [(None, CYAN, Fr[14], ">  MONITOR DATA LINK")]
    if t >= T_CAUTION:
        msgs += [(DKAMB, AMBER, Fs[15], "NAV DATA  DEGRADED")]
        msgs += [(None, CYAN, Fr[14], ">  CROSS-CHECK POSITION")]
    if t >= T_CAUTION+0.5:
        msgs += [(DKAMB, AMBER, Fs[15], "FMS  POSITION DOUBT")]
    if t >= T_WARNING:
        msgs = [(DKRED, RED, Fs[16], "DATA LINK  FAIL")] + msgs
        msgs = [(DKRED, RED, Fs[16], "NAV ACCURACY  LOST")] + msgs
        msgs += [(DKAMB, AMBER, Fs[15], "AUTOPILOT  DISC")]
        msgs += [(None, CYAN, Fr[14], ">  INITIATE DIVERT PROC")]
    if t >= T_DECISION:
        msgs = [(DKRED, RED, Fs[17], "CYBER INCIDENT  CONF")] + msgs
    if t >= T_DIVERT:
        msgs = [(DKRED, RED, Fs[18], "EMERGENCY  DECLARED")] + msgs
        msgs += [(DKAMB, AMBER, Fs[15], "SQUAWK  7700  SET")]
        msgs += [(None, CYAN, Fr[13], ">  DIVERT  CYQX/GANDER")]

    my = LY1 + 34
    for fill, col, f, txt in msgs[:11]:
        if my > y2-18: break
        bh = int(f.size * 1.6)
        if fill:
            blink_this = (col==RED and t>=T_WARNING and blink(t,1.4))
            show_bg = not blink_this or t>=T_DIVERT
            if show_bg:
                box(draw, x1+5, my-bh//2-3, x2-5, my+bh//2+3, fill=fill)
        tl(draw, x1+10, my, txt, f, col)
        my += bh + 8

# ═══════════════════════════════════════════════════════════════════════
# NAVIGATION DISPLAY
# ═══════════════════════════════════════════════════════════════════════
def draw_nd(frame, draw, t):
    x1,y1,x2,y2 = ND_R
    cx=rCX(ND_R); cy=rCY(ND_R)
    w=rW(ND_R);   h=rH(ND_R)
    corr   = sm(ph(t, T_ANOMALY, T_WARNING))
    severe = sm(ph(t, T_WARNING, T_DECISION))
    divert = ph(t, T_DIVERT, T_END)

    box(draw, x1, y1, x2, y2, fill=PANEL, outline=MGRAY, lw=2)

    arc_cx = cx
    arc_cy = y2 - 110
    arc_R  = min(h-150, w//2-24)

    # Compass background
    draw.arc([arc_cx-arc_R, arc_cy-arc_R, arc_cx+arc_R, arc_cy+arc_R],
             178, 362, fill=(20,20,28), width=arc_R-24)

    # Range rings
    for frac, lbl in [(0.35,"80NM"), (0.65,"160NM"), (1.0,"320NM")]:
        rr = int(arc_R*frac)
        draw.arc([arc_cx-rr, arc_cy-rr, arc_cx+rr, arc_cy+rr],
                 178, 362, fill=DGRAY, width=1)
        tr(draw, arc_cx+rr-4, arc_cy-6, lbl, Fr[11], DGRAY)

    # Compass ticks
    hdg = 286.0
    for tick in range(0, 360, 10):
        rel = ((tick-hdg)+180)%360-180
        if abs(rel) > 96: continue
        a_rad = math.radians(90-rel)
        is_30 = tick%30==0
        tlen = 22 if is_30 else 11
        tx1=arc_cx+int((arc_R-tlen)*math.cos(a_rad)); ty1=arc_cy-int((arc_R-tlen)*math.sin(a_rad))
        tx2=arc_cx+int(arc_R*math.cos(a_rad));       ty2=arc_cy-int(arc_R*math.sin(a_rad))
        draw.line([(tx1,ty1),(tx2,ty2)], fill=(WHITE if is_30 else LGRAY), width=(2 if is_30 else 1))
        if is_30:
            lx=arc_cx+int((arc_R-36)*math.cos(a_rad)); ly=arc_cy-int((arc_R-36)*math.sin(a_rad))
            lbl = str(tick//10) if tick>0 else "36"
            tc(draw, lx, ly, lbl, Fr[13], WHITE)

    draw.arc([arc_cx-arc_R, arc_cy-arc_R, arc_cx+arc_R, arc_cy+arc_R],
             178, 362, fill=WHITE, width=2)

    # ── Waypoints & route ─────────────────────────────────────────────────
    # Base positions (bearing offset, distance fraction)
    wps_base = [("MALOT",-76,0.80),("KESIX",-44,0.57),("DENDU",-8,0.32)]

    def wp_screen(hdg_off, dist_frac, t_corr=0):
        chaos = t_corr * 60
        ho = hdg_off + float(_rng.normal(0, t_corr*42))
        df = max(0.1, min(1.0, dist_frac + float(_rng.normal(0, t_corr*0.28))))
        a  = math.radians(90-ho)
        return (arc_cx+int(arc_R*df*math.cos(a)), arc_cy-int(arc_R*df*math.sin(a)))

    def cname(name, corr):
        if corr < 0.12: return name
        cs = list(name)
        for i in range(len(cs)):
            if _rng.random() < corr*0.75:
                cs[i] = chr(int(_rng.integers(65,91)))
        return "".join(cs)

    positions = [(n, wp_screen(ho, df, corr)) for n,ho,df in wps_base]

    # Route line
    prev = (arc_cx, arc_cy)
    for nm, (px,py) in positions:
        if y1<py<y2 and x1<px<x2:
            rc = (RED if severe>0.5 else AMBER if corr>0.4 else MAGENTA)
            draw.line([prev,(px,py)], fill=rc, width=3)
        prev = (px, py)

    # Divert path (new heading after divert)
    if divert > 0.1:
        div_ang = math.radians(90 - (hdg + 40*sm(divert)))  # turn right
        div_len = int(arc_R * 0.7 * sm(divert))
        div_end = (arc_cx+int(div_len*math.cos(div_ang)), arc_cy-int(div_len*math.sin(div_ang)))
        draw.line([(arc_cx,arc_cy), div_end], fill=CYAN, width=3)
        draw.line([(arc_cx,arc_cy-20),(div_end[0],div_end[1])], fill=CYAN, width=2)
        tc(draw, div_end[0]+40, div_end[1]-12, "CYQX", Fr[14], CYAN)
        tc(draw, div_end[0]+40, div_end[1]+8, "GANDER", Fr[11], CYAN)

    # Waypoint symbols
    for nm, (px,py) in positions:
        if not (y1+20<py<y2-20 and x1+20<px<x2-20): continue
        circ(draw, px, py, 7, outline=MAGENTA, lw=2)
        nc = RED if corr>0.5 else CYAN
        lbl = cname(nm, corr)
        tl(draw, px+12, py-10, lbl, Fr[14], nc)

    # Aircraft symbol
    asy = arc_cy - 12
    draw.line([(arc_cx-26,asy),(arc_cx-8,asy+8),(arc_cx,asy)], fill=YELLOW, width=3)
    draw.line([(arc_cx,asy),(arc_cx+8,asy+8),(arc_cx+26,asy)], fill=YELLOW, width=3)
    draw.line([(arc_cx-8,asy+18),(arc_cx+8,asy+18)], fill=YELLOW, width=3)
    circ(draw, arc_cx, asy, 5, fill=YELLOW)

    # Heading bug
    bug_a = math.radians(90)
    bx1=arc_cx+int((arc_R-5)*math.cos(bug_a)); by1=arc_cy-int((arc_R-5)*math.sin(bug_a))
    bx2=arc_cx+int((arc_R+5)*math.cos(bug_a)); by2=arc_cy-int((arc_R+5)*math.sin(bug_a))
    draw.line([(bx1,by1),(bx2,by2)], fill=CYAN, width=5)

    # ── ACARS packet stream visualizer ────────────────────────────────────
    # Small data-link visualization top-right of ND
    pk_x1 = x2-200; pk_x2 = x2-8
    pk_y1 = y1+8;   pk_y2 = y1+110
    box(draw, pk_x1, pk_y1, pk_x2, pk_y2, fill=(12,12,20), outline=MGRAY, lw=1)
    tc(draw, (pk_x1+pk_x2)//2, pk_y1+14, "ACARS DATA LINK", Fr[12], LGRAY)

    # Packet bars — animated
    n_pkts = 20
    pkt_w  = (pk_x2-pk_x1-10) // n_pkts
    for pi in range(n_pkts):
        px = pk_x1 + 5 + pi*pkt_w
        # Packet arrives at different times
        pkt_t = (t * 4 + pi * 0.3) % (n_pkts * 0.3)
        active = pkt_t < 0.25
        if active:
            corrupt_this = (corr > 0.1 and _rng.random() < corr)
            col = RED if corrupt_this else GREEN
            ph_ = 0.6 + 0.4*math.sin(t*8+pi)
            bh_ = int(ph_ * 28)
            box(draw, px, pk_y2-8-bh_, px+pkt_w-2, pk_y2-8, fill=col)
        else:
            box(draw, px, pk_y2-12, px+pkt_w-2, pk_y2-8, fill=DGRAY)

    # Link status
    if t < T_ANOMALY:
        link_col, link_txt = GREEN, "LINK OK"
    elif t < T_CAUTION:
        link_col, link_txt = AMBER, "DEGRADED"
    elif t < T_WARNING:
        link_col, link_txt = AMBER, "CORRUPT" if blink(t,3) else "ERROR"
    else:
        link_col, link_txt = RED, "LINK FAIL"
    tc(draw, (pk_x1+pk_x2)//2, pk_y2-30, link_txt, Fs[16], link_col)

    # Corner info
    tl(draw, x1+8, y1+18, f"ARC  HDG {cn(hdg, corr*0.25, 3)}°", Fr[14], WHITE)
    tr(draw, x2-8, y1+18, "320NM", Fr[14], LGRAY)
    wind_d = cn(258, corr*0.4, 3); wind_s = cn(62, corr*0.3, 2)
    tl(draw, x1+8, y2-28, f"W {wind_d}°/{wind_s}KT", Fr[12], LGRAY)
    tas_c = cn(490, corr*0.35, 3)
    tr(draw, x2-8, y2-28, f"TAS {tas_c}KT", Fr[12], LGRAY)

# ═══════════════════════════════════════════════════════════════════════
# NARRATIVE BEAT TEXT  (below displays)
# ═══════════════════════════════════════════════════════════════════════
BEATS = [
    (0.0,    1.5,  ""),
    (T_LABEL,2.5,  "Normal cruise — FL350 — North Atlantic — all systems nominal"),
    (T_ANOMALY, T_CAUTION,
                  "⚠  ACARS DATA LINK  —  CORRUPTED PACKETS DETECTED"),
    (T_CAUTION, T_WARNING,
                  "⚠  NAVIGATION DATA INTEGRITY COMPROMISED  —  POSITION UNVERIFIED"),
    (T_WARNING, T_DECISION,
                  "▲  MASTER WARNING  —  DATA LINK FAIL  —  NAV ACCURACY LOST"),
    (T_DECISION, T_DIVERT,
                  "◉  PILOTS UNABLE TO VERIFY AIRCRAFT POSITION  —  DECISION REQUIRED"),
    (T_DIVERT, T_HOLD,
                  "▶  EMERGENCY DIVERT INITIATED  —  SQUAWK 7700  —  ATC NOTIFIED"),
    (T_HOLD, T_FADE,
                  "CORRUPTED AVIONICS DATA STREAM  —  CYBER INCIDENT CONFIRMED"),
    (T_FADE, T_END,
                  ""),
]

def draw_narrative(draw, t):
    box(draw, 0, NAR_Y1, W, NAR_Y2, fill=(14,14,20))
    ln(draw, 0, NAR_Y1, W, NAR_Y1, MGRAY, 1)
    ln(draw, 0, NAR_Y2, W, NAR_Y2, MGRAY, 1)

    txt = ""
    col = WHITE
    for t0, t1, msg in BEATS:
        if t0 <= t < t1:
            txt = msg
            if "▲" in msg or "DATA LINK FAIL" in msg:
                col = RED if blink(t, 1.5) else AMBER
            elif "⚠" in msg or "COMPROMISED" in msg:
                col = AMBER
            elif "▶" in msg or "EMERGENCY" in msg:
                col = RED if blink(t, 1) else WHITE
            elif "CYBER" in msg:
                col = ORANGE if blink(t, 0.8) else RED
            else:
                col = LGRAY
            break

    if txt:
        ncy = (NAR_Y1 + NAR_Y2) // 2
        tc(draw, W//2, ncy, txt, Fs[22], col)

# ═══════════════════════════════════════════════════════════════════════
# PILOT DIALOGUE  (bottom strip — human stress element)
# ═══════════════════════════════════════════════════════════════════════
DIALOGUES = [
    # (start, end, speaker, callsign_color, text)
    (T_ANOMALY+0.3, T_CAUTION+0.2,
     "CPT", GREEN,
     '"ACARS is giving me garbage — cross-check your nav"'),
    (T_CAUTION+0.4, T_WARNING+0.2,
     "F/O", CYAN,
     '"Confirmed — FMS position is drifting, can\'t verify waypoints"'),
    (T_WARNING+0.3, T_DECISION+0.2,
     "CPT", GREEN,
     '"Autopilot out — hand-flying — we need to decide now"'),
    (T_DECISION+0.2, T_DIVERT+0.4,
     "F/O", CYAN,
     '"Unable to confirm position — I recommend we declare and divert Gander"'),
    (T_DIVERT+0.1, T_HOLD,
     "CPT", GREEN,
     '"MAYDAY MAYDAY MAYDAY — EUROLINK 421 — cyber incident — diverting CYQX"'),
    (T_HOLD, T_FADE+0.3,
     "F/O", CYAN,
     '"Gander in range — SQUAWK 7700 confirmed — they have us on radar"'),
]

def draw_dialogue(draw, t):
    box(draw, 0, DLG_Y1, W, DLG_Y2, fill=(10,10,16))
    ln(draw, 0, DLG_Y1, W, DLG_Y1, (40,40,50), 1)

    dcy = (DLG_Y1 + DLG_Y2) // 2

    active = [(s,e,sp,sc,tx) for s,e,sp,sc,tx in DIALOGUES if s <= t < e]
    if not active:
        return

    s0, e0, speaker, sc, txt = active[-1]
    dur = e0 - s0
    a_in  = sm(ph(t, s0, s0+0.3))
    a_out = 1.0 - sm(ph(t, e0-0.3, e0))
    alpha = min(a_in, a_out)
    if alpha < 0.02: return

    # Speaker tag
    tag_col = tuple(int(c*alpha) for c in sc)
    box(draw, 16, dcy-22, 80, dcy+22,
        fill=(int(sc[0]*0.2*alpha), int(sc[1]*0.2*alpha), int(sc[2]*0.2*alpha)),
        outline=tag_col, lw=2)
    tc(draw, 48, dcy, speaker, Fs[18], tag_col)

    # Dialogue text with typewriter effect
    progress = sm(ph(t, s0, s0 + min(1.5, dur*0.65)))
    n_chars = max(1, int(progress * len(txt)))
    partial = txt[:n_chars]

    txt_col = tuple(int(c*alpha) for c in WHITE)
    tl(draw, 96, dcy, partial, Fr[22], txt_col)

    # Blinking cursor while typing
    if n_chars < len(txt):
        tw_, _ = tbbox(draw, partial, Fr[22])
        if blink(t, 6):
            ln(draw, 96+tw_+3, dcy-14, 96+tw_+3, dcy+14, txt_col, 2)

# ═══════════════════════════════════════════════════════════════════════
# FULL-SCREEN DRAMATIC OVERLAY (key beats)
# ═══════════════════════════════════════════════════════════════════════
def draw_dramatic_overlay(draw, t):
    # Emergency divert declaration — massive
    if T_DIVERT <= t < T_HOLD:
        a = sm(ph(t, T_DIVERT, T_DIVERT+0.6))
        bh = 110
        oy = H//2 - bh - 20
        rc = (int(120*a), int(4*a), int(4*a))
        box(draw, 0, oy, W, oy+bh, fill=rc)
        ln(draw, 0, oy, W, oy, RED, 3)
        ln(draw, 0, oy+bh, W, oy+bh, RED, 3)
        if blink(t, 1.0) or a < 0.5:
            tc(draw, W//2, oy+bh//2,
               "ACARS DATA LINK CORRUPTED  —  CREW INITIATING EMERGENCY DIVERT",
               Fs[40], WHITE)

    # Cyber confirmed hold frame
    if T_HOLD <= t < T_FADE:
        hold_a = sm(ph(t, T_HOLD, T_HOLD+0.5))
        # Red border vignette frame
        bw_ = int(22*hold_a)
        box(draw, 0, 0, W, bw_, fill=DKRED)
        box(draw, 0, H-bw_, W, H, fill=DKRED)
        box(draw, 0, 0, bw_, H, fill=DKRED)
        box(draw, W-bw_, 0, W, H, fill=DKRED)

        oy = H//2 - 55
        box(draw, W//4, oy, 3*W//4, oy+110, fill=(80,6,6))
        ln(draw, W//4, oy,     3*W//4, oy,     RED, 3)
        ln(draw, W//4, oy+110, 3*W//4, oy+110, RED, 3)
        c_ = WHITE if blink(t, 1.2) else (200,200,200)
        tc(draw, W//2, oy+38, "CYBER ATTACK ON AVIONICS DATA STREAM", Fs[36], c_)
        tc(draw, W//2, oy+80, "POSITION UNVERIFIABLE  ·  EMERGENCY DIVERT ACTIVE", Fr[22], AMBER)

    # Citation / fade-out
    if t >= T_FADE:
        fade = sm(ph(t, T_FADE, T_FADE+0.5))
        over = (int(8*fade), int(8*fade), int(12*fade))
        box(draw, 0, 0, W, H, fill=over)

        lines = [
            ("SCENARIO BASED ON REAL EVENTS", Fs[32], WHITE),
            ("", None, None),
            ("Jan 11 2023 · FAA NOTAM database corrupted · First US nationwide ground stop since 9/11", Fr[18], LGRAY),
            ("ACARS data-link transmits in plaintext · Documented in peer-reviewed security research", Fr[18], LGRAY),
            ("Oct 2025 · Airbus A320 ELAC data corruption · Emergency rollback across 6,000 aircraft", Fr[18], LGRAY),
        ]
        ly = H//2 - 90
        for txt2, f, col in lines:
            if f is None: ly += 20; continue
            col2 = tuple(int(c*fade) for c in col)
            tc(draw, W//2, ly, txt2, f, col2)
            ly += int(f.size * 1.6)

# ═══════════════════════════════════════════════════════════════════════
# FOOTER
# ═══════════════════════════════════════════════════════════════════════
def draw_footer(draw, t):
    box(draw, 0, H-FTR_H, W, H, fill=(10,10,16))
    ln(draw, 0, H-FTR_H, W, H-FTR_H, (40,40,50), 1)
    corr = sm(ph(t, T_ANOMALY, T_WARNING))
    if corr > 0.05:
        hex_bytes = "".join(f" {_rng.integers(0,256):02X}" for _ in range(8))
        tl(draw, 12, H-FTR_H//2, f"ACARS RX ERR 0x{hex_bytes}", Fr[13], (int(180*corr),int(90*corr),0))
    tc(draw, W//2, H-FTR_H//2,
       "ELK421  ·  LEMD→KJFK  ·  FL350  ·  02:14 UTC",
       Fr[13], (60,60,70))
    tr(draw, W-12, H-FTR_H//2, "GATE SAFE VIDEO", Fr[12], (45,45,55))

# ═══════════════════════════════════════════════════════════════════════
# GLITCH EFFECTS
# ═══════════════════════════════════════════════════════════════════════
def apply_glitch(arr, t):
    corr   = sm(ph(t, T_ANOMALY, T_WARNING))
    severe = sm(ph(t, T_WARNING, T_DECISION))
    total  = corr * 0.55 + severe * 0.45

    if total < 0.02:
        return arr

    out = arr.copy()

    # Row displacement
    for _ in range(int(total * 32)):
        ry = int(_rng.integers(0, H))
        sh = int(_rng.integers(-int(80*total), int(80*total)+1))
        if sh == 0: continue
        row = out[ry].copy()
        if sh > 0:
            out[ry, sh:] = row[:W-sh]
            out[ry, :sh] = row[0]
        else:
            out[ry, :sh] = row[-sh:]
            out[ry, sh:] = row[-1]

    # Block displacement
    for _ in range(int(total * 8)):
        bx = int(_rng.integers(0, W-100)); by = int(_rng.integers(0, H-25))
        bw_ = int(_rng.integers(40, 160)); bh_ = int(_rng.integers(4, 24))
        sh  = int(_rng.integers(-50, 50))
        by2 = min(by+bh_, H); bx2 = min(bx+bw_, W)
        blk = out[by:by2, bx:bx2].copy()
        nx1 = bx+sh; nx2 = bx2+sh
        if 0 <= nx1 and nx2 <= W:
            out[by:by2, nx1:nx2] = blk

    # Chromatic aberration
    if total > 0.12:
        ca = int(total * 10)
        if ca > 0:
            out[:, ca:, 2]  = arr[:, :-ca, 2]
            out[:, :-ca, 0] = arr[:, ca:, 0]

    # Scan lines
    if total > 0.22:
        sl = min(0.5, total * 0.55)
        out[::3] = (out[::3] * (1-sl)).astype(np.uint8)

    # Noise pixels
    nn = int(total * 200)
    if nn > 0:
        ny = _rng.integers(0, H, nn)
        nx = _rng.integers(0, W, nn)
        nc = _rng.integers(0, 256, (nn, 3))
        out[ny, nx] = nc

    # Red vignette
    if severe > 0.25:
        vs = severe * 0.45
        vy_, vx_ = np.mgrid[0:H, 0:W]
        vd = np.sqrt(((vx_-W/2)/(W/2))**2 + ((vy_-H/2)/(H/2))**2)
        vm = np.clip(vd * vs, 0, 0.65)[:, :, np.newaxis]
        rt = np.array([0, 0, 120], dtype=np.float32)
        out = (out.astype(np.float32)*(1-vm) + rt*vm).astype(np.uint8)

    return out

# ═══════════════════════════════════════════════════════════════════════
# FRAME RENDERER
# ═══════════════════════════════════════════════════════════════════════
def render_frame(t):
    frame = Image.new("RGB", (W, H), BG)
    draw  = ImageDraw.Draw(frame)

    draw_header(draw, t)
    draw_footer(draw, t)
    draw_display_labels(draw, t)
    draw_pfd(frame, draw, t)
    draw_ecam(draw, t)
    draw_nd(frame, draw, t)
    draw_narrative(draw, t)
    draw_dialogue(draw, t)
    draw_dramatic_overlay(draw, t)

    arr = cv2.cvtColor(np.array(frame), cv2.COLOR_RGB2BGR)
    arr = apply_glitch(arr, t)
    return arr

# ═══════════════════════════════════════════════════════════════════════
# AUDIO
# ═══════════════════════════════════════════════════════════════════════
def sine(freq, dur, amp=0.8):
    t_ = np.linspace(0, dur, int(SRATE*dur), endpoint=False)
    return amp * np.sin(2*np.pi*freq*t_)

def env(sig, atk=0.006, rel=0.018):
    n=len(sig); a_=int(SRATE*atk); r_=int(SRATE*rel)
    e=np.ones(n)
    if a_>0: e[:a_]=np.linspace(0,1,a_)
    if r_>0: e[n-r_:]=np.linspace(1,0,r_)
    return sig*e

def silence(dur): return np.zeros(int(SRATE*dur))

def generate_audio():
    audio = np.zeros(int(SRATE * DUR))

    def place(sig, t0):
        i=int(t0*SRATE); end=min(i+len(sig), len(audio))
        audio[i:end] += sig[:end-i]

    # Background cockpit hum (engine noise, avionics fan)
    t_ = np.linspace(0, DUR, int(SRATE*DUR), endpoint=False)
    hum  = 0.055*np.sin(2*np.pi*185*t_)
    hum += 0.030*np.sin(2*np.pi*370*t_)
    hum += 0.015*np.sin(2*np.pi*740*t_)
    hum += 0.008*_rng.normal(0, 1, len(t_))   # slight white noise (fan)
    audio += hum

    # MASTER CAUTION chime: double ding — t=2.8
    ding_hi = env(sine(830, 0.10, 0.82), atk=0.004, rel=0.020)
    ding_lo = env(sine(755, 0.13, 0.50), atk=0.004, rel=0.025)
    for k in range(2):
        place(ding_hi, T_CAUTION + k*0.20)
        place(ding_lo, T_CAUTION + k*0.20 + 0.015)

    # MASTER WARNING: triple chime — t=4.2
    warn_hi = env(sine(1040, 0.08, 0.96), atk=0.003, rel=0.015)
    warn_lo = env(sine(770, 0.10, 0.55),  atk=0.003, rel=0.018)
    for k in range(3):
        place(warn_hi, T_WARNING + k*0.16)
        place(warn_lo, T_WARNING + k*0.16 + 0.010)

    # Continuous alternating warning from T_WARNING to T_DIVERT
    tc_ = T_WARNING + 0.60
    tog = True
    while tc_ < T_DIVERT - 0.15:
        freq = 900 if tog else 660
        chunk = env(sine(freq, 0.20, 0.58), atk=0.010, rel=0.030)
        place(chunk, tc_)
        tc_ += 0.24
        tog = not tog

    # Urgency escalation chime when divert declared
    for k, f in enumerate([880, 1100, 1320]):
        place(env(sine(f, 0.12, 0.80), atk=0.006, rel=0.020), T_DIVERT + k*0.14)

    # Single resolve tone at end of divert
    place(env(sine(550, 0.35, 0.5), atk=0.01, rel=0.05), T_HOLD + 0.2)

    # Normalize
    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = audio / peak * 0.90
    return audio

def save_audio(audio, path):
    pcm = (audio * 32767).astype(np.int16)
    import wave as _w
    with _w.open(path, 'w') as wf:
        wf.setnchannels(1); wf.setsampwidth(2)
        wf.setframerate(SRATE); wf.writeframes(pcm.tobytes())

# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════
def main():
    print(f"Rendering {NF} frames  {DUR}s  {W}×{H}  {FPS}fps")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(TMP_V, fourcc, FPS, (W, H))
    for fi in range(NF):
        t = fi / FPS
        vw.write(render_frame(t))
        if fi % 60 == 0:
            print(f"  {fi}/{NF}  t={t:.1f}s")
    vw.release()
    print(f"Video → {TMP_V}")

    print("Generating audio...")
    save_audio(generate_audio(), TMP_A)
    print(f"Audio → {TMP_A}")

    print("Muxing...")
    r = subprocess.run([
        "ffmpeg", "-y",
        "-i", TMP_V, "-i", TMP_A,
        "-c:v", "libx264", "-crf", "17", "-preset", "fast",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", OUT
    ], capture_output=True, text=True)
    if r.returncode != 0:
        print("ffmpeg err:", r.stderr[-600:])
    else:
        sz = os.path.getsize(OUT) / 1e6
        print(f"Done → {OUT}  ({sz:.1f} MB)")

if __name__ == "__main__":
    main()
