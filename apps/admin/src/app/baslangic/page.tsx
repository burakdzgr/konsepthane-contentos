import Link from "next/link";
import {
  fetchAutopilotState,
  AUTOPILOT_MODE_LABELS,
} from "@/lib/operations-api";

export const dynamic = "force-dynamic";

export default async function GettingStartedPage() {
  const result = await fetchAutopilotState();
  const mode = result.kind === "ok" ? result.data.mode : null;
  return (
    <section className="panel panel-wide" aria-labelledby="guide-title">
      <h1 id="guide-title">Konsepthane için içerik hazırlayın</h1>
      <p>
        Kaynakları ve hedeflerinizi belirleyin. ContentOS araştırmayı, yazımı ve
        kontrolleri yürütür; siz gerekli kararları verirsiniz.
      </p>
      <section className="detail-card" aria-labelledby="guide-mode">
        <h2 id="guide-mode">
          Otomatik üretim:{" "}
          {mode === null ? "Durum okunamadı" : AUTOPILOT_MODE_LABELS[mode]}
        </h2>
        <p>
          {mode === "autonomous"
            ? "Üretim adımları otomatik ilerliyor. Kaynak yetersizliği, özgünlük sorunu, görsel seçimi veya son yayın onayı gerektiğinde durur."
            : mode === "supervised"
              ? "Çıktılar otomatik hazırlanır; fikir, yazım planı ve editör kabulünde de karar vermeniz gerekir. Daha az müdahale için otomasyon ayarlarını açın."
              : mode === "off"
                ? "Otomatik üretim kapalı. Kaynak keşfi başlatmak tek başına yazarı çalıştırmaz. Üretimin ilerlemesi için otomasyon ayarlarını açın."
                : "Üretimin çalıştığını doğrulayamıyoruz. Sistem sağlığını kontrol edin."}
        </p>
        <Link href="/operasyon">Otomasyon ayarları ve çalışan işler →</Link>
      </section>
      <ol>
        <li>
          <h2>
            <Link href="/strateji">Hedeflerinizi belirleyin</Link>
          </h2>
          <p>
            Önce hedef kitleyi, ardından konu kümesini ve ilgili konu
            hedeflerini ekleyin. Örneğin: çocuklu anneler → çocuk doğum günü →
            evde doğum günü masa süsleme. Başlangıçta birkaç öncelikli konu
            yeterlidir.
          </p>
        </li>
        <li>
          <h2>
            <Link href="/sources">Kaynak ekleyin ve keşfi başlatın</Link>
          </h2>
          <p>
            Kaynak kaydet ile adresi ekleyin. Kaynağın ilham, Türkiye pazarı
            veya topluluk ihtiyacı için kullanılacağını belirtin. Aktif kaynağın
            Keşfi başlat düğmesine bir kez basın.
          </p>
        </li>
        <li>
          <h2>
            <Link href="/calisma">Araştırmayı izleyin</Link>
          </h2>
          <p>
            ContentOS adresleri bulur, uygun içerikleri getirir ve fikirleri
            değerlendirir. Her adresi tek tek onaylamanız gerekmez. Kaynağın
            makalesi çevrilip yayınlanmaz; özgün bir içerik için araştırma
            girdisi olur.
          </p>
        </li>
        <li>
          <h2>
            <Link href="/firsatlar">Sizden beklenen kararı verin</Link>
          </h2>
          <p>
            İlham değerini, hedef kitleyi, kaynak yeterliliğini ve önerinin
            nedenini okuyun. Arama verisinin bilinmemesi arama yapılmadığı veya
            talep olmadığı anlamına gelmez. Yetersiz kaynak uyarısını yalnızca
            gerekçeli editoryal kararınız varsa geçersiz kılın.
          </p>
        </li>
        <li>
          <h2>
            <Link href="/editorial">İçeriği ve görselleri inceleyin</Link>
          </h2>
          <p>
            Otomatik mod yazım planı, taslak, editör ve kalite kontrolünü
            ilerletir. Görsel seçimi veya çözülmeyen bir sorun sizi
            bekleyebilir. Son metni ve görselleri inceleyip yayın onayını verin;
            onaylı paket yayın bağlantısına gönderilir.
          </p>
        </li>
      </ol>
      <section className="detail-card">
        <h2>İyi Konsepthane içeriği nasıl görünür?</h2>
        <p>
          Okurun evinde veya etkinliğinde uygulayabileceği somut bir fikir,
          hazırlık ayrıntıları ve alternatifler sunar. İlgili olduğunda “Siz
          küçük bir alanda bu masayı nasıl düzenlediniz?” gibi doğal bir
          paylaşım sorusuyla konuşmaya alan açar. Sahte deneyim, uydurma fiyat
          ve tekrarlarla uzatılmış metin kullanılmaz.
        </p>
        <p>
          Günlük takip: <Link href="/kontrol">Kontrol Merkezi</Link> ve{" "}
          <Link href="/firsatlar">Benden Bekleyenler</Link>. Teknik ekranlar sol
          menüdeki Sistem ve ayrıntılar altında bulunur.
        </p>
      </section>
    </section>
  );
}
