#!/usr/bin/env python3
"""
AIRBUS A321neo — CYBERSECURITY EMERGENCY VIDEO
ELK421  LEMD → KJFK  |  FL350  |  North Atlantic  |  ACARS DATA LINK COMPROMISED

Inspired by real events:
  • Jan 11 2023: FAA NOTAM system data corruption caused first US nationwide
    ground stop since 9/11 — primary AND backup databases both corrupted
  • Documented ACARS unencrypted data-link vulnerabilities: messages sent in
    plain text over VHF radio, low barrier to inject/corrupt (academic research)
  • Oct 2025: Airbus A320 ELAC flight-control data corruption incident requiring
    emergency software rollback across ~6,000 aircraft
"""
import os, math, wave, struct, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import cv2

# ═══════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════
W, H   = 1920, 1080
FPS    = 30
DUR    = 6.5
NF     = int(FPS * DUR)     # 195 frames
SRATE  = 44100

OUT   = "/home/user/GATE-SAFE-VIDEO/cockpit_emergency.mp4"
TMP_V = "/tmp/ck_raw.mp4"
TMP_A = "/tmp/ck_audio.wav"

# ═══════════════════════════════════════════════════════════════════════════
# TIMELINE  (seconds)
# ═══════════════════════════════════════════════════════════════════════════
T_ANOMALY = 1.1     # first subtle data flicker
T_CAUTION = 2.0     # MASTER CAUTION fires
T_WARNING = 3.4     # MASTER WARNING — DATA LINK FAIL
T_DIVERT  = 5.0     # crew initiates emergency divert
T_CITE    = 5.8     # citation appears
T_END     = 6.5

# ═══════════════════════════════════════════════════════════════════════════
# PALETTE  (RGB)
# ═══════════════════════════════════════════════════════════════════════════
BG       = (10,  10,  14)
PANEL    = (20,  20,  26)
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
DKRED    = ( 80,   8,   8)
DKAMB    = ( 70,  44,   0)
BLACK    = (  0,   0,   0)

# ═══════════════════════════════════════════════════════════════════════════
# LAYOUT  (x1, y1, x2, y2)
# ═══════════════════════════════════════════════════════════════════════════
HDR_H = 52
FTR_H = 38
PAD   = 8
DY1   = HDR_H + PAD          # y start of display area
DY2   = H - FTR_H - PAD     # y end   of display area

PFD_R  = (PAD,  DY1, 748,   DY2)   # w=740
ECAM_R = (756,  DY1, 1162,  DY2)   # w=406
ND_R   = (1170, DY1, W-PAD, DY2)   # w=742

def rW(r): return r[2]-r[0]
def rH(r): return r[3]-r[1]
def rCX(r): return (r[0]+r[2])//2
def rCY(r): return (r[1]+r[3])//2

# ═══════════════════════════════════════════════════════════════════════════
# FONTS
# ═══════════════════════════════════════════════════════════════════════════
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

Fs = {sz: F(sz, True)  for sz in [10,12,14,16,18,20,22,24,28,32,36,40,48,56,64,72,80]}
Fr = {sz: F(sz, False) for sz in [10,11,12,13,14,15,16,18,20,22,24,28,32,36]}

# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def ph(t, t0, t1):
    if t1 <= t0: return float(t >= t0)
    return max(0., min(1., (t-t0)/(t1-t0)))

def sm(p): return p*p*(3-2*p)
def lerp(a, b, p): return a + (b-a)*p
def blink(t, hz=2): return math.sin(t * hz * math.pi * 2) > 0

_rng = np.random.default_rng(42)

def corrupt_num(val, corr, n=3):
    if corr < 0.04: return str(int(val))
    if _rng.random() < corr * 0.65:
        spread = max(2, int(abs(val) * 0.06 * corr))
        off = int(_rng.integers(-spread, spread+1))
        return str(int(val) + off)
    if _rng.random() < corr * 0.5:
        return "".join(str(_rng.integers(0, 10)) for _ in range(n))
    return str(int(val))

def tbbox(draw, txt, f):
    bb = draw.textbbox((0, 0), txt, font=f)
    return bb[2]-bb[0], bb[3]-bb[1]

def tc(draw, cx, cy, txt, f, fill):
    w, h = tbbox(draw, txt, f)
    draw.text((cx-w//2, cy-h//2), txt, font=f, fill=fill)

def tl(draw, x, cy, txt, f, fill):
    _, h = tbbox(draw, txt, f)
    draw.text((x, cy-h//2), txt, font=f, fill=fill)

def tr(draw, rx, cy, txt, f, fill):
    w, h = tbbox(draw, txt, f)
    draw.text((rx-w, cy-h//2), txt, font=f, fill=fill)

def box(draw, x1, y1, x2, y2, fill=None, outline=None, lw=1):
    draw.rectangle([x1, y1, x2, y2], fill=fill, outline=outline, width=lw)

def ln(draw, x1, y1, x2, y2, fill=WHITE, w=1):
    draw.line([(x1, y1), (x2, y2)], fill=fill, width=w)

def circ(draw, cx, cy, r, fill=None, outline=None, lw=1):
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=fill, outline=outline, width=lw)

# ═══════════════════════════════════════════════════════════════════════════
# ADI  (Attitude Director Indicator)
# ═══════════════════════════════════════════════════════════════════════════
def make_adi(R, pitch, roll):
    """Return RGBA PIL image (2R × 2R) of the horizon sphere."""
    D  = R * 2
    S  = int(D * 1.45) + 10   # working canvas (for rotation headroom)
    cx = S // 2

    adi = Image.new("RGB", (S, S), SKY_C)
    ad  = ImageDraw.Draw(adi)

    ppd    = R / 22.0          # pixels per degree of pitch
    hy     = cx + int(pitch * ppd)   # horizon y in unrotated frame

    # Ground fill
    if hy < S:
        ad.rectangle([0, max(0, hy), S, S], fill=GND_C)

    # Horizon line
    ad.rectangle([0, hy-3, S, hy+3], fill=HRZ_C)

    # Pitch ladder
    for deg in range(-30, 31, 5):
        if deg == 0:
            continue
        y   = int(hy - deg * ppd)
        if not (4 < y < S-4):
            continue
        bw  = int(R * (0.44 if abs(deg) % 10 == 0 else 0.24))
        lw  = 2 if abs(deg) % 10 == 0 else 1
        ad.rectangle([cx-bw, y-lw, cx+bw, y+lw], fill=WHITE)
        if abs(deg) % 10 == 0 and bw > 18:
            lbl = str(abs(deg))
            ad.text((cx-bw-26, y-9), lbl, font=Fs[12], fill=WHITE)
            ad.text((cx+bw+4,  y-9), lbl, font=Fs[12], fill=WHITE)

    # Rotate for roll angle
    adi_r = adi.rotate(-roll, center=(cx, cx), expand=False, fillcolor=SKY_C)

    # Crop to D×D from center
    off = (S - D) // 2
    adi_c = adi_r.crop([off, off, off+D, off+D])

    # Circular mask
    mask = Image.new("L", (D, D), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, D-1, D-1], fill=255)

    out = Image.new("RGBA", (D, D), (0, 0, 0, 0))
    out.paste(adi_c, (0, 0), mask=mask)
    return out

# ═══════════════════════════════════════════════════════════════════════════
# HEADER & FOOTER
# ═══════════════════════════════════════════════════════════════════════════
def draw_header(draw, t):
    corr   = sm(ph(t, T_ANOMALY, T_WARNING))
    severe = sm(ph(t, T_WARNING, T_DIVERT))

    box(draw, 0, 0, W, HDR_H, fill=(14, 14, 20))
    ln(draw, 0, HDR_H-2, W, HDR_H-2, MGRAY, 2)

    # Left: callsign + aircraft type
    tl(draw, 12, HDR_H//2, "ELK421", Fs[28], GREEN)
    tl(draw, 130, HDR_H//2, "EUROLINK 421", Fr[18], LGRAY)

    # Center: route
    route_col = AMBER if corr > 0.2 else WHITE
    tc(draw, W//2, HDR_H//2, "LEMD  ──  KJFK", Fs[22], route_col)

    # Flight phase
    fl_txt = corrupt_num(350, corr*0.3, 3)
    fl_col = AMBER if corr > 0.4 else CYAN
    tc(draw, W//2 + 280, HDR_H//2, f"FL{fl_txt}", Fs[22], fl_col)

    # Right: time / squawk
    if t >= T_DIVERT:
        sq_col = RED if blink(t, 2) else DKRED
        tr(draw, W-12, HDR_H//2, "SQUAWK 7700", Fs[24], sq_col)
    else:
        sq_col = AMBER if severe > 0.3 else LGRAY
        tr(draw, W-12, HDR_H//2, "A321neo  |  ACARS", Fr[18], sq_col)

def draw_footer(draw, t):
    box(draw, 0, H-FTR_H, W, H, fill=(10, 10, 16))
    ln(draw, 0, H-FTR_H, W, H-FTR_H, MGRAY, 1)

    corr = sm(ph(t, T_ANOMALY, T_WARNING))
    if corr > 0.05:
        corrupt_msg = "ACARS RX: ERR 0x" + "".join(
            f"{_rng.integers(0,256):02X}" for _ in range(4))
        tl(draw, 12, H - FTR_H//2, corrupt_msg, Fr[14], AMBER)

    tc(draw, W//2, H - FTR_H//2,
       "Inspired by the 2023 FAA NOTAM Data Corruption Incident & ACARS Vulnerability Research",
       Fr[12], MGRAY)

# ═══════════════════════════════════════════════════════════════════════════
# PRIMARY FLIGHT DISPLAY
# ═══════════════════════════════════════════════════════════════════════════
def draw_pfd(frame, draw, t):
    x1, y1, x2, y2 = PFD_R
    cx = rCX(PFD_R)

    corr   = sm(ph(t, T_ANOMALY, T_WARNING))
    severe = sm(ph(t, T_WARNING, T_DIVERT))
    divert = ph(t, T_DIVERT, T_END)

    # Panel background
    box(draw, x1, y1, x2, y2, fill=PANEL, outline=MGRAY, lw=2)

    FMA_H = 72

    # ── FMA ─────────────────────────────────────────────────────────────────
    box(draw, x1, y1, x2, y1+FMA_H, fill=(16, 16, 24), outline=MGRAY, lw=1)

    fma_items = [
        ("A/THR", GREEN, 0),
        ("OP CLB", GREEN, 0),
        ("NAV",   CYAN,  1),   # index 2 = NAV mode (will corrupt)
        ("--",    MGRAY, 0),
        ("AP1",   GREEN, 0),
    ]
    cw = (x2-x1) // 5
    for i, (lbl, col, is_nav) in enumerate(fma_items):
        fcx = x1 + i*cw + cw//2
        fcy = y1 + FMA_H//2

        if is_nav and corr > 0.1:
            col = AMBER if blink(t, 4) else RED
            lbl = "NAV FAIL" if severe > 0.5 else "NAV DEGR"
        if i == 4 and severe > 0.6:
            col = AMBER
            lbl = "AP OFF"

        tc(draw, fcx, fcy, lbl, Fs[20], col)

        if i < 4:
            ln(draw, x1+(i+1)*cw, y1+6, x1+(i+1)*cw, y1+FMA_H-6, MGRAY, 1)

    # ── SPEED TAPE ──────────────────────────────────────────────────────────
    SX1 = x1 + 4;   SX2 = x1 + 92
    SY1 = y1 + FMA_H + 4;  SY2 = y2 - 108
    SH  = SY2 - SY1
    SCX = (SX1 + SX2) // 2
    SCY = (SY1 + SY2) // 2

    box(draw, SX1, SY1, SX2, SY2, fill=(16, 16, 22))

    spd = 480 + 10 * math.sin(t * 0.35)
    spd_txt = corrupt_num(spd, corr * 0.9, 3)
    spd_col = AMBER if corr > 0.3 else WHITE
    if corr > 0.6: spd_col = RED

    # Tape ticks
    for ds in range(-50, 51, 10):
        ty = SCY - int(ds * SH / 180)
        if SY1 + 4 < ty < SY2 - 4:
            ln(draw, SX2-22, ty, SX2-4, ty, LGRAY, 1)
            sv = int(spd + ds)
            if sv > 0:
                tr(draw, SX2-24, ty, str(sv), Fr[11], LGRAY)

    # Speed box
    box(draw, SX1+2, SCY-26, SX2-2, SCY+26, fill=BLACK, outline=WHITE, lw=2)
    tc(draw, SCX, SCY, spd_txt, Fs[28], spd_col)

    # VLS / VSW markers (amber/red lines on tape)
    vls_y = SCY + int(20 * SH / 180)
    ln(draw, SX1+4, vls_y, SX2-4, vls_y, AMBER, 2)

    # Speed trend arrow
    trend_len = int(5 * SH / 180)
    draw.polygon([(SX2-6, SCY-trend_len), (SX2-2, SCY), (SX2-6, SCY)],
                 fill=GREEN)

    # ── ALTITUDE TAPE ───────────────────────────────────────────────────────
    AX1 = x2 - 104;  AX2 = x2 - 4
    AY1 = y1 + FMA_H + 4;  AY2 = y2 - 108
    AH  = AY2 - AY1
    ACX = (AX1 + AX2) // 2
    ACY = (AY1 + AY2) // 2

    box(draw, AX1, AY1, AX2, AY2, fill=(16, 16, 22))

    alt = 35000 + 80 * math.sin(t * 0.22)
    alt_txt = corrupt_num(alt, corr * 0.55, 5)
    alt_col = AMBER if corr > 0.4 else WHITE
    if severe > 0.5: alt_col = RED

    # Tape ticks every 500 ft
    for da in range(-4000, 4001, 500):
        ty = ACY - int(da * AH / 14000)
        if AY1 + 4 < ty < AY2 - 4:
            ln(draw, AX1+4, ty, AX1+22, ty, LGRAY, 1)
            av = int(alt + da)
            if av % 1000 == 0:
                tl(draw, AX1+26, ty, str(av), Fr[10], LGRAY)

    # Alt box
    box(draw, AX1+2, ACY-26, AX2-2, ACY+26, fill=BLACK, outline=WHITE, lw=2)
    tc(draw, ACX, ACY, alt_txt, Fs[24], alt_col)

    # Target altitude
    tgt_alt = 35000 if divert < 0.05 else int(lerp(35000, 15000, sm(divert)))
    tgt_y = ACY - int((tgt_alt - alt) * AH / 14000)
    if AY1 < tgt_y < AY2:
        ln(draw, AX1-2, tgt_y, AX2+2, tgt_y, CYAN, 2)
    tgt_txt = corrupt_num(tgt_alt, corr*0.2, 5)
    tl(draw, AX1+2, AY1+18, tgt_txt, Fr[14], CYAN)

    # VS (vertical speed)
    vs = 0 + int(divert * -1800)
    vs_str = ("+" if vs >= 0 else "") + str(vs) + " FT/M"
    vs_col = CYAN if vs == 0 else GREEN
    if vs < -500: vs_col = AMBER
    tr(draw, AX2-2, AY2-18, vs_str, Fr[12], vs_col)

    # ── ADI ─────────────────────────────────────────────────────────────────
    AIX1 = SX2 + 4;  AIX2 = AX1 - 4
    AIY1 = y1 + FMA_H + 4;  AIY2 = y2 - 108
    AICX = (AIX1 + AIX2) // 2
    AICY = (AIY1 + AIY2) // 2
    AIR  = min((AIX2-AIX1)//2 - 6, (AIY2-AIY1)//2 - 6)

    pitch = 2.2 + math.sin(t * 0.38) * 0.6 - divert * 4
    roll  = math.sin(t * 0.28) * 1.8 - divert * 20

    adi_img = make_adi(AIR, pitch, roll)
    frame.paste(adi_img, (AICX - AIR, AICY - AIR), adi_img)

    # ADI border
    draw.ellipse([AICX-AIR-2, AICY-AIR-2, AICX+AIR+2, AICY+AIR+2],
                 outline=MGRAY, width=3)

    # If severe: red X on ADI
    if severe > 0.72 and blink(t, 3):
        r2 = AIR - 6
        ln(draw, AICX-r2, AICY-r2, AICX+r2, AICY+r2, RED, 5)
        ln(draw, AICX+r2, AICY-r2, AICX-r2, AICY+r2, RED, 5)

    # Aircraft symbol (fixed W, always center)
    sw = AIR // 2
    sym_pts_l = [(AICX-sw, AICY), (AICX-sw//3, AICY+sw//5), (AICX, AICY)]
    sym_pts_r = [(AICX, AICY), (AICX+sw//3, AICY+sw//5), (AICX+sw, AICY)]
    draw.line(sym_pts_l, fill=YELLOW, width=4)
    draw.line(sym_pts_r, fill=YELLOW, width=4)
    circ(draw, AICX, AICY, 5, fill=YELLOW)

    # FPV (flight path vector) bird
    fpv_x = AICX + int(roll * 1.5)
    fpv_y = AICY - int(pitch * AIR / 22)
    if AIY1 < fpv_y < AIY2 and AIX1 < fpv_x < AIX2:
        circ(draw, fpv_x, fpv_y, 8, outline=GREEN, lw=2)
        ln(draw, fpv_x-20, fpv_y, fpv_x+20, fpv_y, GREEN, 2)
        ln(draw, fpv_x, fpv_y, fpv_x, fpv_y-14, GREEN, 2)

    # Roll arc + ticks
    arc_r = AIR + 14
    for deg in [-60, -45, -30, -20, -10, 10, 20, 30, 45, 60]:
        a_rad = math.radians(90 + deg)
        tl_ = 14 if abs(deg) in [30, 60] else 8
        tx1 = AICX + int((arc_r-tl_)*math.cos(a_rad))
        ty1 = AICY - int((arc_r-tl_)*math.sin(a_rad))
        tx2 = AICX + int(arc_r*math.cos(a_rad))
        ty2 = AICY - int(arc_r*math.sin(a_rad))
        draw.line([(tx1, ty1), (tx2, ty2)], fill=WHITE, width=1)

    # Roll index
    ridx_a = math.radians(90 + roll)
    ridx_r = arc_r - 8
    rx = AICX + int(ridx_r * math.cos(ridx_a))
    ry = AICY - int(ridx_r * math.sin(ridx_a))
    circ(draw, rx, ry, 5, fill=YELLOW)

    # MASTER CAUTION / WARNING flag on PFD
    if t >= T_CAUTION:
        if t >= T_WARNING:
            fc = RED if blink(t, 2) else DKRED
            ft = "MASTER WARNING"
        else:
            fc = AMBER if blink(t, 2) else DKAMB
            ft = "MASTER CAUTION"
        box(draw, x1+6, y1+FMA_H+6, x1+210, y1+FMA_H+38, fill=fc, outline=WHITE, lw=1)
        tl(draw, x1+10, y1+FMA_H+22, ft, Fs[14], WHITE)

    # ── HEADING SCALE ───────────────────────────────────────────────────────
    HY1 = y2 - 106;  HY2 = y2 - 6
    HCY = (HY1 + HY2) // 2

    box(draw, x1+4, HY1, x2-4, HY2, fill=(16, 16, 24))

    hdg = 286.4 + math.sin(t * 0.18) * 0.4
    hdg_txt = corrupt_num(hdg, corr * 0.35, 3)

    hscale_w = (x2-x1-20)
    for dh in range(-40, 41, 10):
        tx = cx + int(dh * hscale_w / 140)
        if x1+8 < tx < x2-8:
            ln(draw, tx, HY1+8, tx, HY1+22, LGRAY, 1)
            hv = int(hdg + dh) % 360
            tc(draw, tx, HY1+34, str(hv), Fr[11], LGRAY)
        if dh % 20 == 0 and x1+8 < tx < x2-8:
            ln(draw, tx, HY1+8, tx, HY1+28, WHITE, 2)

    # Heading box
    box(draw, cx-40, HY1+4, cx+40, HY2-4, fill=BLACK, outline=WHITE, lw=2)
    tc(draw, cx, HCY, hdg_txt + "°", Fs[24], WHITE)

# ═══════════════════════════════════════════════════════════════════════════
# ECAM  (Electronic Centralized Aircraft Monitor)
# ═══════════════════════════════════════════════════════════════════════════
def draw_ecam(draw, t):
    x1, y1, x2, y2 = ECAM_R
    cx = rCX(ECAM_R)
    w  = rW(ECAM_R)

    corr   = sm(ph(t, T_ANOMALY, T_WARNING))
    severe = sm(ph(t, T_WARNING, T_DIVERT))
    divert = ph(t, T_DIVERT, T_END)

    UY2 = y1 + (y2-y1)//2 - 3    # upper panel bottom
    LY1 = UY2 + 6                # lower panel top

    # ── ECAM UPPER — engine parameters ──────────────────────────────────────
    box(draw, x1, y1, x2, UY2, fill=PANEL, outline=MGRAY, lw=2)
    tc(draw, cx, y1+20, "ENGINE", Fr[14], LGRAY)

    n1 = 88.4 + math.sin(t * 0.4) * 0.3
    egt = 650 + int(math.sin(t * 0.3) * 8)

    for i, label in enumerate(["ENG 1", "ENG 2"]):
        ecx = x1 + w//4 + i*(w//2)
        ecy = y1 + (UY2-y1)//2 + 30

        # N1 arc gauge
        gR = 90
        # Background arc
        draw.arc([ecx-gR, ecy-gR, ecx+gR, ecy+gR], 150, 30, fill=MGRAY, width=8)

        n1_c = corrupt_num(n1, corr*0.6, 4) if i == 0 else corrupt_num(n1+0.2, corr*0.4, 4)
        n1_v = float(n1_c) if n1_c.replace('.','').isdigit() else n1
        n1_ang = 150 + (n1_v / 100) * 240
        n1_color = RED if n1_v > 100 or (corr > 0.7) else GREEN
        draw.arc([ecx-gR, ecy-gR, ecx+gR, ecy+gR], 150, min(n1_ang, 390), fill=n1_color, width=8)

        # N1 value
        tc(draw, ecx, ecy+10, n1_c + "%", Fs[24], n1_color)
        tc(draw, ecx, ecy-gR-18, label, Fr[14], LGRAY)

        # EGT / FF below
        egt_c = corrupt_num(egt + i*3, corr*0.45, 3)
        egt_col = AMBER if (egt_c.isdigit() and int(egt_c) > 700) else GREEN
        tc(draw, ecx, ecy+gR+10, f"EGT {egt_c}°", Fr[14], egt_col)
        ff_c = corrupt_num(2840 + i*15, corr*0.5, 4)
        tc(draw, ecx, ecy+gR+32, f"FF  {ff_c}", Fr[13], LGRAY)

    # Fuel qty
    fuel = corrupt_num(18400, corr*0.3, 5)
    fc = AMBER if corr > 0.6 else GREEN
    tc(draw, cx, UY2-22, f"FUEL  {fuel} KG", Fr[15], fc)

    # ── ECAM LOWER — system warnings ────────────────────────────────────────
    box(draw, x1, LY1, x2, y2, fill=PANEL, outline=MGRAY, lw=2)
    tc(draw, cx, LY1+20, "SYS", Fr[14], LGRAY)

    msgs = []   # (fill_color, text_color, text)
    if t >= T_ANOMALY:
        msgs.append((DKAMB, AMBER, "ACARS 1  FAULT"))
    if t >= T_CAUTION:
        msgs.append((DKAMB, AMBER, "NAV DATA  DEGRADED"))
        msgs.append((None,  CYAN,  "×  CROSS-CHECK NAV"))
    if t >= T_WARNING:
        msgs.insert(0, (DKRED, RED,   "DATA LINK  FAIL"))
        msgs.insert(1, (DKRED, RED,   "NAV ACCURACY  LOST"))
        msgs.append((DKAMB, AMBER, "AUTOPILOT  DISC"))
        msgs.append((None,  CYAN,  "×  INITIATE DIVERT"))
    if t >= T_DIVERT:
        msgs.insert(0, (DKRED, RED, "EMERGENCY DECLARED"))
        msgs.append((DKAMB, AMBER, "SQUAWK  7700"))

    msg_y = LY1 + 38
    for fill, col, txt in msgs[:9]:
        if msg_y > y2 - 20:
            break
        if fill:
            box(draw, x1+6, msg_y-14, x2-6, msg_y+14, fill=fill)
        # Blink critical messages
        show = True
        if col == RED and t >= T_WARNING:
            show = blink(t, 1.5)
        if show:
            tl(draw, x1+12, msg_y, txt, Fs[16], col)
        msg_y += 34

# ═══════════════════════════════════════════════════════════════════════════
# NAVIGATION DISPLAY
# ═══════════════════════════════════════════════════════════════════════════
def draw_nd(frame, draw, t):
    x1, y1, x2, y2 = ND_R
    cx = rCX(ND_R)
    cy = rCY(ND_R)
    w  = rW(ND_R)
    h  = rH(ND_R)

    corr   = sm(ph(t, T_ANOMALY, T_WARNING))
    severe = sm(ph(t, T_WARNING, T_DIVERT))

    box(draw, x1, y1, x2, y2, fill=PANEL, outline=MGRAY, lw=2)

    # ARC mode: aircraft at bottom-center, compass arc above
    arc_cx = cx
    arc_cy = y2 - 120       # compass origin (below center)
    arc_R  = min(h - 160, w//2 - 20)

    # ── Compass arc background ───────────────────────────────────────────────
    draw.arc([arc_cx-arc_R, arc_cy-arc_R, arc_cx+arc_R, arc_cy+arc_R],
             180, 360, fill=(26, 26, 34), width=arc_R-20)

    # ── Range rings ──────────────────────────────────────────────────────────
    for frac, label in [(0.33, "80"), (0.66, "160"), (1.0, "320")]:
        rr = int(arc_R * frac)
        # Draw quarter-circle arc (top half only)
        draw.arc([arc_cx-rr, arc_cy-rr, arc_cx+rr, arc_cy+rr],
                 180, 360, fill=DGRAY, width=1)
        # Label
        tl(draw, arc_cx+rr+4, arc_cy, label, Fr[12], MGRAY)

    # ── Compass ticks ────────────────────────────────────────────────────────
    hdg = 286.0
    for tick_deg in range(0, 360, 10):
        rel = (tick_deg - hdg) % 360
        if rel > 180: rel -= 360
        if abs(rel) > 95: continue
        a_rad = math.radians(90 - rel)
        is_30 = tick_deg % 30 == 0
        tl_ = 20 if is_30 else 10
        tx1 = arc_cx + int((arc_R-tl_)*math.cos(a_rad))
        ty1 = arc_cy - int((arc_R-tl_)*math.sin(a_rad))
        tx2 = arc_cx + int(arc_R*math.cos(a_rad))
        ty2 = arc_cy - int(arc_R*math.sin(a_rad))
        draw.line([(tx1,ty1),(tx2,ty2)], fill=LGRAY, width=2 if is_30 else 1)
        if is_30:
            lx = arc_cx + int((arc_R-32)*math.cos(a_rad))
            ly = arc_cy - int((arc_R-32)*math.sin(a_rad))
            lbl = str(tick_deg // 10) if tick_deg > 0 else "36"
            tc(draw, lx, ly, lbl, Fr[12], WHITE)

    # Compass arc border
    draw.arc([arc_cx-arc_R, arc_cy-arc_R, arc_cx+arc_R, arc_cy+arc_R],
             180, 360, fill=WHITE, width=2)

    # ── Route & waypoints ────────────────────────────────────────────────────
    # Normal waypoints on North Atlantic track
    waypoints_normal = [
        ("MALOT", -82, 0.82),
        ("KESIX", -58, 0.60),
        ("DENDU",  -8, 0.36),
    ]

    def wp_pos(rel_hdg_offset, dist_frac):
        """Relative position from aircraft."""
        a = math.radians(90 - rel_hdg_offset)
        px = arc_cx + int(arc_R * dist_frac * math.cos(a))
        py = arc_cy - int(arc_R * dist_frac * math.sin(a))
        return px, py

    def corrupt_wp_name(name, corr):
        if corr < 0.15: return name
        chars = list(name)
        for i in range(len(chars)):
            if _rng.random() < corr * 0.7:
                chars[i] = chr(int(_rng.integers(65, 91)))
        return "".join(chars)

    positions = []
    for name, hdg_off, dist in waypoints_normal:
        # Corrupt position offsets
        c_hdg = hdg_off + _rng.normal(0, corr * 40)
        c_dist = dist + _rng.normal(0, corr * 0.3)
        c_dist = max(0.1, min(1.0, c_dist))
        px, py = wp_pos(c_hdg, c_dist)
        positions.append((name, px, py))

    # Route line (magenta)
    if positions:
        prev = (arc_cx, arc_cy)
        for name, px, py in positions:
            if y1 < py < y2 and x1 < px < x2:
                route_col = RED if severe > 0.5 else MAGENTA
                draw.line([prev, (px, py)], fill=route_col, width=2)
            prev = (px, py)

    # Draw waypoints
    for name, px, py in positions:
        if not (y1+20 < py < y2-20 and x1+20 < px < x2-20):
            continue
        circ(draw, px, py, 6, outline=MAGENTA, lw=2)
        c_name = corrupt_wp_name(name, corr)
        c_col  = RED if corr > 0.5 else CYAN
        tl(draw, px+10, py-8, c_name, Fr[13], c_col)

    # ── Aircraft symbol ──────────────────────────────────────────────────────
    asw = 22
    asy = arc_cy - 10
    draw.line([(arc_cx-asw, asy),(arc_cx-asw//3, asy+asw//4),(arc_cx, asy)], fill=YELLOW, width=3)
    draw.line([(arc_cx, asy),(arc_cx+asw//3, asy+asw//4),(arc_cx+asw, asy)], fill=YELLOW, width=3)
    draw.line([(arc_cx-asw//4, asy+asw//2),(arc_cx+asw//4, asy+asw//2)], fill=YELLOW, width=3)
    circ(draw, arc_cx, asy, 4, fill=YELLOW)

    # Heading bug
    bug_a = math.radians(90)   # straight ahead
    bx1 = arc_cx + int((arc_R-4)*math.cos(bug_a))
    by1 = arc_cy - int((arc_R-4)*math.sin(bug_a))
    bx2 = arc_cx + int((arc_R+4)*math.cos(bug_a))
    by2 = arc_cy - int((arc_R+4)*math.sin(bug_a))
    draw.line([(bx1,by1),(bx2,by2)], fill=CYAN, width=4)

    # ── ND labels ────────────────────────────────────────────────────────────
    tl(draw, x1+8, y1+16, "ARC", Fr[14], CYAN)
    tc(draw, cx, y1+16, "320NM", Fr[14], LGRAY)
    tr(draw, x2-8, y1+16, "HDG " + corrupt_num(hdg, corr*0.3, 3), Fr[14], WHITE)

    # DATA LINK status box
    if t >= T_ANOMALY:
        dl_p   = ph(t, T_ANOMALY, T_CAUTION)
        dl_col = RED if t >= T_WARNING else AMBER
        dl_txt = "ACARS LINK FAIL" if t >= T_WARNING else "ACARS DEGRADED"
        bx_c   = DKRED if t >= T_WARNING else DKAMB
        bx_w   = x2 - x1 - 16
        blink_show = blink(t, 1.8)
        if blink_show or t >= T_DIVERT:
            box(draw, x1+8, y2-80, x2-8, y2-48, fill=bx_c, outline=dl_col, lw=2)
            tc(draw, cx, y2-64, dl_txt, Fs[18], dl_col)

    # Wind / TAS readout (bottom-left)
    wind_dir = corrupt_num(255, corr*0.4, 3)
    wind_spd = corrupt_num(62,  corr*0.5, 2)
    tl(draw, x1+8, y2-30, f"W/{wind_dir}°/{wind_spd}KT", Fr[13], LGRAY)

    tas_c = corrupt_num(490, corr*0.35, 3)
    tr(draw, x2-8, y2-30, f"TAS {tas_c}KT", Fr[13], LGRAY)

# ═══════════════════════════════════════════════════════════════════════════
# GLITCH EFFECTS  (numpy pixel manipulation)
# ═══════════════════════════════════════════════════════════════════════════
def apply_glitch(arr, t):
    corr   = sm(ph(t, T_ANOMALY, T_WARNING))
    severe = sm(ph(t, T_WARNING, T_DIVERT))
    total  = corr * 0.6 + severe * 0.4

    if total < 0.03:
        return arr

    out = arr.copy()

    # Row displacement
    n_rows = int(total * 28)
    for _ in range(n_rows):
        ry = int(_rng.integers(0, H))
        shift = int(_rng.integers(-int(60*total), int(60*total)+1))
        if shift == 0:
            continue
        row = out[ry].copy()
        if shift > 0:
            out[ry, shift:] = row[:-shift]
            out[ry, :shift] = row[0]
        else:
            out[ry, :shift] = row[-shift:]
            out[ry, shift:] = row[-1]

    # Rectangular block corruption
    n_blocks = int(total * 6)
    for _ in range(n_blocks):
        bx = int(_rng.integers(0, W-80))
        by = int(_rng.integers(0, H-30))
        bw = int(_rng.integers(30, 120))
        bh = int(_rng.integers(4, 20))
        shift = int(_rng.integers(-40, 40))
        by2 = min(by+bh, H)
        bx2 = min(bx+bw, W)
        block = out[by:by2, bx:bx2].copy()
        if shift > 0 and bx+shift+bw < W:
            out[by:by2, bx+shift:bx2+shift] = block
        elif shift < 0 and bx+shift >= 0:
            out[by:by2, bx+shift:bx2+shift] = block

    # Color channel split (chromatic aberration)
    if total > 0.15:
        ca = int(total * 8)
        if ca > 0:
            out[:, ca:, 0] = arr[:, :-ca, 0]   # R shift right (BGR: index 2)
            out[:, :-ca, 2] = arr[:, ca:, 2]   # B shift left

    # Scan lines
    if total > 0.25:
        sl_alpha = min(0.45, total * 0.5)
        out[::3] = (out[::3] * (1 - sl_alpha)).astype(np.uint8)

    # Noise bursts
    n_noise = int(total * 120)
    if n_noise > 0:
        ny = _rng.integers(0, H, n_noise)
        nx = _rng.integers(0, W, n_noise)
        noise_c = _rng.integers(0, 255, (n_noise, 3))
        out[ny, nx] = noise_c

    # Vignette gets redder during warning
    if severe > 0.3:
        v_strength = severe * 0.35
        vy, vx = np.mgrid[0:H, 0:W]
        vd = np.sqrt(((vx-W/2)/(W/2))**2 + ((vy-H/2)/(H/2))**2)
        vmask = np.clip(vd * v_strength, 0, 0.6)[:, :, np.newaxis]
        red_tint = np.array([0, 0, 100], dtype=np.float32)  # BGR: red
        out = (out.astype(np.float32) * (1-vmask) + red_tint * vmask).astype(np.uint8)

    return out

# ═══════════════════════════════════════════════════════════════════════════
# OVERLAY TEXT  (main narrative)
# ═══════════════════════════════════════════════════════════════════════════
def draw_overlay(draw, t):
    divert = ph(t, T_DIVERT, T_DIVERT + 0.5)

    if t >= T_DIVERT and divert > 0.05:
        # Main emergency declaration — one sentence, big impact
        alpha_fade = min(1.0, divert * 4)

        # Red glow backing
        bh = 90
        oy = H//2 - bh//2
        box(draw, 0, oy, W, oy+bh, fill=(70, 0, 0))
        ln(draw, 0, oy,    W, oy,    RED, 3)
        ln(draw, 0, oy+bh, W, oy+bh, RED, 3)

        # Main text
        if blink(t, 1.2) or t >= T_CITE:
            tc(draw, W//2, H//2 - 8,
               "ACARS DATA LINK CORRUPTED  —  CREW INITIATING EMERGENCY DIVERT",
               Fs[36], WHITE)

        # Sub-line: squawk
        tc(draw, W//2, H//2 + 35,
           "SQUAWK 7700  |  ATC NOTIFIED  |  DIVERTING TO ALTERNATE",
           Fr[20], AMBER)

    if t >= T_CITE:
        cite_alpha = sm(ph(t, T_CITE, T_CITE + 0.4))
        cite = ("Scenario inspired by: 2023 FAA NOTAM data corruption (Jan 11 2023)  |  "
                "Documented ACARS plaintext data-link vulnerabilities")
        tc(draw, W//2, H - FTR_H - 28, cite, Fr[13], LGRAY)

# ═══════════════════════════════════════════════════════════════════════════
# FRAME RENDERER
# ═══════════════════════════════════════════════════════════════════════════
def render_frame(t):
    frame = Image.new("RGB", (W, H), BG)
    draw  = ImageDraw.Draw(frame)

    draw_header(draw, t)
    draw_footer(draw, t)
    draw_pfd(frame, draw, t)
    draw_ecam(draw, t)
    draw_nd(frame, draw, t)
    draw_overlay(draw, t)

    # Convert to numpy (BGR for OpenCV)
    arr = cv2.cvtColor(np.array(frame), cv2.COLOR_RGB2BGR)
    arr = apply_glitch(arr, t)

    return arr

# ═══════════════════════════════════════════════════════════════════════════
# AUDIO GENERATOR
# ═══════════════════════════════════════════════════════════════════════════
def sine(freq, dur, amp=0.7, sr=SRATE):
    t = np.linspace(0, dur, int(sr*dur), endpoint=False)
    return amp * np.sin(2 * np.pi * freq * t)

def silence(dur, sr=SRATE):
    return np.zeros(int(sr*dur))

def envelope(sig, attack=0.005, release=0.015):
    n = len(sig)
    a = int(SRATE * attack)
    r = int(SRATE * release)
    env = np.ones(n)
    env[:a] = np.linspace(0, 1, a)
    env[n-r:] = np.linspace(1, 0, r)
    return sig * env

def generate_audio():
    audio = np.zeros(int(SRATE * DUR))

    def place(sig, t_start):
        i = int(t_start * SRATE)
        end = min(i + len(sig), len(audio))
        audio[i:end] += sig[:end-i]

    # MASTER CAUTION chime: double ding at 820 Hz, t=2.0
    ding = envelope(sine(820, 0.09, 0.8))
    place(ding, T_CAUTION)
    place(ding, T_CAUTION + 0.18)

    # Lower ding underneath (750 Hz)
    ding2 = envelope(sine(750, 0.12, 0.5))
    place(ding2, T_CAUTION + 0.02)
    place(ding2, T_CAUTION + 0.20)

    # MASTER WARNING chime: triple ding at 1020 Hz, t=3.4
    warn_ding = envelope(sine(1020, 0.08, 0.95))
    for k in range(3):
        place(warn_ding, T_WARNING + k * 0.15)

    # Continuous alternating warning chime from T_WARNING to T_DIVERT
    t_cur = T_WARNING + 0.55
    toggle = True
    while t_cur < T_DIVERT - 0.1:
        freq = 880 if toggle else 660
        chunk = envelope(sine(freq, 0.18, 0.55), attack=0.01, release=0.03)
        place(chunk, t_cur)
        t_cur += 0.22
        toggle = not toggle

    # Single resolve chime when divert initiated
    resolve = envelope(sine(660, 0.25, 0.6))
    place(resolve, T_DIVERT + 0.05)

    # Low background hum (cockpit ambience) throughout
    t_bg  = np.linspace(0, DUR, int(SRATE * DUR), endpoint=False)
    hum   = 0.06 * np.sin(2 * np.pi * 180 * t_bg)
    hum  += 0.03 * np.sin(2 * np.pi * 360 * t_bg)
    audio += hum

    # Normalize
    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = audio / peak * 0.92

    return audio

def save_audio(audio, path):
    pcm = (audio * 32767).astype(np.int16)
    with wave.open(path, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SRATE)
        wf.writeframes(pcm.tobytes())

# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════
def main():
    print(f"Rendering {NF} frames at {FPS}fps ({DUR}s) → {W}x{H}")

    # Video writer (raw, no audio)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(TMP_V, fourcc, FPS, (W, H))

    for fi in range(NF):
        t = fi / FPS
        frame = render_frame(t)
        vw.write(frame)
        if fi % 30 == 0:
            print(f"  frame {fi}/{NF}  t={t:.2f}s")

    vw.release()
    print(f"Video written → {TMP_V}")

    # Audio
    print("Generating audio...")
    audio = generate_audio()
    save_audio(audio, TMP_A)
    print(f"Audio written → {TMP_A}")

    # Combine with ffmpeg
    print("Combining video + audio...")
    cmd = [
        "ffmpeg", "-y",
        "-i", TMP_V,
        "-i", TMP_A,
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", OUT
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("ffmpeg error:", result.stderr[-800:])
    else:
        print(f"Done! Output: {OUT}")

if __name__ == "__main__":
    main()
