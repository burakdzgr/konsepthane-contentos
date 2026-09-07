# Günlük İçerik Botu

## Önce / sonra

Önce: `/operasyon` üzerinden otonom mod açılabiliyordu; kaynak taraması ayrı
başlatılıyor, günlük hazır içerik hedefi bulunmuyordu. Ana ekran teknik
istatistikleri öne çıkarıyordu.

Sonra: `/bot` kaynak seçimi, günlük hedef, başlat/duraklat, gerçek günlük
ilerleme ve içerik listesini aynı ekranda sunar. Ana menünün ilk bağlantısıdır.
Eski kontrol merkezi ve tanılama araçları Sistem ve ayrıntılar altında korunur.

İkinci UI geçişinde ortak kabuk da yenilendi: yeni koyu stüdyo renkleri,
boşluk/typography ölçeği, kart, tablo, form, badge, sol menü ve üst bar bütün
sayfalarda ortak bir tasarım sisteminden gelir. `/yayina-hazir` normal menüde
ayrı bir alandır; yalnız gerçek son inceleme durumunu, onaylananları ve yayın
sırasını üç açık sekmede gösterir. İçerikler ekranındaki düşük seviyeli
araştırma girişleri normal akıştan kaldırılmadan Gelişmiş altında katlandı.

## Kullanım

1. İçerik Botu ekranında kaynakları seçin.
2. Günlük hedefi girin (ör. 10, izin verilen aralık 1–50).
3. Kaydet ve botu çalıştır düğmesine basın.
4. Bot seçili kaynaklar için mevcut bütçelerle sınırlı günlük keşif başlatır.
   Aktif çalışma varsa ikinci bir çalışma oluşturmaz. Kaynak türü otomatik
   keşfi desteklemiyorsa yalnızca mevcut araştırma havuzu kullanılabilir.
5. Uygun fırsatlar günlük plana alınır. Mevcut kalite ve kanıt kurallarıyla
   fikir, yazım planı, taslak ve kontroller ilerler.
6. Son yayın onayı insanda kalır. Görsel/lisans ve giderilemeyen kalite/kanıt
   sorunları da mevcut güvenli karar noktalarında durur.

## Sayacın anlamı

Gün `Europe/Istanbul` sınırlarıyla hesaplanır. Kuyruğa giren veya AI cevabı
dönen iş hazır değildir. Yalnızca kalıcı `AWAITING_HUMAN_REVIEW` geçişi olan
planlı içerik, ilk geçişinin Türkiye gününde bir kez sayılır.

Yarım kalan rezervasyonlar ertesi günün kapasitesinden düşer. Hedef azaltılması
başlamış işleri iptal etmez. Reddedilen/arşivlenen iş tamamlanmış sayılmaz ve
kapasiteyi serbest bırakır. Engellenmiş iş kapasiteyi tutar; otomatik olarak
unutulmaz. Günlük 10, kalite düşürülerek doldurulan bir garanti değildir.

## Kalıcılık ve güvenlik

Migration `0038` additive: nullable `autopilot_settings.daily_target`, açık
RESTRICT kaynak ilişkileri için `autopilot_sources`, iş kimliği tekil anahtar
olan `daily_preparations`. Önceki veriler ve migration geçmişi korunur.
Hedefsiz eski ayarlar eski davranışı korur; günlük plan operatör tarafından
açıkça etkinleştirilir. Ayar komutunda operatör, hedef ve seçilen kaynaklar
audit kaydına yazılır.

PostgreSQL singleton satır kilidi kapasite ayırmayı seri hale getirir. Worker
step günlük plana alınmamış işleri ilerletmez; insanın önceden onayladığı
yayın gönderimleri hazırlık kotasından bağımsızdır. 20 saniyelik sweep ve
60 saniyelik beat watchdog birlikte çalışır; Redis kilidi tekrar tetiklenen
sweep zincirlerini birleştirir. Eski, ilerlemeyen canlı kaynak taramaları
beş dakika sonra yeniden kuyruğa alınabilir; intake adımı entity kilidi taşır.
Bilgisayar/Docker/worker/beat kapalıysa plan çalışamaz; açılınca devam eder.

## Değişmeyen sınırlar

- Dış içerik çevrilip kopyalanacak şablon değil, araştırma/ilham sinyalidir.
- Stratejik kelimeler editoryal yön verir; keyword stuffing talimatı değildir.
- AI çıktısı araştırma kanıtı değildir; UNKNOWN arama/trend bilgisi gizlenmez.
- Kanıt/provenance, kalite ve insan yayın onayı atlanmaz.
- Consumer UGC uygulaması ve üretim Konsepthane veritabanına doğrudan yazma yok.

## Yerel kabul (2026-09-06)

Yeni ekran production Docker build ile yerelde açıldı. Tarayıcıdan mevcut
Kara's Party Ideas, Catch My Party, Pretty My Party seçilip günlük 10 hedefi
kaydedildi. Migration gerçek yerel PostgreSQL üzerinde `0038 (head)` olarak
doğrulandı. Gerçek kaynak fetch/promotion/değerlendirme işleri gözlendi.
İlk gözlem: 0 hazır, 1 planlı içerik (`21 Cinderella Birthday Party Ideas`,
yazım planı aşaması). Bu gözlem 10 içeriğin tamamlandığını kanıtlamaz.
