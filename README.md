# mac-araclari

Mac menü çubuğu için iki küçük, Türkçe araç. Python ve macOS'un kendi arayüz
kütüphaneleriyle (PyObjC) yazıldı; her biri tek komutla `.app` olarak kurulur.

*Two small macOS menu bar utilities with a Turkish UI — English summary below.*

| | |
|---|---|
| **[Hareket](hareket/)** | Uzun süre oturunca kalkmanı hatırlatır. Süre dolunca ekranda uyarı açılır: *Kalktım* deyince mola başlar, istersen ertelersin. |
| **[Cep](cep/)** | Kopyalama geçmişi ve taşıma alanı. Kopyaladıklarını arar, sabitler, silersin; dosyaları menü çubuğundaki ikona sürükleyip istediğin klasöre taşırsın. |


<p align="center">
  <img src="docs/hareket-menu.png" width="49%" alt="Hareket menüsü">
  <img src="docs/cep-panel.png" width="49%" alt="Cep paneli">
</p>
<p align="center"><sub>Tasarım görselleri — gerçek uygulamada küçük farklar olabilir.</sub></p>

## Kurulum

```bash
git clone https://github.com/mustafabugraokurer/mac-araclari.git
cd mac-araclari/hareket   # ya da: cd mac-araclari/cep
./install.sh
```

Ya da klasördeki **`Kur.command`** dosyasına çift tıkla.

**Gereken:** macOS 12 veya üstü, Python 3.9+ ve Xcode Komut Satırı Araçları
(`xcode-select --install`).

Kurulum betiği uygulamayı senin Mac'inde derler, `~/Applications` klasörüne koyar,
oturum açınca başlatır ve çökerse yeniden açar. Uygulamalar Apple tarafından imzalı
olmadığı için hazır `.app` dağıtılmıyor; kaynak koddan derlemek bu yüzden en temiz yol.

Ayrıntılar her uygulamanın kendi README'sinde: [Hareket](hareket/README.md) ·
[Cep](cep/README.md)

### Cep için izin

"Seçince yapıştır" ve `⌃⌘V` kısayolu için bir kez **Erişilebilirlik** izni gerekir:
Sistem Ayarları → Gizlilik ve Güvenlik → Erişilebilirlik → Cep. Yeniden derledikten
sonra Cep'i listeden kaldırıp tekrar eklemen gerekebilir.

## Gizlilik

Her şey senin Mac'inde kalır; uygulamalar internete bağlanmaz. Cep'in geçmişi
`~/Library/Application Support/Cep/` içinde durur ve şifre yöneticilerinin "gizli"
olarak işaretlediği kopyaları kaydetmez.

---

## English

Two small menu bar utilities for macOS, written in Python with PyObjC. The UI is in Turkish.

- **Hareket** ("movement") — a stand-up reminder, like the Apple Watch stand alert.
  When the timer ends, a dialog asks you to confirm you stood up (starting a short
  break) or to snooze. The next sitting timer starts only when you say so.
- **Cep** ("pocket") — clipboard history with search, pinning, deletion and a
  "frequently used" section, plus a file shelf: drag files onto the menu bar icon,
  then drag them out to any folder to move or copy them. Quick paste with `⌃⌘V`.

**Install:** clone the repo, `cd` into an app folder and run `./install.sh`
(or double-click `Kur.command`). Requires macOS 12+, Python 3.9+ and the Xcode
Command Line Tools. The script builds the app locally with py2app, installs it to
`~/Applications`, and registers a LaunchAgent so it starts at login and restarts if
it crashes. Cep needs Accessibility permission for auto-paste and the hotkey.

Everything stays on your Mac; neither app makes network requests.

## Lisans / License

[MIT](LICENSE)
