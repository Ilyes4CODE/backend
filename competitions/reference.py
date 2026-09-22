"""Reference data transcribed from the championship regulations
(قانون-التنظيمي-للبطولة.pdf — WFVV, ref 01/DL-LDTGVCTVN, 3rd World Championship).

Section V of that document defines the competition catalogue; the weight tables in
section V.1 and the Quyen tables in V.2 are reproduced verbatim below.
"""

# ── V.1 المنازلات — 18 weight classes (10 male, 8 female) ────────────────────
# Each class awards 1 gold, 1 silver and 2 bronze: both semi-final losers share
# third place, which is why the regulations list 18/18/36 medals.
MALE_WEIGHT_CLASSES = [
    ('M46_50', '46 - 50 kg'),
    ('M50_55', '50 - 55 kg'),
    ('M55_60', '55 - 60 kg'),
    ('M60_65', '60 - 65 kg'),
    ('M65_70', '65 - 70 kg'),
    ('M70_75', '70 - 75 kg'),
    ('M75_80', '75 - 80 kg'),
    ('M80_85', '80 - 85 kg'),
    ('M85_90', '85 - 90 kg'),
    ('M90_PLUS', '+90 kg'),
]

FEMALE_WEIGHT_CLASSES = [
    ('F44_48', '44 - 48 kg'),
    ('F48_52', '48 - 52 kg'),
    ('F52_56', '52 - 56 kg'),
    ('F56_60', '56 - 60 kg'),
    ('F60_65', '60 - 65 kg'),
    ('F65_70', '65 - 70 kg'),
    ('F70_75', '70 - 75 kg'),
    ('F75_PLUS', '+75 kg'),
]

WEIGHT_CLASSES = MALE_WEIGHT_CLASSES + FEMALE_WEIGHT_CLASSES

# ── V.2 Quyen "quy định" — the prescribed forms, per gender ──────────────────
PRESCRIBED_QUYEN_MALE = [
    'Ngọc Trản Quyền',
    'Siêu Xung Thiên',
    'Độc Lư Thương',
    'Thanh Long Độc Kiếm',
    'Phong Hoa Đao',
    'Tứ Linh Đao',
]

PRESCRIBED_QUYEN_FEMALE = [
    'Lão Mai Quyền',
    'Thái Sơn Côn',
    'Hùng Kê Quyền',
    'Lão Hổ Thượng Sơn',
    'Song Tuyết Kiếm',
    'Tứ Linh Đao',
]

# ── V.2 - V.6 the judged (technique) events ─────────────────────────────────
TECHNIQUE_EVENTS = [
    ('QUYEN_PRESCRIBED', 'Quyen "quy định" — prescribed form'),
    ('FREESTYLE_BAREHAND', 'Free style — bare hand'),
    ('FREESTYLE_LONG_WEAPON', 'Free style — long weapon'),
    ('FREESTYLE_SHORT_WEAPON', 'Free style — short weapon'),
    ('FREESTYLE_SOFT_WEAPON', 'Free style — soft weapon'),
    ('GROUP_QUYEN_BAREHAND', 'Group quyen "tập thể" — bare hand'),
    ('GROUP_QUYEN_WEAPON', 'Group quyen "binh khí tập thể" — weapons'),
    ('DEMO_COMBAT_BAREHAND', 'Demonstration combat — bare hand'),
    ('DEMO_COMBAT_WEAPON', 'Demonstration combat — weapons'),
    ('DUONG_SINH', 'Dưỡng sinh'),
]

# Minimum team sizes stated in the regulations for the collective events.
GROUP_EVENT_MIN_PARTICIPANTS = {
    'GROUP_QUYEN_BAREHAND': 5,
    'GROUP_QUYEN_WEAPON': 5,
    'DUONG_SINH': 3,
}

# Section IX: every fighter must demonstrate the first five techniques before the bout.
REQUIRED_PRE_BOUT_TECHNIQUES = 5
