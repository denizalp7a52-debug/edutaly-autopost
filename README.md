# Edutaly otomatik paylaşım

GitHub Actions üzerinde ücretsiz çalışır. Bilgisayarın açık olması gerekmez.

- `schedule.json`: 30 günlük takvim (saatler UTC; Türkiye = UTC+3)
  - Her gün 12:30 TR: Instagram hikayesi
  - Her gün 19:00 TR: Instagram postu (+ onay sonrası TikTok)
- `media/`: paylaşılacak görseller
- `posted.json`: neyin paylaşıldığının kaydı (sistem kendisi günceller)
- `scripts/autopost.py`: paylaşım programı

## Kurulum (bir kez)

1. **Depo:** GitHub'da `edutaly-autopost` adında **Public** bir depo aç ve bu klasörün tüm içeriğini yükle.
   Instagram görselleri herkese açık bir adresten çektiği için depo açık olmalı.
2. **Meta uygulaması:** developers.facebook.com → Uygulama oluştur → "Instagram API" ürünü →
   "Instagram girişiyle API kurulumu" → hesabını (@edutalyegitimvedanismanlik) ekle → **Erişim anahtarı oluştur**.
   İzinler: `instagram_business_basic`, `instagram_business_content_publish`.
3. **Secrets:** Depo → Settings → Secrets and variables → Actions → New repository secret
   - `IG_ACCESS_TOKEN` = 2. adımdaki anahtar
   - `GH_PAT` (önerilir) = GitHub → Settings → Developer settings → Fine-grained token,
     sadece bu depo, izin: **Secrets: Read and write**. Haftalık yenilenen anahtarı otomatik kaydeder.
4. **Test:** Actions → "Otomatik paylaşım" → Run workflow → command: `check`. Yeşil olmalı.
   İstersen `post` + `day01-story` ile tek bir hikayeyi hemen dene.

Bundan sonra sistem kendi kendine çalışır. Bir paylaşım başarısız olursa GitHub e-posta gönderir.

## Sık işler

- **Takvimi görmek:** Actions → Run workflow → `status`
- **Durdurmak:** Actions → "Otomatik paylaşım" → ⋯ → Disable workflow
- **Deneme modu:** Settings → Variables → `DRY_RUN` = `true` (hiçbir şey paylaşılmaz)
- **Yeni içerik eklemek:** `media/` içine görseli koy, `schedule.json`'a bir satır ekle.

## TikTok

TikTok'un API'si, uygulaması onaylanmamış hesaplarda paylaşımları sadece **gizli** yapar.
developers.tiktok.com'da uygulama aç → "Content Posting API" → onaya gönder.
Onay gelince Secrets'a `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN`,
Variables'a `TIKTOK_ENABLED` = `true` ekle. TikTok, fotoğrafı çektiği alan adının doğrulanmasını da ister
(ör. `edutaly.com` alt alanı → `MEDIA_BASE_URL`).

Not: Vize ve konsolosluk işlemleri Edutaly hizmet kapsamı dışındadır; açıklamalar buna göre yazıldı.
