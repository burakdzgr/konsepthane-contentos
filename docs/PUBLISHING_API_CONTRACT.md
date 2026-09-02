# Konsepthane Publishing API v1 Contract

> Operator-supplied and ACCEPTED on 2026-09-02. This document is the
> authoritative wire contract the ContentOS `HttpPublishingTransport`
> implements. The API's production owner is the Konsepthane main
> backend; ContentOS is only an authenticated client.

## Amaç

Konsepthane ContentOS yalnızca **insan tarafından onaylanmış exact
publication package**'ı Konsepthane ana platformuna gönderir.

ContentOS:

* Konsepthane DB'ye erişmez.
* Konsepthane filesystem'e erişmez.
* İçeriği publish sırasında tekrar yazmaz/değiştirmez.
* Yalnızca bu API üzerinden yayın yapar.

API'nin sahibi **Konsepthane ana backend**'idir.

## Base URL

Production ortamında config ile verilecek: `CONTENTOS_PUBLISHING_API_URL`

Bu değer örneğin şu path'in önüne kadar gelir:

`https://<konsepthane-host>/api/internal/contentos`

ContentOS ardından `/v1/...` endpointlerini kullanır.

## Authentication

V1 için: `Authorization: Bearer <service-token>`

Token:

* yalnızca ContentOS'a ait olacak,
* yalnızca publishing API yetkisine sahip olacak,
* admin/user tokenı olmayacak,
* HTTPS dışında kullanılamayacak,
* secret olarak tutulacak,
* rotate edilebilir olacak.

ContentOS tarafı: `CONTENTOS_PUBLISHING_API_KEY`. Konsepthane tarafı
karşılığı olan secret ile doğrulayacak.

## 1. Media Upload

### Endpoint

`PUT /v1/media/{sha256}` — media content-addressed olarak yüklenir.

### Headers

```text
Authorization: Bearer <service-token>
Content-Type: image/png | image/jpeg | image/webp | ...
X-Content-SHA256: <sha256>
Idempotency-Key: media:<sha256>
```

Body: raw binary media bytes.

Konsepthane:

1. byte'ları alır,
2. SHA-256'yı yeniden hesaplar,
3. URL/path'teki SHA ile karşılaştırır,
4. uyuşmazsa reddeder,
5. aynı SHA daha önce yüklendiyse duplicate oluşturmaz.

### Success

```json
{
  "schema_version": "media-upload-result/1",
  "media_ref": "media-uuid",
  "content_sha256": "...",
  "status": "stored"
}
```

Aynı dosya tekrar gönderilirse aynı `media_ref` dönmelidir.

## 2. Publish

### Endpoint

`POST /v1/publications`

### Headers

```text
Authorization: Bearer <service-token>
Idempotency-Key: <ContentOS generated publishing idempotency key>
Content-Type: application/json
X-Request-Id: <correlation id>
```

### Request

```json
{
  "package": {
    "schema_version": "publication-package/1",
    "work_item_id": "uuid",
    "locale": "tr-TR",
    "market": "TR",
    "title_proposal": "İçerik başlığı",
    "body_schema_version": "writer-draft-body/1",
    "body": {}
  },
  "media_manifest": {
    "needs": {
      "0": {
        "media_asset_id": "uuid",
        "content_sha256": "...",
        "media_type": "image/webp",
        "byte_size": 123456,
        "alt_text": "...",
        "license_note": "...",
        "source_attribution": "...",
        "origin": "..."
      }
    },
    "waived_unmet_indexes": []
  }
}
```

Konsepthane bu body'nin metinsel anlamını değiştiremez.

Konsepthane tarafının görevi:

* structured body'yi kendi content modeline çevirmek,
* HTML/rendering yapmak,
* slug üretmek,
* media SHA'larını daha önce yüklenen media kayıtlarıyla eşlemek,
* veritabanına atomik biçimde kaydetmek,
* public identity oluşturmak.

## Idempotency

Bu zorunludur. Aynı `Idempotency-Key + aynı request` tekrar gelirse
**ikinci içerik oluşturulmaz** — daha önce oluşmuş publication sonucu
geri döndürülür.

Aynı `Idempotency-Key` ile farklı payload gelirse `409 Conflict`:

```json
{ "error": { "code": "idempotency_conflict" } }
```

Bu sayede timeout/redelivery durumunda çift içerik yayınlanamaz.

## Successful Response

İlk yayın: `201 Created`. Retry/idempotent replay: `200 OK`.

```json
{
  "schema_version": "publication-result/1",
  "publication_ref": "article:uuid",
  "content_id": "uuid",
  "version": 1,
  "status": "published",
  "canonical_url": "https://konsepthane.com/...",
  "published_at": "2026-09-02T20:00:00Z"
}
```

ContentOS için minimum zorunlu alan: `publication_ref`. Diğer alanlar
reconciliation/analytics için saklanabilir.

## Error Contract

Tüm hatalar machine-readable olmalı:

```json
{ "error": { "code": "invalid_package", "message": "safe bounded message" } }
```

Temel statuslar:

* `400` malformed request
* `401` authentication failed
* `403` service not allowed
* `409` idempotency conflict
* `413` media too large
* `422` package/media validation failed
* `429` rate limited
* `500` server failure
* `503` temporarily unavailable

4xx validation/rejection hataları ContentOS'ta `rejected_by_api`,
5xx/network `transport_error`, timeout `timeout` olarak kaydedilir.

> ContentOS client note: `429 rate limited` is transient, not a
> validation/rejection of the package, and is therefore recorded as
> `transport_error` (`publishing_api_rate_limited`) so bounded retries
> apply instead of a terminal BLOCK.

## Publication Atomicity

`POST /v1/publications` başarılı döndüyse içerik gerçekten Konsepthane
tarafında durable olmalıdır. Önce durable kayıt, sonra success
response — asla tersi değil.

## Media Rule

Publication içindeki media manifest'te bulunan SHA'lar daha önce
`/v1/media/{sha256}` üzerinden yüklenmiş olmalıdır. Eksik, waiver
olmayan media varsa publication reddedilir. `waived_unmet_indexes` ise
bilinçli olarak mediasız bırakılmış ihtiyaçlardır ve publish'i
engellemez.

## Rendering Ownership

ContentOS: **editorial content sahibi**. Konsepthane:
**rendering/public platform sahibi**.

Konsepthane: HTML oluşturabilir, component/block mapping yapabilir,
slug oluşturabilir, canonical URL oluşturabilir, media URL
oluşturabilir. Ama: yeni factual claim ekleyemez, paragraph yeniden
yazamaz, başlığı AI ile değiştiremez, içeriği enrich edemez.

## Production Ownership

Publishing API'nin production sahibi: **Konsepthane
backend/application**. ContentOS yalnızca authenticated client'tır.

`ContentOS → API → Konsepthane application/service layer → Konsepthane DB`

Asla: `ContentOS → Konsepthane DB`.

## V1 Contract Decision

Accepted V1:

* Bearer service authentication
* content-addressed media upload
* idempotent publication POST
* immutable approved package
* receiver-side rendering
* durable publication reference
* no direct production access
* retry-safe semantics
