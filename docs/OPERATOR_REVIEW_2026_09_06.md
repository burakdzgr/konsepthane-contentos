# Editoryal bot incelemesi — 6 Eylül 2026

Başlangıç revizyonu: 7aeb0fd. Güncel sistem FastAPI, SQLAlchemy, Celery ve
Next.js üzerinde keşif, fikir, kanıt, arama niyeti, brief, yazım, editör, QA,
medya, insan onayı ve Publishing API zincirine sahip.

## Neydi / ne değişti?

| Önce | Bu düzenleme |
| --- | --- |
| 13 sürekli görünen menü bağlantısı | 7 günlük bağlantı; analiz ve teknik ekranlar açılır Sistem ve ayrıntılar altında |
| Kaynak keşfinin yazarı başlatıp başlatmadığı belirsiz | Nasıl Kullanırım ekranı gerçek otopilot durumunu okuyup modları açıklar |
| Otomasyon teknik ekranlar arasında | Kontrol Merkezi ve başlangıç kılavuzundan doğrudan erişim |
| Operasyonda gateway, tarayıcı ve olaylar ön planda | Üretim ve keşif önde; teknik paneller açılır ayrıntıda |
| Otonom açıklaması yalnız son onayda duracağını söylüyordu | Kaynak, kalite ve görsel seçimi beklemeleri de açıklanır |
| Fikir/brief talimatlarında yalnız kutlama yayını tanımı | Fikir, brief ve Writer için ortak Türkiye, kadın kitleleri ve topluluk yönü |
| Ortak topluluk editoryal yönü yoktu | Bağlama uygun doğal paylaşım sorusu; sahte yorum/link/sosyal kanıt yasağı |

Yeni şablon sürümleri: idea-candidates 2, brief-composition 5, writer-draft 6.
Mevcut taslaklar değiştirilmez. Yeni DB tablosu veya migration yoktur.
Writer yalnız kabul edilmiş brief'i işler; kaynak kanıtı ve claim kuralları korunur.

## Mevcut otomasyon ve eksikler

Otonom mod uygun fırsatı görevlendirir, özgünlükten geçen adayı seçer,
kanıt/arama niyeti/brief/taslak/editör/QA işlerini yürütür. Düzeltme döngüsü
ikiyle sınırlıdır. Eksik kanıt/kaynak, özgünlük, görsel bağlama ve son yayın
onayı insan müdahalesi gerektirebilir. Denetimli mod ara kabullerde de durur.

Yetersiz kaynakları farklı sitelerden tamamlayan tam otomatik araştırma döngüsü
bu düzenlemeyle tamamlanmadı. Her kaynak için garantili üretim iddiası yoktur.
Arama/trend verisi gerçek sağlayıcı erişimi gerektirir; yoksa Bilinmiyor kalır.
Yeni üretim talimatlarının içerik kalitesi gerçek örneklerde ayrıca incelenmelidir.
Sahte sağlayıcı testleri içerik kalitesinin ölçümü değildir.

Önceki commissioning hatası güncel repoda commissioning_admits ve gerekçeli
override ile zaten ele alınmıştı; bu çalışmada yeniden düzeltilmiş sayılmadı.
Önceki Cinderella canlı yayını CURRENT_STATE'de kayıtlıdır; bu çalışmanın testi değildir.

## Kullanım

1. Strateji: uygun kitle, konu kümesi ve öncelikli hedefler.
2. Kaynaklar: amaç ve adres, ardından Keşfi başlat.
3. Nasıl Kullanırım: gerçek otomasyon durumu ve ayarlara erişim.
4. Çalışmalar/İçerikler: ilerlemeyi izle.
5. Benden Bekleyenler: editoryal kararı ver.
6. Son metin ve görselleri incele, insan yayın onayını ver.

Üretim Konsepthane DB/dosyalarına doğrudan erişim yapılmaz; yayın mevcut
authenticated Publishing API üzerinden kalır.

## Doğrulama

- Backend: 1.691 test geçti.
- Admin: 370 test geçti.
- Admin TypeScript ve ESLint geçti.
- Değişen backend modülleri Ruff ve mypy kontrollerinden geçti.
- Backend ve admin Docker production build başarılı.
- Mevcut veri ve migration geçmişi korundu; yeni migration yok.
