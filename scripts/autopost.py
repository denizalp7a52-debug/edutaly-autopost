#!/usr/bin/env python3
"""
Edutaly otomatik paylaşım — GitHub Actions ile çalışır.

Komutlar:
  python scripts/autopost.py run              # zamanı gelen paylaşımları yap (cron bunu çağırır)
  python scripts/autopost.py check            # token, hesap ve görsel adreslerini kontrol et
  python scripts/autopost.py post <id>        # tek bir paylaşımı hemen yap (test)
  python scripts/autopost.py refresh-ig       # Instagram token süresini uzat
  python scripts/autopost.py status           # takvim özeti

Ortam değişkenleri (GitHub Secrets):
  IG_ACCESS_TOKEN      Instagram uzun ömürlü erişim anahtarı (zorunlu)
  IG_USER_ID           (opsiyonel) Instagram hesap kimliği, yoksa otomatik bulunur
  GH_PAT               (opsiyonel) yenilenen token'ı Secrets'a geri yazmak için
  TIKTOK_ENABLED       "true" olursa TikTok da paylaşılır (TikTok uygulama onayı sonrası)
  TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET / TIKTOK_REFRESH_TOKEN
  TIKTOK_PRIVACY       varsayılan PUBLIC_TO_EVERYONE (onaysız uygulamada SELF_ONLY)
  MEDIA_BASE_URL       (opsiyonel) görsellerin herkese açık adres kökü
  DRY_RUN              "true" ise hiçbir şey paylaşılmaz, sadece yazdırılır
"""
import json, os, subprocess, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib import request, parse, error

ROOT = Path(__file__).resolve().parent.parent
SCHEDULE = ROOT / "schedule.json"
STATE = ROOT / "posted.json"
IG_API = "https://graph.instagram.com/v21.0"
GRACE = timedelta(hours=int(os.getenv("GRACE_HOURS", "12")))   # geç kalan paylaşımı en fazla bu kadar sonra yap
MAX_PER_RUN = int(os.getenv("MAX_PER_RUN", "3"))
DRY = os.getenv("DRY_RUN", "").lower() == "true"


def log(*a):
    print(datetime.now(timezone.utc).strftime("%H:%M:%S"), *a, flush=True)


def http(method, url, params=None, json_body=None, headers=None, timeout=60):
    data = None
    headers = dict(headers or {})
    if params and method == "GET":
        url = url + ("&" if "?" in url else "?") + parse.urlencode(params)
    elif params:
        data = parse.urlencode(params).encode()
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json; charset=UTF-8"
    req = request.Request(url, data=data, method=method, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode()
            return r.status, (json.loads(body) if body.strip().startswith(("{", "[")) else body)
    except error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(body)
        except ValueError:
            return e.code, body


def media_url(rel):
    base = os.getenv("MEDIA_BASE_URL")
    if not base:
        repo = os.getenv("GITHUB_REPOSITORY", "")
        branch = os.getenv("GITHUB_REF_NAME", "main")
        if not repo:
            raise SystemExit("MEDIA_BASE_URL veya GITHUB_REPOSITORY tanımlı değil")
        base = f"https://raw.githubusercontent.com/{repo}/{branch}"
    return base.rstrip("/") + "/" + rel


def load():
    return json.loads(SCHEDULE.read_text("utf-8")), json.loads(STATE.read_text("utf-8"))


def save_state(state):
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), "utf-8")


def set_secret(name, value):
    """Yenilenen token'ı GitHub Secrets'a yaz (GH_PAT varsa)."""
    if not os.getenv("GH_PAT") or not os.getenv("GITHUB_REPOSITORY"):
        log(f"UYARI: {name} yenilendi ama GH_PAT yok; Secrets güncellenmedi.")
        return
    env = dict(os.environ, GH_TOKEN=os.environ["GH_PAT"])
    subprocess.run(["gh", "secret", "set", name, "--repo", os.environ["GITHUB_REPOSITORY"], "--body", value],
                   check=True, env=env, capture_output=True)
    log(f"{name} Secrets'a yazıldı.")


# ───────────────────────── Instagram ─────────────────────────
def ig_token():
    t = os.getenv("IG_ACCESS_TOKEN")
    if not t:
        raise RuntimeError("IG_ACCESS_TOKEN tanımlı değil")
    return t


def ig_user_id():
    if os.getenv("IG_USER_ID"):
        return os.environ["IG_USER_ID"]
    code, me = http("GET", f"{IG_API}/me", {"fields": "user_id,username", "access_token": ig_token()})
    if code != 200:
        raise RuntimeError(f"Instagram hesabı okunamadı: {me}")
    return str(me.get("user_id") or me["id"])


def ig_publish(item):
    uid = ig_user_id()
    params = {"image_url": media_url(item["image"]), "access_token": ig_token()}
    if item["kind"] == "story":
        params["media_type"] = "STORIES"
    else:
        params["caption"] = item["caption"]
    if DRY:
        log("DRY_RUN instagram", item["id"], params["image_url"]); return "dry-run"
    code, res = http("POST", f"{IG_API}/{uid}/media", params)
    if code != 200 or "id" not in res:
        raise RuntimeError(f"Instagram container hatası: {res}")
    cid = res["id"]
    for _ in range(30):                       # en fazla ~2.5 dk bekle
        code, st = http("GET", f"{IG_API}/{cid}", {"fields": "status_code", "access_token": ig_token()})
        sc = st.get("status_code") if isinstance(st, dict) else None
        if sc == "FINISHED":
            break
        if sc in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram medya işlenemedi: {st}")
        time.sleep(5)
    code, pub = http("POST", f"{IG_API}/{uid}/media_publish", {"creation_id": cid, "access_token": ig_token()})
    if code != 200 or "id" not in pub:
        raise RuntimeError(f"Instagram yayınlama hatası: {pub}")
    return pub["id"]


def ig_refresh():
    code, res = http("GET", "https://graph.instagram.com/refresh_access_token",
                     {"grant_type": "ig_refresh_token", "access_token": ig_token()})
    if code != 200 or "access_token" not in res:
        raise RuntimeError(f"Token yenilenemedi: {res}")
    days = int(res.get("expires_in", 0)) // 86400
    log(f"Instagram token yenilendi, {days} gün geçerli.")
    if res["access_token"] != ig_token():
        set_secret("IG_ACCESS_TOKEN", res["access_token"])


# ───────────────────────── TikTok (onay sonrası) ─────────────────────────
def tiktok_enabled():
    return os.getenv("TIKTOK_ENABLED", "").lower() == "true"


def tiktok_access_token():
    code, res = http("POST", "https://open.tiktokapis.com/v2/oauth/token/", {
        "client_key": os.environ["TIKTOK_CLIENT_KEY"], "client_secret": os.environ["TIKTOK_CLIENT_SECRET"],
        "grant_type": "refresh_token", "refresh_token": os.environ["TIKTOK_REFRESH_TOKEN"]})
    if code != 200 or "access_token" not in res:
        raise RuntimeError(f"TikTok token alınamadı: {res}")
    if res.get("refresh_token") and res["refresh_token"] != os.environ["TIKTOK_REFRESH_TOKEN"]:
        set_secret("TIKTOK_REFRESH_TOKEN", res["refresh_token"])
    return res["access_token"]


def tiktok_publish(item):
    first_line = item["caption"].split("\n")[0][:90]
    body = {
        "post_info": {"title": first_line, "description": item["caption"][:4000],
                      "privacy_level": os.getenv("TIKTOK_PRIVACY", "PUBLIC_TO_EVERYONE"),
                      "disable_comment": False, "auto_add_music": True},
        "source_info": {"source": "PULL_FROM_URL", "photo_cover_index": 0,
                        "photo_images": [media_url(item["image"])]},
        "post_mode": "DIRECT_POST", "media_type": "PHOTO"}
    if DRY:
        log("DRY_RUN tiktok", item["id"], body["source_info"]["photo_images"][0]); return "dry-run"
    code, res = http("POST", "https://open.tiktokapis.com/v2/post/publish/content/init/", json_body=body,
                     headers={"Authorization": f"Bearer {tiktok_access_token()}"})
    if code != 200 or res.get("error", {}).get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok hatası: {res}")
    return res.get("data", {}).get("publish_id", "ok")


PUBLISHERS = {"instagram": ig_publish, "tiktok": tiktok_publish}


def platform_on(p):
    return p == "instagram" and bool(os.getenv("IG_ACCESS_TOKEN")) or p == "tiktok" and tiktok_enabled()


# ───────────────────────── commands ─────────────────────────
def publish_item(item, state):
    try:
        ref = PUBLISHERS[item["platform"]](item)
        state["done"][item["id"]] = {"status": "posted", "at": datetime.now(timezone.utc).isoformat(), "ref": ref}
        log("PAYLAŞILDI", item["id"], item["topic"], ref)
        return True
    except Exception as e:  # bir hata diğerlerini durdurmasın
        n = state.setdefault("errors", {}).get(item["id"], 0) + 1
        state["errors"][item["id"]] = n
        log("HATA", item["id"], e)
        return False


def now_utc():
    t = os.getenv("NOW_UTC")      # sadece test için
    return datetime.fromisoformat(t.replace("Z", "+00:00")) if t else datetime.now(timezone.utc)


def cmd_run():
    sched, state = load()
    now = now_utc()
    posted, failed = 0, 0
    for item in sorted(sched["items"], key=lambda i: i["when_utc"]):
        if item["id"] in state["done"] or not platform_on(item["platform"]):
            continue
        when = datetime.fromisoformat(item["when_utc"].replace("Z", "+00:00"))
        if when > now:
            continue
        if now - when > GRACE:
            state["done"][item["id"]] = {"status": "missed", "at": now.isoformat()}
            log("KAÇIRILDI (süre geçti)", item["id"]); continue
        if state.get("errors", {}).get(item["id"], 0) >= 3:
            continue
        if posted >= MAX_PER_RUN:
            break
        if publish_item(item, state):
            posted += 1
        else:
            failed += 1
    save_state(state)
    log(f"Bitti: {posted} paylaşıldı, {failed} hata.")
    if failed:
        sys.exit(1)        # GitHub e-posta ile haber verir


def cmd_post(item_id):
    sched, state = load()
    item = next((i for i in sched["items"] if i["id"] == item_id), None)
    if not item:
        raise SystemExit(f"Bulunamadı: {item_id}")
    ok = publish_item(item, state)
    save_state(state)
    sys.exit(0 if ok else 1)


def cmd_check():
    sched, _ = load()
    ok = True
    if os.getenv("IG_ACCESS_TOKEN"):
        code, me = http("GET", f"{IG_API}/me", {"fields": "user_id,username,account_type", "access_token": ig_token()})
        log("Instagram:", code, me)
        ok &= code == 200
    else:
        log("Instagram: IG_ACCESS_TOKEN yok"); ok = False
    for item in sched["items"][:2]:
        url = media_url(item["image"])
        try:
            with request.urlopen(request.Request(url, method="HEAD"), timeout=30) as r:
                log("Görsel", r.status, r.headers.get("Content-Type"), url)
        except Exception as e:
            log("Görsel ERİŞİLEMEDİ", url, e); ok = False
    log("TikTok:", "açık" if tiktok_enabled() else "kapalı")
    sys.exit(0 if ok else 1)


def cmd_status():
    sched, state = load()
    now = datetime.now(timezone.utc)
    for item in sched["items"]:
        st = state["done"].get(item["id"], {}).get("status", "bekliyor")
        if st == "bekliyor" and not platform_on(item["platform"]):
            st = "platform kapalı"
        print(f'{item["when_utc"]}  {item["platform"]:9} {item["kind"]:5}  {st:15} {item["topic"]}')
    print("şimdi:", now.isoformat())


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    {"run": cmd_run, "check": cmd_check, "status": cmd_status, "refresh-ig": ig_refresh,
     "post": lambda: cmd_post(sys.argv[2])}[cmd]()
