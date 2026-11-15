"""
Namaz vakitleri — internetsiz astronomik hesap.

Desteklenen yöntemler: Diyanet (Türkiye), Müslüman Dünya Birliği, ISNA, Mısır,
Ümmü'l-Kura, Karaçi, Körfez, Kuveyt, Katar, Singapur, Malezya, Endonezya, Fas,
Fransa (UOIF) ve Rusya. İkindi Şafii (1 misli) ya da Hanefi (2 misli) hesaplanabilir.
Kutba yakın yerlerde güneş yeterince alçalmıyorsa imsak/yatsı "açıya göre gece payı"
kuralıyla düzeltilir. macOS'a bağımlı değildir, test edilebilir.
"""
import datetime as dt
import math

VAKITLER = ["imsak", "gunes", "ogle", "ikindi", "aksam", "yatsi"]
ADLAR = {"imsak": "İmsak", "gunes": "Güneş", "ogle": "Öğle", "ikindi": "İkindi",
         "aksam": "Akşam", "yatsi": "Yatsı"}

# imsak/yatsı: güneşin ufkun kaç derece altında olduğu; yatsi_dk: akşamdan kaç dk sonra
YONTEMLER = {
    "diyanet": {"ad": "Diyanet (Türkiye)", "imsak": 18, "yatsi": 17,
                "temkin": {"gunes": -7, "ogle": 5, "ikindi": 4, "aksam": 7}},
    "mwl": {"ad": "Müslüman Dünya Birliği", "imsak": 18, "yatsi": 17,
            "temkin": {"ogle": 1}},
    "isna": {"ad": "ISNA (Kuzey Amerika)", "imsak": 15, "yatsi": 15, "temkin": {"ogle": 1}},
    "misir": {"ad": "Mısır", "imsak": 19.5, "yatsi": 17.5, "temkin": {"ogle": 1}},
    "ummulkura": {"ad": "Ümmü'l-Kura (Suudi Arabistan)", "imsak": 18.5, "yatsi_dk": 90},
    "karachi": {"ad": "Karaçi (Güney Asya)", "imsak": 18, "yatsi": 18, "temkin": {"ogle": 1}},
    "korfez": {"ad": "Körfez (BAE)", "imsak": 18.2, "yatsi": 18.2,
               "temkin": {"gunes": -3, "ogle": 3, "ikindi": 3, "aksam": 3}},
    "kuveyt": {"ad": "Kuveyt", "imsak": 18, "yatsi": 17.5},
    "katar": {"ad": "Katar", "imsak": 18, "yatsi_dk": 90},
    "singapur": {"ad": "Singapur", "imsak": 20, "yatsi": 18, "temkin": {"ogle": 1}},
    "malezya": {"ad": "Malezya (JAKIM)", "imsak": 20, "yatsi": 18, "temkin": {"ogle": 1}},
    "endonezya": {"ad": "Endonezya (Kemenag)", "imsak": 20, "yatsi": 18,
                  "temkin": {"ogle": 1}},
    "fas": {"ad": "Fas", "imsak": 19, "yatsi": 17, "temkin": {"aksam": 5}},
    "fransa": {"ad": "Fransa (UOIF, 12°)", "imsak": 12, "yatsi": 12},
    "rusya": {"ad": "Rusya", "imsak": 16, "yatsi": 15},
}

# Geriye uyumluluk: eski çağrılar Diyanet temkinini kullanır
IMSAK_ACI = YONTEMLER["diyanet"]["imsak"]
YATSI_ACI = YONTEMLER["diyanet"]["yatsi"]
TEMKIN = dict(YONTEMLER["diyanet"]["temkin"], imsak=0, yatsi=0)


def _d2r(d):
    return d * math.pi / 180.0


def _r2d(r):
    return r * 180.0 / math.pi


def _gunes(jd):
    """Güneşin dik açıklığı (derece) ve zaman denklemi (saat)."""
    d = jd - 2451545.0
    g = (357.529 + 0.98560028 * d) % 360
    q = (280.459 + 0.98564736 * d) % 360
    L = (q + 1.915 * math.sin(_d2r(g)) + 0.020 * math.sin(_d2r(2 * g))) % 360
    e = 23.439 - 0.00000036 * d
    RA = _r2d(math.atan2(math.cos(_d2r(e)) * math.sin(_d2r(L)), math.cos(_d2r(L)))) / 15
    RA %= 24
    decl = _r2d(math.asin(math.sin(_d2r(e)) * math.sin(_d2r(L))))
    eqt = q / 15 - RA
    eqt = (eqt + 12) % 24 - 12
    return decl, eqt


def _julian(tarih: dt.date) -> float:
    y, m, d = tarih.year, tarih.month, tarih.day
    if m <= 2:
        y -= 1
        m += 12
    A = y // 100
    B = 2 - A + A // 4
    return math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d + B - 1524.5


def vakitler(tarih: dt.date, enlem: float, boylam: float, utc_fark: float,
             temkin: dict = None, yontem: str = "diyanet", hanefi: bool = False) -> dict:
    """{vakit: datetime} döndürür (yerel saat, dakikaya yuvarlanmış).

    temkin verilirse yöntemin kendi temkini yerine o kullanılır ({} = temkinsiz).
    """
    y = YONTEMLER.get(yontem, YONTEMLER["diyanet"])
    temkin = y.get("temkin", {}) if temkin is None else temkin
    jd = _julian(tarih) - boylam / (15 * 24)
    golge = 2 if hanefi else 1

    def ogle_saati(t):
        _, eqt = _gunes(jd + t / 24)
        return (12 - eqt) % 24

    def aci_saati(aci, t, yon):
        """Güneşin ufkun `aci` derece altında olduğu saat; hiç olmuyorsa None."""
        decl, _ = _gunes(jd + t / 24)
        noon = ogle_saati(t)
        c = (-math.sin(_d2r(aci)) - math.sin(_d2r(decl)) * math.sin(_d2r(enlem))) / \
            (math.cos(_d2r(decl)) * math.cos(_d2r(enlem)))
        if c < -1 or c > 1:
            return None
        T = _r2d(math.acos(c)) / 15
        return noon + (-T if yon < 0 else T)

    def ikindi_saati(t):
        decl, _ = _gunes(jd + t / 24)
        aci = -_r2d(math.atan(1 / (golge + math.tan(_d2r(abs(enlem - decl))))))
        return aci_saati(aci, t, +1)

    t = {"imsak": 5, "gunes": 6, "ogle": 12, "ikindi": 13, "aksam": 18, "yatsi": 18}
    for _ in range(2):
        yeni = {
            "imsak": aci_saati(y["imsak"], t["imsak"], -1),
            "gunes": aci_saati(0.833, t["gunes"], -1),
            "ogle": ogle_saati(t["ogle"]),
            "ikindi": ikindi_saati(t["ikindi"]),
            "aksam": aci_saati(0.833, t["aksam"], +1),
            "yatsi": aci_saati(y["yatsi"], t["yatsi"], +1) if "yatsi" in y else None,
        }
        # güneş hiç doğmuyor/batmıyorsa (kutup): öğleden ±6 saat varsay
        if yeni["gunes"] is None:
            yeni["gunes"] = yeni["ogle"] - 6
        if yeni["aksam"] is None:
            yeni["aksam"] = yeni["ogle"] + 6
        if yeni["ikindi"] is None:
            yeni["ikindi"] = (yeni["ogle"] + yeni["aksam"]) / 2
        gece = 24 - (yeni["aksam"] - yeni["gunes"])
        # imsak: açıya göre gece payı kuralı
        pay = y["imsak"] / 60 * gece
        if yeni["imsak"] is None or yeni["gunes"] - yeni["imsak"] > pay:
            yeni["imsak"] = yeni["gunes"] - pay
        if "yatsi_dk" in y:
            yeni["yatsi"] = yeni["aksam"] + y["yatsi_dk"] / 60
        else:
            pay = y["yatsi"] / 60 * gece
            if yeni["yatsi"] is None or yeni["yatsi"] - yeni["aksam"] > pay:
                yeni["yatsi"] = yeni["aksam"] + pay
        t = yeni

    sonuc = {}
    gece_yarisi = dt.datetime.combine(tarih, dt.time())
    for k in VAKITLER:
        saat = t[k] + utc_fark - boylam / 15 + temkin.get(k, 0) / 60
        dk = math.floor(saat * 60 + 0.5)
        sonuc[k] = gece_yarisi + dt.timedelta(minutes=dk)
    return sonuc
