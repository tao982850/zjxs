# -*- coding: utf-8 -*-
"""
IFN影视 TVBox 爬虫 - v9 极速版
修复: 1)强制清理旧缓存 2)token持久化复用 3)播放极速路径
站点: https://cn1.ifn.watch
"""
import sys, re, json, time, random, urllib.request, urllib.error, urllib.parse, os, threading

sys.path.append('..')
try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def fetch(self, url, headers=None, **kw):
            req = urllib.request.Request(url, headers=headers or {}, method=kw.get('method','GET'))
            data = kw.get('data')
            if data:
                req.data = data.encode('utf-8') if isinstance(data,str) else data
            with urllib.request.urlopen(req, timeout=kw.get('timeout',15)//1000 if kw.get('timeout',15)>1000 else kw.get('timeout',15)) as r:
                class R:
                    status_code = getattr(r,'status',200)
                    text = r.read().decode('utf-8','ignore')
                return R()

HOST = "https://cn1.ifn.watch"
HOSTS = ["https://cn1.ifn.watch", "https://ifn.watch"]
SUPA = "https://rvcrrwdtggvbomvzvpev.supabase.co"
MAIL = "https://api.mail.tm"
ANON = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJ2Y3Jyd2R0Z2d2Ym9tdnp2cGV2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDQ5MzEwNjUsImV4cCI6MjA2MDUwNzA2NX0.eiNtiUxJxXZzYn1uFRtKaPAXim64vP6brgRWxgMcmyE"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
CATEGORIES = {"3":"电影","4":"剧集","5":"综艺","6":"动漫","8":"短剧","7":"纪录片","40":"4K"}
RESLO = re.compile(r'^(576P|720P|1080P|2160P)$', re.I)
CACHE_VER = "v9"

# 种子账户池
SEED_ACCOUNTS = [
    ("tvbox_997185@uberip.com", "Tvbox123456!"),
    ("tvbox_641630@uberip.com", "Tvbox123456!"),
    ("tvbox_342153@uberip.com", "Tvbox123456!"),
    ("tvbox_629519@uberip.com", "Tvbox123456!"),
    ("tvbox_146602@uberip.com", "Tvbox123456!"),
    ("tvbox_400937@uberip.com", "Tvbox123456!"),
    ("tvbox_164318@uberip.com", "Tvbox123456!"),
    ("tvbox_301941@uberip.com", "Tvbox123456!"),
    ("tvbox_385633@uberip.com", "Tvbox123456!"),
    ("tvbox_137667@uberip.com", "Tvbox123456!"),
    ("tvbox_739984@uberip.com", "Tvbox123456!"),
    ("tvbox_421018@uberip.com", "Tvbox123456!"),
    ("tvbox_962186@uberip.com", "Tvbox123456!"),
    ("tvbox_646115@uberip.com", "Tvbox123456!"),
    ("tvbox_798029@uberip.com", "Tvbox123456!"),
    ("tvbox_622361@uberip.com", "Tvbox123456!"),
    ("tvbox_501265@uberip.com", "Tvbox123456!"),
    ("tvbox_480213@uberip.com", "Tvbox123456!"),
    ("tvbox_120840@uberip.com", "Tvbox123456!"),
    ("tvbox_892742@uberip.com", "Tvbox123456!"),
    ("tvbox_551292@uberip.com", "Tvbox123456!"),
    ("tvbox_818095@uberip.com", "Tvbox123456!"),
    ("tvbox_965116@uberip.com", "Tvbox123456!"),
    ("tvbox_604605@uberip.com", "Tvbox123456!"),
    ("tvbox_799549@uberip.com", "Tvbox123456!"),
    ("tvbox_900410@uberip.com", "Tvbox123456!"),
    ("tvbox_580448@uberip.com", "Tvbox123456!"),
    ("tvbox_219285@uberip.com", "Tvbox123456!"),
    ("tvbox_846877@uberip.com", "Tvbox123456!"),
    ("tvbox_968191@uberip.com", "Tvbox123456!"),
    ("tvbox_848558@uberip.com", "Tvbox123456!"),
]

class _UR:
    def __init__(self, resp=None, body=None):
        if body is not None:
            self._body = body
            self.status_code = getattr(resp,'status',200)
            return
        try:
            self.status_code = resp.status
            self._body = resp.read()
        except:
            self.status_code = 0
            self._body = b''
    @property
    def text(self):
        return self._body.decode('utf-8','ignore')
    def read(self):
        return self._body

def _json(r):
    try:
        return json.loads(r.text if hasattr(r,'text') else r)
    except:
        return None

def _log(msg):
    try:
        with open('/sdcard/Download/ifn_diag.txt','a') as f:
            f.write("%s %s\n" % (time.strftime('%H:%M:%S'), msg))
    except:
        pass

class Spider(Spider):
    def init(self, extend=""):
        self._ver = CACHE_VER
        self._at = ""; self._at_ts = 0.0; self._rt = ""
        self._mail = ""; self._pwd = ""; self._host = ""
        self._pick_t = 0.0; self._last = ""
        self._acc_idx = 0; self._accounts = []
        self._live_accounts = []
        self._token_cache = {}
        self._register_cooldown = 0
        self._supply_cooldown = 0
        self._cache_loaded = False
        self._load_cache()
        # 首次初始化或旧缓存清理后重建活跃列表
        if not self._live_accounts:
            self._live_accounts = [em for em, pw in SEED_ACCOUNTS]
            _log("v9 live init %d" % len(self._live_accounts))
        if extend and "|" in str(extend):
            e = str(extend).split("|")
            self._mail = e[0].strip()
            self._pwd = e[1].strip() if len(e)>1 else ""
        if self._rt:
            try:
                self._refresh()
            except:
                pass
        # 后台预热前3个账户token缓存（不阻塞主流程）
        threading.Thread(target=self._warmup, daemon=True).start()

    def _warmup(self):
        """后台预热token缓存"""
        try:
            for em, pw in SEED_ACCOUNTS[:3]:
                if em in self._token_cache and time.time() - self._token_cache[em].get("ts",0) < 300:
                    continue
                self._login_cached(em, pw)
        except:
            pass

    def _cache_paths(self):
        return [os.path.join(os.getcwd(),'.ifn_sess.json'),'/sdcard/Download/.ifn_sess.json','/storage/emulated/0/Download/.ifn_sess.json']

    def _pick(self):
        if self._host:
            return self._host
        now = time.time()
        if self._pick_t and now - self._pick_t < 10:
            return self._host or HOST
        self._pick_t = now
        for h in HOSTS:
            try:
                req = urllib.request.Request(h+"/", headers={"User-Agent":UA}, method="HEAD")
                r = urllib.request.urlopen(req, timeout=5)
                if r.status == 200:
                    self._host = h; return h
            except:
                pass
        self._host = HOST; return HOST

    def _ureq(self, url, headers=None, method='GET', data=None, timeout=30):
        hd = dict(headers or {}); hd.setdefault('User-Agent', UA)
        body = data.encode('utf-8') if isinstance(data,str) else data
        req = urllib.request.Request(url, data=body, headers=hd, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return _UR(resp)
        except urllib.error.HTTPError as e:
            return _UR(e)
        except:
            return None

    def _req(self, url, headers=None, method='GET', data=None):
        try:
            r = self.fetch(url, headers=headers, method=method, data=data, timeout=30000)
            if r is not None:
                st = getattr(r,'status_code',0)
                if st:
                    return r
            return self._ureq(url, headers, method, data)
        except:
            return self._ureq(url, headers, method, data)

    def _text(self, r):
        if r is None: return ""
        if hasattr(r,'text'): return r.text
        if isinstance(r,(bytes,bytearray)): return r.decode('utf-8','ignore')
        return str(r)

    def _supa_headers(self):
        return {"apikey":ANON,"Authorization":"Bearer "+(self._at or ANON),"Content-Type":"application/json"}

    def _supa_post(self, path, obj):
        return self._req(SUPA+path, headers=self._supa_headers(), method='POST', data=json.dumps(obj))

    def _refresh(self):
        if not self._rt: return False
        r = self._supa_post("/auth/v1/token?grant_type=refresh_token", {"refresh_token":self._rt})
        d = _json(r)
        if not d: return False
        at = d.get("access_token","")
        if at:
            self._at = at; self._at_ts = time.time()
            self._rt = d.get("refresh_token", self._rt)
            return True
        return False

    def _login(self, email, pwd):
        r = self._supa_post("/auth/v1/token?grant_type=password", {"email":email,"password":pwd})
        d = _json(r)
        if not d: return False
        at = d.get("access_token","")
        if at:
            self._at = at; self._at_ts = time.time()
            self._rt = d.get("refresh_token","")
            self._mail = email; self._pwd = pwd
            self._save_cache()
            _log("login OK %s" % email)
            return True
        _log("login FAIL %s" % email)
        return False

    def _login_cached(self, email, pwd):
        """登录并缓存token，返回是否成功"""
        r = self._supa_post("/auth/v1/token?grant_type=password", {"email":email,"password":pwd})
        d = _json(r)
        if not d: return False
        at = d.get("access_token","")
        if at:
            ts = time.time()
            self._token_cache[email] = {"at": at, "rt": d.get("refresh_token",""), "ts": ts}
            self._save_cache()
            return True
        return False

    def _try_play(self, h, mediaId, episodeId, title):
        if not self._at:
            return None
        r = self._req(h+"/api/play/token",
            headers={"Content-Type":"application/json","Authorization":"Bearer "+self._at,"Referer":h+"/"},
            method='POST', data=json.dumps({"mediaId":mediaId,"episodeId":episodeId,"title":title}))
        if r is None:
            return None
        body = self._text(r)
        try:
            d = json.loads(body)
            if d.get("success"):
                return d.get("token","")
            code = str(d.get("code","")).upper()
            if "INSUFFICIENT" in code or "积分" in body:
                return "INSUFFICIENT"
            if "未授权" in body or "UNAUTHORIZED" in code:
                return "UNAUTHORIZED"
            _log("play_token err: %s" % body[:100])
        except:
            pass
        return None

    def _play_token(self, mediaId, episodeId, title):
        """获取播放token — 极速路径：优先缓存token直接试播"""
        h = self._pick()

        if not mediaId:
            _log("play_token empty mediaId")
            return ""

        if not self._live_accounts:
            self._live_accounts = [em for em, pw in SEED_ACCOUNTS]
            _log("v9 live init %d" % len(self._live_accounts))

        def _try_one():
            if not self._at:
                return None, "NO_TOKEN"
            tok = self._try_play(h, mediaId, episodeId, title)
            if tok and tok not in ("INSUFFICIENT", "UNAUTHORIZED"):
                return tok, "OK"
            if tok == "INSUFFICIENT":
                return None, "INSUFFICIENT"
            if tok == "UNAUTHORIZED":
                return None, "UNAUTHORIZED"
            return None, "FAIL"

        # === 极速路径1：当前session有效，直接试播 ===
        if self._at and self._mail in self._live_accounts and time.time() - self._at_ts < 600:
            tok, status = _try_one()
            if status == "OK":
                return tok
            if status == "INSUFFICIENT":
                self._remove_live(self._mail, "insufficient")
                self._at = ""
            elif status == "UNAUTHORIZED":
                if self._rt and self._refresh():
                    tok2, status2 = _try_one()
                    if status2 == "OK":
                        return tok2
                self._remove_live(self._mail, "unauthorized")
                self._at = ""; self._rt = ""
            # FAIL: token可能临时失效，不杀账户，继续轮询

        # === 极速路径2：缓存token直接试播（无需重新登录）===
        for em in self._live_accounts[:]:
            cached = self._token_cache.get(em)
            if cached and time.time() - cached.get("ts", 0) < 600:
                self._at = cached["at"]
                self._rt = cached.get("rt", "")
                self._at_ts = cached["ts"]
                self._mail = em
                tok, status = _try_one()
                if status == "OK":
                    return tok
                if status == "INSUFFICIENT":
                    self._remove_live(em, "insufficient")
                    self._token_cache.pop(em, None)
                    self._at = ""
                elif status == "UNAUTHORIZED":
                    if self._rt and self._refresh():
                        tok2, status2 = _try_one()
                        if status2 == "OK":
                            return tok2
                    self._remove_live(em, "unauthorized")
                    self._token_cache.pop(em, None)
                    self._at = ""; self._rt = ""
                else:
                    # FAIL: 缓存token可能临时失效，清除缓存但不杀账户
                    self._token_cache.pop(em, None)
                    self._at = ""

        # === 慢速路径：登录+试播 ===
        for em in self._live_accounts[:]:
            pw = None
            for e, p in SEED_ACCOUNTS:
                if e == em: pw = p; break
            if not pw:
                self._remove_live(em, "no_pw")
                continue

            if not self._login_cached(em, pw):
                continue

            self._at = self._token_cache[em]["at"]
            self._rt = self._token_cache[em]["rt"]
            self._at_ts = self._token_cache[em]["ts"]
            self._mail = em; self._pwd = pw

            tok, status = _try_one()
            if status == "OK":
                _log("play OK %s left=%d" % (em[:20], len(self._live_accounts)))
                return tok

            if status == "INSUFFICIENT":
                self._remove_live(em, "insufficient")
                self._token_cache.pop(em, None)
                self._at = ""
            elif status == "UNAUTHORIZED":
                if self._rt and self._refresh():
                    tok2, status2 = _try_one()
                    if status2 == "OK":
                        return tok2
                self._remove_live(em, "unauthorized")
                self._token_cache.pop(em, None)
                self._at = ""; self._rt = ""
            else:
                # FAIL: 不杀账户，只清除本次token
                self._token_cache.pop(em, None)
                self._at = ""

        # 全部耗尽，紧急补充
        _log("live EMPTY, supplement")
        if self._supplement_accounts(2):
            for em in self._live_accounts[:5]:
                pw = None
                for e, p in SEED_ACCOUNTS:
                    if e == em: pw = p; break
                if not pw: continue
                if not self._login_cached(em, pw):
                    continue
                self._at = self._token_cache[em]["at"]
                self._mail = em
                tok, status = _try_one()
                if status == "OK":
                    _log("play OK after supplement %s" % em[:20])
                    return tok

        _log("play FAIL all")
        return ""

    def _remove_live(self, email, reason):
        """从活跃列表移除并记录原因"""
        if email in self._live_accounts:
            self._live_accounts.remove(email)
            _log("live dead %s (%s) left=%d" % (email[:20], reason, len(self._live_accounts)))
            self._save_cache()

    def _supplement_accounts(self, count=2):
        """补充注册账户"""
        now = time.time()
        if now < self._register_cooldown:
            _log("supplement cooldown")
            return 0

        success = 0
        for attempt in range(count):
            try:
                r1 = self._req(MAIL+"/domains")
                d1 = _json(r1)
                if not d1 or not d1.get("hydra:member"):
                    continue
                domain = d1["hydra:member"][0]["domain"]
                addr = "tvbox_%d@%s" % (random.randint(100000,999999), domain)
                pwd = "Tvbox123456!"

                r2 = self._req(MAIL+"/accounts", headers={"Content-Type":"application/json"},
                    method='POST', data=json.dumps({"address":addr,"password":pwd}))
                if not r2 or getattr(r2,'status_code',0) >= 400:
                    if r2 and getattr(r2,'status_code',0) == 429:
                        self._register_cooldown = now + 30
                    continue

                r3 = self._req(MAIL+"/token", headers={"Content-Type":"application/json"},
                    method='POST', data=json.dumps({"address":addr,"password":pwd}))
                d3 = _json(r3)
                mt = d3.get("token","") if d3 else ""
                if not mt:
                    continue

                r4 = self._req(SUPA+"/auth/v1/signup", headers={"apikey":ANON,"Content-Type":"application/json"},
                    method='POST', data=json.dumps({"email":addr,"password":pwd}))
                if not r4:
                    continue

                vlink = ""
                for _ in range(16):
                    time.sleep(0.5)
                    r5 = self._req(MAIL+"/messages", headers={"Authorization":"Bearer "+mt})
                    d5 = _json(r5)
                    if d5 and d5.get("hydra:member"):
                        for item in d5["hydra:member"]:
                            mid = item.get("id","")
                            if not mid: continue
                            r6 = self._req(MAIL+"/messages/"+mid, headers={"Authorization":"Bearer "+mt})
                            body = self._text(r6)
                            m = re.search(r'https://[^"\'\s<>]+?/auth/v1/verify\?token=[a-f0-9]+&type=signup[^"\'\s<>]*', body)
                            if m:
                                vlink = m.group(0).replace('\\','')
                                break
                        if vlink:
                            break
                if not vlink:
                    continue

                self._req(vlink, headers={"User-Agent":UA})

                if (addr,pwd) not in SEED_ACCOUNTS:
                    SEED_ACCOUNTS.append((addr,pwd))
                if (addr,pwd) not in self._accounts:
                    self._accounts.append((addr,pwd))
                if addr not in self._live_accounts:
                    self._live_accounts.append(addr)

                self._save_cache()
                success += 1
                _log("supplemented %s" % addr)

            except Exception as e:
                _log("supplement exc: %s" % str(e)[:60])

        if success == 0:
            self._register_cooldown = time.time() + 30
        return success

    def _ensure_supply(self):
        """后台检测补充"""
        try:
            if not self._live_accounts:
                return
            if len(self._live_accounts) >= 10:
                return
            now = time.time()
            if now < self._supply_cooldown:
                return
            need = 10 - len(self._live_accounts)
            if need > 0:
                _log("supply trigger need=%d" % need)
                got = self._supplement_accounts(min(need, 2))
                _log("supply got %d, live=%d" % (got, len(self._live_accounts)))
            if len(self._live_accounts) >= 10:
                self._supply_cooldown = now + 60
            else:
                self._supply_cooldown = now + 300
        except Exception as e:
            _log("supply exc: %s" % str(e)[:60])

    def _save_cache(self):
        try:
            data = json.dumps({
                "ver": CACHE_VER,
                "rt": self._rt,
                "mail": self._mail,
                "pwd": self._pwd,
                "accounts": getattr(self,'_accounts',[]),
                "live": getattr(self,'_live_accounts',[]),
                "tokens": getattr(self,'_token_cache',{})
            })
            for p in self._cache_paths():
                try:
                    with open(p,'w') as f:
                        f.write(data)
                    return
                except:
                    pass
        except:
            pass

    def _load_cache(self):
        try:
            for p in self._cache_paths():
                try:
                    with open(p) as f:
                        d = json.loads(f.read())
                    # 版本检查：旧缓存强制丢弃
                    if d.get("ver") != CACHE_VER:
                        _log("cache ver mismatch %s != %s, reset" % (d.get("ver","?"), CACHE_VER))
                        self._live_accounts = [em for em, pw in SEED_ACCOUNTS]
                        self._token_cache = {}
                        self._save_cache()
                        return True
                    acc = d.get("accounts",[]) or []
                    self._rt = self._rt or d.get("rt","")
                    if not self._mail:
                        self._mail = d.get("mail","")
                        self._pwd = d.get("pwd","")
                    self._accounts = acc
                    live = d.get("live",[])
                    if live:
                        self._live_accounts = live
                    # 恢复token缓存
                    tokens = d.get("tokens",{})
                    if tokens:
                        self._token_cache = tokens
                        _log("cache loaded %d tokens" % len(tokens))
                    for em,pw in acc:
                        if (em,pw) not in SEED_ACCOUNTS:
                            SEED_ACCOUNTS.append((em,pw))
                    self._cache_loaded = True
                    return True
                except:
                    pass
        except:
            pass
        return False

    def _items(self, html):
        items, seen, names = [], set(), set()
        for m in re.finditer(r'<a href="(/detail/([^"]+))" title="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL):
            vid = m.group(2); name = m.group(3).strip()[:80]
            if vid in seen or name in names:
                continue
            seen.add(vid); names.add(name)
            b = m.group(4)
            im = re.search(r'<img[^>]*src="(/api/image/[^"]+)"', b)
            if not im:
                im = re.search(r'<img[^>]*src="(https?://[^"]+)"', b)
            pic = im.group(1) if im else ""
            if pic.startswith('/') and not pic.startswith('//'):
                pic = self._pick() + pic
            elif pic.startswith('//'):
                pic = 'https:' + pic
            remark = ""
            for rpat in [r'<span[^>]*class="[^"]*(?:rating|score|rate|year|tag)[^"]*"[^>]*>([^<]+)']:
                rm = re.search(rpat, b)
                if rm:
                    remark = rm.group(1).strip()
                    break
            items.append({"vod_id":vid, "vod_name":name, "vod_pic":pic, "vod_remarks":remark})
        return items

    def _detail_data(self, html):
        BS = chr(92)
        def _close(txt, start, br, bl):
            dep = 0; kk = start; esc = False; ins = False
            while kk < len(txt):
                c = txt[kk]
                if esc: esc = False
                elif c == BS: esc = True
                elif ins:
                    if c == '"': ins = False
                else:
                    if c == '"': ins = True
                    elif c == bl: dep += 1
                    elif c == br:
                        dep -= 1
                        if dep == 0: return kk
                kk += 1
            return -1
        def _loads(seg):
            seg = seg.replace(BS*3+'"', chr(1))
            for _ in range(6):
                n = seg.replace(BS*2+'"', BS+'"')
                if n == seg: break
                seg = n
            seg = seg.replace(BS+'"', '"').replace(chr(1), BS+'"')
            try:
                return json.loads(seg)
            except:
                return None
        try:
            chunks = re.findall(r'self\.__next_f\.push\(\[1,\s*"((?:\\.|[^"\\])*)"', html)
            if chunks:
                payload = ''.join(json.loads('"%s"'%c) for c in chunks)
                i = payload.find('detailData')
                if i >= 0:
                    j = payload.find('{', i)
                    if j >= 0:
                        k = _close(payload, j, '}', '{')
                        if k >= 0:
                            d = _loads(payload[j:k+1])
                            if d: return d
        except:
            pass
        i = html.find('detailData')
        if i < 0: return None
        j = html.find('{', i)
        if j < 0: return None
        k = _close(html, j, '}', '{')
        if k >= 0:
            return _loads(html[j:k+1])
        return None

    def homeContent(self, filter=False):
        return {"class":[{"type_id":k,"type_name":v} for k,v in CATEGORIES.items()], "filters":{}}

    def homeVideoContent(self):
        self._ensure_supply()
        return {"list":self._items(self._text(self._req(self._pick()+"/")))[:50]}

    def categoryContent(self, tid, pg=1, filter=False, extend=""):
        self._ensure_supply()
        try:
            pn = max(int(str(pg)), 1)
        except:
            pn = 1
        cat = str(tid)
        url = f"{self._pick()}/category/{cat}?page={pn}" if pn > 1 else f"{self._pick()}/category/{cat}"
        html = self._text(self._req(url))
        items = self._items(html)
        has_next = bool(re.search(r'/category/%s\?page=%d["\'\s>]' % (cat, pn+1), html))
        return {"list":items, "page":pn, "pagecount":pn+1 if has_next else pn, "limit":len(items), "total":len(items)*(pn+1 if has_next else pn)}

    def detailContent(self, ids):
        self._ensure_supply()
        vid = str(ids[0] if isinstance(ids, list) else ids)
        url = f"{self._pick()}/detail/{urllib.parse.quote(vid)}"
        html = self._text(self._req(url))
        d = self._detail_data(html)
        if not d:
            return {"list":[]}
        title = d.get("title","")
        cover = d.get("coverImgUrl","")
        if cover and cover.startswith('/'): cover = self._pick() + cover
        year = d.get("year","")
        area = d.get("area","")
        score = d.get("doubanScore","")
        content = d.get("description","")
        eps = d.get("episodes",[]) or []
        if not eps:
            eps = [{"title":title,"id":"","episodeNumber":1}]
        mediaId = d.get("id") or d.get("mediaId") or d.get("media_id") or vid or ""
        if not mediaId:
            _log("detailContent mediaId empty, vid=%s" % vid[:40])
        play_list = []
        for ep in eps:
            ep_name = ep.get("title") or ep.get("name") or f"第{ep.get('episodeNumber','1')}集"
            ep_id = ep.get("id","")
            param = f"{mediaId}|{ep_id}|{ep_name}|proxy"
            play_list.append(f"{ep_name}${param}")
        play_from = ["IFN播放"]
        play_url = ["#".join(play_list)]
        remark = ""
        if score: remark += f"评分:{score} "
        if year: remark += year
        detail = {
            "vod_id": vid, "vod_name": title, "vod_pic": cover,
            "vod_remarks": remark.strip(), "vod_year": year, "vod_area": area,
            "vod_content": content, "vod_play_from": "$$$".join(play_from),
            "vod_play_url": "$$$".join(play_url),
        }
        return {"list":[detail]}

    def playerContent(self, flag, id, vipFlags=None):
        if not id:
            return {"parse":0, "url":"", "header":{}}
        parts = str(id).split("|")
        if len(parts) != 4:
            return {"parse":0, "url":"", "header":{}}
        mediaId, episodeId, title, mode = parts[0], parts[1], parts[2], parts[3]
        if not mediaId:
            _log("playerContent empty mediaId, skip")
            return {"parse":0, "url":"", "header":{}}
        reslo = title if RESLO.match(title) else "1080P"
        tok = self._play_token(mediaId, episodeId, title)
        if not tok:
            return {"parse":0, "url":"", "header":{}}
        url = f"{self._pick()}/api/play/{tok}.m3u8?thirdParty=true&reslo={reslo}"
        return {"parse":0, "url":url, "header":{"User-Agent":UA,"Referer":self._pick()+"/","Origin":self._pick()}}

    def searchContent(self, key, quick, pg=1):
        self._ensure_supply()
        try:
            pn = max(int(str(pg)), 1)
        except:
            pn = 1
        q = urllib.parse.quote(str(key))
        url = f"{self._pick()}/search?q={q}&page={pn}" if pn > 1 else f"{self._pick()}/search?q={q}"
        html = self._text(self._req(url))
        items = self._items(html)
        has_next = bool(re.search(r'/search\?q=[^"\'\s]*page=%d["\'\s>]' % (pn+1), html))
        return {"list":items, "page":pn, "pagecount":pn+1 if has_next else pn, "limit":len(items), "total":len(items)*(pn+1 if has_next else pn)}

    def localProxy(self, param):
        pass

    def getName(self):
        return "IFN影视"

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def destroy(self):
        pass


# ==================== 本地测试 ====================
if __name__ == "__main__":
    import subprocess

    class TestSpider(Spider):
        def _req(self, url, headers=None, method='GET', data=None):
            hd = dict(headers or {}); hd.setdefault('User-Agent', UA)
            cmd = ["curl", "-s", "-L", "-m", "15", "-H", "User-Agent: "+UA]
            for k,v in hd.items():
                if k != 'User-Agent':
                    cmd.extend(["-H", k+": "+v])
            if method != 'GET' and data:
                cmd.extend(["-X", method, "-d", data])
            cmd.append(url)
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            class Fake:
                status_code = 200
                text = r.stdout
            return Fake()

    spider = TestSpider()
    spider.init()

    print("="*60)
    print("IFN影视 TVBox 爬虫 v9 - 测试")
    print("="*60)

    # 1. 分类
    r = spider.homeContent()
    print("\n[1] 首页分类:")
    for c in r['class']:
        print("  %s (id=%s)" % (c['type_name'], c['type_id']))

    # 2. 首页视频
    r = spider.homeVideoContent()
    print("\n[2] 首页视频: %d 条" % len(r['list']))
    for it in r['list'][:3]:
        print("  %s | %s" % (it['vod_name'][:30], it['vod_remarks']))

    # 3. 分类列表
    r = spider.categoryContent('3', 1)
    print("\n[3] 电影分类: %d 条, page=%d/%d" % (len(r['list']), r['page'], r['pagecount']))

    # 4. 搜索
    r = spider.searchContent('特立独行', '')
    print("\n[4] 搜索 '特立独行': %d 条" % len(r['list']))

    # 5. 详情
    if r['list']:
        test_id = r['list'][0]['vod_id']
        r = spider.detailContent([test_id])
        if r.get('list'):
            d = r['list'][0]
            print("\n[5] 详情:")
            print("  标题: %s" % d['vod_name'])
            print("  线路: %s" % d['vod_play_from'])
            eps = d['vod_play_url'].split('$$$')[0].split('#') if d.get('vod_play_url') else []
            print("  集数: %d" % len(eps))

            # 6. 播放
            if eps:
                ep = eps[0]
                url = ep.split('$')[1] if '$' in ep else ep
                parts = url.split('|')
                if len(parts) == 4:
                    print("\n[6] 播放测试:")
                    print("  mediaId=%s episodeId=%s" % (parts[0], parts[1]))
                    r = spider.playerContent('', url)
                    print("  parse=%s url=%s..." % (r.get('parse'), r.get('url','')[:60]))

    print("\n[7] 活跃账户: %d" % len(spider._live_accounts))
    print("[8] 缓存token: %d" % len(spider._token_cache))
    print("done")
