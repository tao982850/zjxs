# -*- coding: utf-8 -*-
# 橘汁TV v1.0 橘汁3.0.2.4协议端到端打通落地(TV版3.0.2.3 域名池gdsaj)
# RSA握手+AES安全通道+proto接口; fakePos=3; safeCode32静态; 424教训: publicParams数值字段必须int
import sys,json,time,base64,random,re,threading
from urllib.parse import quote
import requests
sys.path.append('..')
try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def fetch(self, url, headers=None, **kw):
            kw.pop('timeout', None)
            r = requests.get(url, headers=headers, timeout=15, **kw)
            r.encoding = 'utf-8'
            return r
HOSTS = ['https://gdsaj.hzhcbkj.cn']
TXT_URLS = ['https://tv-1349250429.cos.ap-guangzhou.myqcloud.com/tv1.txt',
            'https://tv2-1349250429.cos.ap-chengdu.myqcloud.com/tv2.txt',
            'https://tv3-1349250429.cos.ap-shanghai.myqcloud.com/tv3.txt']
CATS = {'1': '电影', '2': '剧集', '3': '综艺', '4': '动漫', '5': '短剧', '6': '直播'}
TID = {'1': 20, '2': 21, '3': 22, '4': 23, '5': 24, '6': 25}
PUB1_N = 0xabf12cd9863632fabb326b52b4f6df1dd8ae74a56168064814a8ca4a3a25bedc811529de1e4ddbe0f5148e8d0f36932a4be91f419ec9ab4b557cb383d50f08d06d4b588533cf0bd1f3d7aa98eeba43ea6d1ddafaf4f7f529590e6e3b2f4f474413aec8a8bde67e0c87bd8dcdc2fb3042bbf919498fd1f2cb702688a2b648b783
PUB1_E = 65537
SAFE32 = 'SGNWTJHSK05SU3NBYITNB2FJD3FNPT0='
SAFESECRET = 'OC1A06E197EF10CF3F6058CA7A803B5E'
VAPP = '3023'
UA = 'okhttp/4.9.0'
SBOX = [99,124,119,123,242,107,111,197,48,1,103,43,254,215,171,118,202,130,201,125,250,89,71,240,173,212,162,175,156,164,114,192,183,253,147,38,54,63,247,204,52,165,229,241,113,216,49,21,4,199,35,195,24,150,5,154,7,18,128,226,235,39,178,117,9,131,44,26,27,110,90,160,82,59,214,179,41,227,47,132,83,209,0,237,32,252,177,91,106,203,190,57,74,76,88,207,208,239,170,251,67,77,51,133,69,249,2,127,80,60,159,168,81,163,64,143,146,157,56,245,188,182,218,33,16,255,243,210,205,12,19,236,95,151,68,23,196,167,126,61,100,93,25,115,96,129,79,220,34,42,144,136,70,238,184,20,222,94,11,219,224,50,58,10,73,6,36,92,194,211,172,98,145,149,228,121,231,200,55,109,141,213,78,169,108,86,244,234,101,122,174,8,186,120,37,46,28,166,180,198,232,221,116,31,75,189,139,138,112,62,181,102,72,3,246,14,97,53,87,185,134,193,29,158,225,248,152,17,105,217,142,148,155,30,135,233,206,85,40,223,140,161,137,13,191,230,66,104,65,153,45,15,176,84,187,22]
IS = [0]*256
for _i,_v in enumerate(SBOX): IS[_v]=_i
RCON = [1,2,4,8,16,32,64,128,27,54,108,216,171,77]
def _xt(x):
    x <<= 1
    if x & 256: x ^= 0x11b
    return x & 255
def _mul(a, b):
    r = 0
    while b:
        if b & 1: r ^= a
        a = _xt(a); b >>= 1
    return r
def _ke(key):
    nk = len(key) // 4; nr = nk + 6
    w = [list(key[4*i:4*i+4]) for i in range(nk)]
    for i in range(nk, 4 * (nr + 1)):
        t = w[i - 1][:]
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [SBOX[x] for x in t]
            t[0] ^= RCON[i // nk - 1]
        elif nk > 6 and i % nk == 4:
            t = [SBOX[x] for x in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return w
def _sr(s, dec=False):
    for r in range(1, 4):
        row = s[r][:]
        for c in range(4):
            s[r][c] = row[(c - r) % 4] if dec else row[(c + r) % 4]
def _sbx(s, dec=False):
    T = IS if dec else SBOX
    for r in range(4):
        for c in range(4): s[r][c] = T[s[r][c]]
def _mc(s, dec=False):
    for c in range(4):
        a = [s[r][c] for r in range(4)]
        if not dec:
            s[0][c] = _mul(a[0],2) ^ _mul(a[1],3) ^ a[2] ^ a[3]
            s[1][c] = a[0] ^ _mul(a[1],2) ^ _mul(a[2],3) ^ a[3]
            s[2][c] = a[0] ^ a[1] ^ _mul(a[2],2) ^ _mul(a[3],3)
            s[3][c] = _mul(a[0],3) ^ a[1] ^ a[2] ^ _mul(a[3],2)
        else:
            s[0][c] = _mul(a[0],14) ^ _mul(a[1],11) ^ _mul(a[2],13) ^ _mul(a[3],9)
            s[1][c] = _mul(a[0],9) ^ _mul(a[1],14) ^ _mul(a[2],11) ^ _mul(a[3],13)
            s[2][c] = _mul(a[0],13) ^ _mul(a[1],9) ^ _mul(a[2],14) ^ _mul(a[3],11)
            s[3][c] = _mul(a[0],11) ^ _mul(a[1],13) ^ _mul(a[2],9) ^ _mul(a[3],14)
def _blk(b, w, dec=False):
    s = [[b[r + 4*c] for c in range(4)] for r in range(4)]
    nr = len(w) // 4 - 1
    def add(n):
        for r in range(4):
            for c in range(4): s[r][c] ^= w[n * 4 + c][r]
    if not dec:
        add(0)
        for n in range(1, nr): _sbx(s); _sr(s); _mc(s); add(n)
        _sbx(s); _sr(s); add(nr)
    else:
        add(nr)
        for n in range(nr - 1, 0, -1): _sr(s, True); _sbx(s, True); add(n); _mc(s, True)
        _sr(s, True); _sbx(s, True); add(0)
    return bytes(s[r][c] for c in range(4) for r in range(4))
def aes_ecb(key, data, mode=1, strip=True):
    w = _ke(key); out = b''
    if mode:
        pad = 16 - len(data) % 16; data += bytes([pad]) * pad
        for i in range(0, len(data), 16): out += _blk(data[i:i+16], w)
    else:
        for i in range(0, len(data), 16): out += _blk(data[i:i+16], w, True)
        if strip and out and 0 < out[-1] <= 16: out = out[:-out[-1]]
    return out
def _vi(n):
    o = bytearray()
    while True:
        b = n&127; n >>= 7
        if n: o.append(b|128)
        else: o.append(b); break
    return bytes(o)
def _ld(f,s): return _vi(f*8+2)+_vi(len(s))+s
def _vint(f,n): return _vi(f*8)+_vi(n)
def _pd(b):
    o=[]; i=0
    while i < len(b):
        v=0; s=0
        while 1:
            x=b[i]; i+=1; v|=(x&127)<<s; s+=7
            if not x&128: break
        f=v>>3; w=v&7
        if w==0:
            z=0; s=0
            while 1:
                x=b[i]; i+=1; z|=(x&127)<<s; s+=7
                if not x&128: break
            o.append((f,z))
        elif w==2:
            ln=0; s=0
            while 1:
                x=b[i]; i+=1; ln|=(x&127)<<s; s+=7
                if not x&128: break
            o.append((f,b[i:i+ln])); i+=ln
        else: break
    return o
class Spider(Spider):
    def init(self,extend=''):
        self.base = HOSTS[0].rstrip('/')
        self.ua = UA
        self.types = dict(CATS)
        self.filters = {}
        self._n = None; self._e = None; self._t0 = 0
        self._sm = {}
        self._lock = threading.Lock()
        try:
            threading.Thread(target=self._refresh,daemon=True).start()
        except Exception:
            pass
    def _refresh(self):
        for u in TXT_URLS:
            try:
                r = requests.get(u,timeout=4)
                d = r.json()
                if d.get('enabled'):
                    self.base = d['domain'].rstrip('/')
                    break
            except Exception:
                pass
    def _rnd(self,n):
        cs = '1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
        o = ''; u = set()
        while len(o) < n-1:
            c = random.choice(cs)
            if c not in u: o += c; u.add(c)
        return o + '='
    def _rsa_pkcs1(self,n,e,m):
        k = (n.bit_length()+7)//8
        if len(m) > k-11: raise ValueError('msg too long')
        ps = b''
        while len(ps) < k-len(m)-3:
            ps += bytes([random.randrange(1,256)])
        em = b'\x00\x02'+ps+b'\x00'+m
        return pow(int.from_bytes(em,'big'),e,n).to_bytes(k,'big')
    def _pub_ne(self,b64s):
        d = base64.b64decode(b64s)
        ni = d.rfind(b'\x02\x81\x81')
        n = int.from_bytes(d[ni+4:ni+132],'big')
        return n, 65537
    def _sig1(self,m): return base64.b64encode(self._rsa_pkcs1(PUB1_N,PUB1_E,m)).decode()
    def _hd(self,ts,r16,withsig=True):
        p = {'plat':'tv','vOs':'11','vApp':VAPP,'vName':'3.0.2.3','pkg':'com.exxammpea.a1','appName':'橘汁TV',
             'udid':'a'*32,'uuid':'a'*32,'androidID':'a'*16,'chid':'10000','test_timestamp':int(ts),'young':0,
             'timestamp':int(ts),'random_str':r16}
        if withsig and self._n:
            p['sig'] = base64.b64encode(self._rsa_pkcs1(self._n,self._e,(ts+r16+VAPP).encode())).decode()
            z = base64.b64encode(aes_ecb(SAFESECRET.encode(),(ts+r16).encode())).decode()
            p['sig2'] = z[:8]; p['sig3'] = z[8:]
        return {'publicParams':json.dumps(p,separators=(',',':')),'Content-Type':'application/x-protobuf','User-Agent':self.ua,'Accept':'application/x-protobuf'}
    def _hs(self):
        with self._lock:
            self._n = None
            t = str(int(time.time()*1000)); r = self._rnd(16)
            body = _vint(1,int(t)) + _ld(2,self._sig1((t+r).encode()).encode()) + _ld(3,self._rnd(16).encode()) + _ld(4,r.encode()) + _ld(5,self._rnd(16).encode())
            try:
                rq = requests.post(self.base+'/api/v5/find/app/zone',data=body,headers=self._hd(t,r,False),timeout=6)
            except Exception:
                return False
            if rq.status_code != 200: return False
            fields = _pd(rq.content)
            data = next((v for f,v in fields if f==3 and isinstance(v,bytes)),b'')
            if not data: return False
            ss = {}
            for f,v in _pd(data):
                if isinstance(v,bytes): ss[f]=v.decode()
            if len(ss) < 5: return False
            try:
                self._n,self._e = self._pub_ne(ss[1]+ss[2]+ss[4]+ss[5])
                self._t0 = time.time()
                return True
            except Exception:
                return False
    def _call(self,path,par):
        for _ in range(2):
            if not self._n or time.time()-self._t0 > 3600:
                if not self._hs(): return None
            try:
                t = str(int(time.time()*1000)); r16 = self._rnd(16); r8 = self._rnd(8); fake = self._rnd(20)
                plain = par + t
                enc = base64.b64encode(aes_ecb(SAFE32.encode(),plain.encode())).decode()
                s3 = r8 + enc
                body = _ld(1,s3[:20].encode())+_ld(2,s3[20:].encode())+_ld(3,fake.encode())+_vint(4,int(t))+_ld(5,r8.encode())
                rq = requests.post(self.base+path,data=body,headers=self._hd(t,r16),timeout=4)
            except Exception:
                self._n = None; continue
            if rq.status_code == 424:
                self._n = None; continue
            if rq.status_code != 200: return None
            return _pd(rq.content)
        return None
    def _dr(self,flds,fn):
        for f,v in flds:
            if f==fn and isinstance(v,bytes): return v.decode('utf-8','replace')
        return ''
    def _di(self,flds,fn):
        for f,v in flds:
            if f==fn and isinstance(v,int): return v
        return 0
    def _cover(self,cv):
        for f,v in _pd(cv or b''):
            if f==2 and isinstance(v,bytes): return v.decode('utf-8','replace')
        return ''
    def _list_items(self,ar):
        data = next((v for f,v in ar if f==3 and isinstance(v,bytes)),b'') if ar else b''
        out = []
        for f,v in _pd(data):
            if f==1 and isinstance(v,bytes):
                d = _pd(v)
                out.append({'vod_id':str(self._di(d,3)),'vod_name':self._dr(d,5),'vod_pic':self._cover(next((w for g,w in d if g==2),None)),
                            'vod_remarks':self._dr(d,13) or (str(self._di(d,14)) if self._di(d,14) else '')})
        return out
    def homeContent(self,filter=False):
        r = {'class':[{'type_id':k,'type_name':v} for k,v in self.types.items()]}
        if filter: r['filters'] = {}
        r['list'] = self.homeVideoContent().get('list',[])
        return r
    def homeVideoContent(self):
        try:
            t = str(int(time.time()*1000)); r16 = self._rnd(16)
            if not self._n or time.time()-self._t0 > 3600:
                if not self._hs(): return {'list':[]}
            hd = dict(self._hd(t,r16),Accept='application/json')
            rq = requests.get(self.base+'/api/ex/v3/security/tag/list',headers=hd,timeout=6)
            if rq.status_code != 200: return {'list':[]}
            enc = rq.json().get('data','')
            if not enc: return {'list':[]}
            b1 = base64.b64decode(enc)
            m1 = aes_ecb(SAFE32.encode(),b1,0)
            b2 = base64.b64decode(m1)
            m2 = aes_ecb(SAFESECRET.encode(),b2,0)
            j = json.loads(m2)
            items = []
            def walk(o):
                if isinstance(o,dict):
                    vs = o.get('vodList')
                    if isinstance(vs,list):
                        for v in vs:
                            if not isinstance(v,dict): continue
                            cimg = v.get('coverImage') or {}
                            items.append({'vod_id':str(v.get('id','')),'vod_name':v.get('name',''),
                                          'vod_pic':cimg.get('path','') if isinstance(cimg,dict) else (v.get('pic') or ''),
                                          'vod_remarks':v.get('remark','') or (v.get('episodeText') or '')})
                    if isinstance(o.get('carousels'),list):
                        for c in o['carousels']:
                            if isinstance(c,dict) and str(c.get('link','')).startswith('/navigate/video?id='):
                                items.append({'vod_id':str(c['link']).rsplit('=',1)[-1],'vod_name':c.get('title',''),
                                              'vod_pic':c.get('cover','') or c.get('picLink',''),'vod_remarks':''})
                    for v in o.values(): walk(v)
                elif isinstance(o,list):
                    for v in o: walk(v)
            walk(j)
            seen = set(); uniq = []
            for it in items:
                if it['vod_id'] and it['vod_id'] not in seen:
                    seen.add(it['vod_id']); uniq.append(it)
                    if len(uniq) >= 80: break
            return {'list':uniq}
        except Exception:
            return {'list':[]}
    def categoryContent(self,tid,pg=1,filter=False,extend=''):
        try: pn = max(int(str(pg)),1)
        except Exception: pn = 1
        cid = str(tid).split('|')[0]
        tidn = TID.get(cid,'20')
        ar = self._call('/api/proto/v5/drama/category','typeId1=%d&page=%d&pagesize=20'%(tidn,pn))
        items = self._list_items(ar) if ar else []
        return {'page':pn,'pagecount':100,'limit':20,'total':len(items),'list':items}
    def detailContent(self,ids,quick='1'):
        vid = str(ids[0] if isinstance(ids,list) else ids or '')
        m = re.search(r'(\d+)',vid); vid = m.group(1) if m else ''
        if not vid: return {'list':[]}
        ar = self._call('/api/proto/v5/drama/getDetail','id='+vid)
        if not ar: return {'list':[]}
        data = next((v for f,v in ar if f==3 and isinstance(v,bytes)),b'')
        d = _pd(data)
        name = self._dr(d,9) or vid
        pic = self._cover(next((w for g,w in d if g==2),None))
        year = self._di(d,18); year = str(year) if year else ''
        dct = {'vod_id':vid,'vod_name':name,'vod_pic':pic,'vod_year':year,
               'vod_area':self._dr(d,1),'vod_class':self._dr(d,13),'vod_director':self._dr(d,12),
               'vod_actor':self._dr(d,25),'vod_content':self._dr(d,7) or self._dr(d,6),
               'vod_remarks':self._dr(d,26),'vod_play_from':'','vod_play_url':''}
        grp = {}
        order = []
        for f,v in d:
            if f==29 and isinstance(v,bytes):
                vd = _pd(v)
                src = self._dr(vd,9); scn = self._dr(vd,10) or src
                ep = self._di(vd,13); title = self._dr(vd,2) or str(ep)
                path = self._dr(vd,4)
                if not path: continue
                if src not in grp:
                    grp[src] = {'scn':scn,'eps':{}}; order.append(src)
                if ep not in grp[src]['eps']:
                    grp[src]['eps'][ep] = title.replace('#','-').replace('$','|')+'$'+path
        if order:
            keep = [o for o in order if o=='KZNB']+[o for o in order if o!='KZNB']
            shown = []; used = set()
            for o in keep:
                n = grp[o].get('scn') or o
                if n in used: n = o
                used.add(n); self._sm[n] = o; shown.append(n)
            dct['vod_play_from'] = '$$$'.join(shown)
            dct['vod_play_url'] = '$$$'.join('#'.join(grp[o]['eps'][k] for k in sorted(grp[o]['eps'].keys())) for o in keep)
        return {'list':[dct]}
    def searchContent(self,key,quick=False,pg='1'):
        try: pn = max(int(str(pg)),1)
        except Exception: pn = 1
        ar = self._call('/api/proto/v5/drama/search','searchKeys=%s&page=%d&pagesize=20'%(key,pn))
        return {'list':self._list_items(ar) if ar else [],'page':pn}
    def _url1(self,src,path):
        if not self._n or time.time()-self._t0 > 3600:
            self._hs()
        ar = self._call('/api/proto/v5/videoUsableUrl','vodPlayFrom=%s&playUrl=%s'%(quote(src),quote(path)))
        if not ar: return ''
        data = next((v for f,v in ar if f==3 and isinstance(v,bytes)),b'')
        u = ''
        for f,v in _pd(data):
            if f==1 and isinstance(v,bytes): u = v.decode('utf-8','replace')
        return u
    def _web(self,u):
        l = (u or '').lower().split('?',1)[0]
        return l.endswith('.html') or l.endswith('.htm') or ('/cover/' in l and '.qq.com' in l) or ('/v_show/' in l and '.youku.com' in l)
    def playerContent(self,flag,id,vipFlags=None):
        src = self._sm.get(str(flag), str(flag)); path = str(id)
        if '://' in path and self._web(path):
            u = self._url1(src,path)
            if u and not self._web(u) and u.startswith('http'):
                return {'parse':0,'url':u}
            return {'parse':1,'url':path}
        u = self._url1(src,path) if src else ''
        if not u and '://' in path:
            return {'parse':0,'url':path}
        if not u: return {'parse':0,'url':''}
        if not u.startswith('http'):
            return {'parse':1,'url':u}
        if 'zy.m3u8' in u or '/zb/' in u:
            try:
                r = requests.get(u,headers={'User-Agent':self.ua},timeout=5,allow_redirects=False)
                if r.status_code in (301,302,303,307):
                    loc = r.headers.get('Location','')
                    if loc.startswith('http'): u = loc
            except Exception:
                pass
        return {'parse':0,'url':u}
