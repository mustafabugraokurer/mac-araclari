"""
Cep — kayıt katmanı (macOS'a bağımlı değil, test edilebilir).

- Kopyalama geçmişi: metin, link, renk, görsel, dosya
- Sabitlenenler sen silene kadar kalır; diğerleri GECMIS_GUN gün / EN_FAZLA öğe
- Taşıma alanı: dosya yolu + mod ("kes" ya da "kopya"); dosyalar sen bırakana
  kadar asıl yerinde durur, Cep onları hiçbir zaman kendi başına silmez.
"""
import hashlib
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path

GECMIS_GUN = 30
EN_FAZLA = 200

URL_RE = re.compile(r"^(https?://|www\.)\S+$", re.I)
RENK_RE = re.compile(r"^#?(?:[0-9a-f]{6}|[0-9a-f]{3})$", re.I)


def _sha(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha1(data).hexdigest()


def tur_bul(text: str) -> str:
    t = text.strip()
    if "\n" not in t and URL_RE.match(t):
        return "link"
    if RENK_RE.match(t):
        return "renk"
    return "metin"


def once(ts: float, now: float = None) -> str:
    now = now or time.time()
    d = max(0, int(now - ts))
    if d < 45:
        return "şimdi"
    if d < 3600:
        return f"{max(1, d // 60)} dk önce"
    if d < 86400:
        return f"{d // 3600} sa önce"
    if d < 2 * 86400:
        return "dün"
    return f"{d // 86400} gün önce"


def tek_satir(text: str, n: int = 52) -> str:
    t = " ".join(text.split())
    return t if len(t) <= n else t[: n - 1] + "…"


def bos_isim(hedef_klasor: Path, ad: str) -> Path:
    """Aynı isimde dosya varsa 'ad 2.uzanti' gibi boş bir isim bul."""
    p = hedef_klasor / ad
    if not p.exists():
        return p
    kok, uz = os.path.splitext(ad)
    i = 2
    while True:
        p = hedef_klasor / f"{kok} {i}{uz}"
        if not p.exists():
            return p
        i += 1


class Store:
    def __init__(self, klasor: Path):
        self.dir = Path(klasor)
        self.img_dir = self.dir / "gorseller"
        self.img_dir.mkdir(parents=True, exist_ok=True)
        self.hist_file = self.dir / "gecmis.json"
        self.shelf_file = self.dir / "tasima.json"
        self.history = self._oku(self.hist_file)
        self.shelf = self._oku(self.shelf_file)
        self.prune()

    # ------------------------------------------------ dosya
    @staticmethod
    def _oku(p: Path) -> list:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _yaz(self, p: Path, data) -> None:
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)

    def save(self) -> None:
        self._yaz(self.hist_file, self.history)

    def save_shelf(self) -> None:
        self._yaz(self.shelf_file, self.shelf)

    # ------------------------------------------------ geçmiş
    def _push(self, item: dict) -> dict:
        for i, old in enumerate(self.history):
            if old["key"] == item["key"]:
                old["ts"] = item["ts"]
                old["app"] = item.get("app") or old.get("app")
                self.history.insert(0, self.history.pop(i))
                self.save()
                return old
        self.history.insert(0, item)
        self.prune()
        self.save()
        return item

    def _yeni(self, kind: str, key: str, app: str, **kw) -> dict:
        return {"id": uuid.uuid4().hex[:12], "kind": kind, "key": key,
                "app": app or "", "ts": time.time(), "pinned": False, **kw}

    def add_text(self, text: str, app: str = "", gorselden: bool = False) -> dict:
        if not text or not text.strip():
            return None
        kw = {"gorselden": True} if gorselden else {}
        return self._push(self._yeni(tur_bul(text), "t:" + _sha(text), app, text=text, **kw))

    def set_ocr(self, item_id: str, text: str) -> dict:
        """Görsel öğeye tanınan yazıyı ekle (aramada bulunsun diye)."""
        item = self.get(item_id)
        if item:
            item["ocr"] = text or ""
            self.save()
        return item

    def add_image(self, png: bytes, w: int, h: int, app: str = "") -> dict:
        key = "i:" + _sha(png)
        for old in self.history:
            if old["key"] == key:
                return self._push(dict(old, ts=time.time()))
        ad = key[2:14] + ".png"
        (self.img_dir / ad).write_bytes(png)
        return self._push(self._yeni("gorsel", key, app, image=ad, w=w, h=h))

    def add_files(self, paths: list, app: str = "") -> dict:
        paths = [str(p) for p in paths if p]
        if not paths:
            return None
        return self._push(self._yeni("dosya", "f:" + "|".join(paths), app, paths=paths))

    def get(self, item_id: str) -> dict:
        return next((x for x in self.history if x["id"] == item_id), None)

    def _gorsel_sil(self, item: dict) -> None:
        if item.get("image"):
            try:
                (self.img_dir / item["image"]).unlink()
            except FileNotFoundError:
                pass

    def remove(self, item_id: str) -> None:
        item = self.get(item_id)
        if item:
            self.history.remove(item)
            self._gorsel_sil(item)
            self.save()

    def toggle_pin(self, item_id: str) -> None:
        item = self.get(item_id)
        if item:
            item["pinned"] = not item["pinned"]
            self.save()

    def clear_unpinned(self) -> int:
        silinecek = [x for x in self.history if not x["pinned"]]
        for x in silinecek:
            self._gorsel_sil(x)
        self.history = [x for x in self.history if x["pinned"]]
        self.save()
        return len(silinecek)

    def prune(self) -> None:
        sinir = time.time() - GECMIS_GUN * 86400
        kalan, sayac = [], 0
        for x in self.history:
            if x.get("pinned"):
                kalan.append(x)
            elif x["ts"] >= sinir and sayac < EN_FAZLA:
                kalan.append(x)
                sayac += 1
            else:
                self._gorsel_sil(x)
        self.history = kalan

    def pinned(self) -> list:
        return [x for x in self.history if x["pinned"]]

    def recent(self) -> list:
        return [x for x in self.history if not x["pinned"]]

    def mark_used(self, item_id: str) -> None:
        """Cep'ten yapıştırıldı: kullanım sayısını artır, en üste al."""
        item = self.get(item_id)
        if not item:
            return
        item["kullanim"] = int(item.get("kullanim", 0)) + 1
        item["ts"] = time.time()
        self.history.remove(item)
        self.history.insert(0, item)
        self.save()

    def frequent(self, n: int = 5, en_az: int = 2) -> list:
        """En çok yapıştırılan (sabitlenmemiş) öğeler."""
        aday = [x for x in self.history
                if not x["pinned"] and int(x.get("kullanim", 0)) >= en_az]
        aday.sort(key=lambda x: (-int(x.get("kullanim", 0)), -x["ts"]))
        return aday[:n]

    @staticmethod
    def _norm(t: str) -> str:
        return t.replace("I", "ı").replace("İ", "i").lower()

    def search(self, sorgu: str) -> list:
        q = self._norm(sorgu.strip())
        if not q:
            return list(self.history)
        sonuc = []
        for x in self.history:
            metin = " ".join([x.get("text") or "", x.get("ocr") or "",
                              " ".join(x.get("paths") or []),
                              self.label(x), x.get("app") or ""])
            if q in self._norm(metin):
                sonuc.append(x)
        return sonuc

    @staticmethod
    def label(item: dict) -> str:
        k = item["kind"]
        if k == "gorsel":
            return f"Görsel  {item.get('w', '?')} × {item.get('h', '?')}"
        if k == "dosya":
            ps = item["paths"]
            ad = os.path.basename(ps[0].rstrip("/")) or ps[0]
            return tek_satir(ad) if len(ps) == 1 else f"{tek_satir(ad, 36)} + {len(ps) - 1} dosya"
        return tek_satir(item["text"])

    @staticmethod
    def detail(item: dict, now: float = None) -> str:
        parca = ["Görselden"] if item.get("gorselden") else []
        if item.get("app"):
            parca.append(item["app"])
        if item.get("gorselden") and item.get("text"):
            n = len([s for s in item["text"].splitlines() if s.strip()])
            if n > 1:
                parca.append(f"{n} satır")
        parca.append(once(item["ts"], now))
        return " · ".join(parca)

    # ------------------------------------------------ taşıma alanı
    def shelf_add(self, paths: list, mode: str) -> int:
        mevcut = {x["path"] for x in self.shelf}
        eklenen = 0
        for p in paths:
            p = str(p)
            if p in mevcut or not os.path.exists(p):
                continue
            self.shelf.append({"id": uuid.uuid4().hex[:12], "path": p, "mode": mode,
                               "kaynak": os.path.basename(os.path.dirname(p)) or "/",
                               "ts": time.time()})
            eklenen += 1
        if eklenen:
            self.save_shelf()
        return eklenen

    def shelf_remove(self, ids) -> None:
        ids = set(ids)
        self.shelf = [x for x in self.shelf if x["id"] not in ids]
        self.save_shelf()

    def shelf_cleanup(self) -> list:
        """Başka bir yolla taşınmış/silinmiş dosyaları taşıma alanından çıkar."""
        gitti = [x for x in self.shelf if not os.path.exists(x["path"])]
        if gitti:
            self.shelf_remove([x["id"] for x in gitti])
        return gitti

    def shelf_get(self, ids) -> list:
        ids = set(ids)
        return [x for x in self.shelf if x["id"] in ids]

    def shelf_move_to(self, ids, hedef: str) -> list:
        """Seçili öğeleri hedef klasöre taşı ("kes") ya da kopyala ("kopya")."""
        hedef_p = Path(hedef)
        sonuc = []
        for x in self.shelf_get(ids):
            src = Path(x["path"])
            if not src.exists():
                sonuc.append((x, None, "bulunamadı"))
                continue
            if src.parent.resolve() == hedef_p.resolve() and x["mode"] == "kes":
                sonuc.append((x, src, "zaten orada"))
                continue
            dst = bos_isim(hedef_p, src.name)
            try:
                if x["mode"] == "kes":
                    shutil.move(str(src), str(dst))
                elif src.is_dir():
                    shutil.copytree(str(src), str(dst))
                else:
                    shutil.copy2(str(src), str(dst))
                sonuc.append((x, dst, "tamam"))
            except Exception as e:
                sonuc.append((x, None, str(e)))
        bitti = [x["id"] for x, _, durum in sonuc if durum in ("tamam", "zaten orada")]
        if bitti:
            self.shelf_remove(bitti)
        return sonuc
