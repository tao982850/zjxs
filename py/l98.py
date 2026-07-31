# coding: utf-8
import requests, json, base64, time
from urllib.parse import unquote, quote, urlparse
from concurrent.futures import ThreadPoolExecutor

class Spider:
    def __init__(self):
        self.siteUrl = 'https://l98.cn'
        self.headers = {'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36','Referer':'https://l98.cn/'}
        self.key = 'source-a45d5761c9'
        self.api = 'tvbox-py://'+self.key
        self.cms = 'https://api.wsyzy.net/api.php/provide/vod'
        self.nf = {'nf71':'71','nf72':'72','nf70':'70'}
        self.alias = {'电视剧':['连续剧','剧集'],'动漫':['动画','国漫']}
        self.cat_default = {'4':'source-37dc8f3871'}
        self.extra = {'yy':('yunyun','recommend','芸芸音乐')}
        self.play_srcs = [{'key':'source-a45d5761c9','name':'瓜子影视'},{'key':'cms','name':'Netflix'},{'key':'source-37dc8f3871','name':'独播库'},{'key':'source-0ad659640c','name':'泥巴影视'}]
        self.feat_srcs = [{'key':'source-a45d5761c9','name':'瓜子影视'},{'key':'source-37dc8f3871','name':'独播库'},{'key':'source-0ad659640c','name':'泥巴影视'},{'key':'jumi','name':'剧迷影视'},{'key':'source-c569666812','name':'星河影视'},{'key':'source-05849e86e9','name':'飞流视频'},{'key':'source-d3d13b6f84','name':'枫叶影院'}]
        self.srcs = [
            {'key':'source-a45d5761c9','name':'瓜子影视'},
            {'key':'source-0ad659640c','name':'泥巴影视'},
            {'key':'source-37dc8f3871','name':'独播库'},
            {'key':'yunyun','name':'芸芸音乐'},
            {'key':'source-ba3403d123','name':'山楂影视'},
            {'key':'source-c6eef9d264','name':'星芽短剧'},
            {'key':'source-b3e87ad824','name':'西饭短剧'},
            {'key':'source-c6be459334','name':'爱影4K'},
            {'key':'wencai','name':'文才影视'},
            {'key':'4kav','name':'4KAV'},
            {'key':'jumi','name':'剧迷影视'},
            {'key':'source-c569666812','name':'星河影视'},
            {'key':'source-05849e86e9','name':'飞流视频'},
            {'key':'source-d3d13b6f84','name':'枫叶影院'}
        ]
        self.cls = {self.key:{'电影':'1','电视剧':'2','动漫':'4','综艺':'3','短剧':'64'}}
        self.hcache = {}
        self.hts = 0
        self.dcache = {}
        self.dts = {}
        self.ccache = {}
        self.nfmap = {}
        self.nft = 0
        self.s = requests.Session()
        self.s.headers.update(self.headers)
        self._warm = False

    def _post(self, path, body, timeout=8):
        if not self._warm:
            try:
                self.s.get(self.siteUrl+'/', timeout=10)
            except Exception:
                pass
            self._warm = True
        try:
            r = self.s.post(self.siteUrl+path, json=body, timeout=timeout)
            d = r.json()
            return d.get('data') if d.get('success') else None
        except Exception:
            return None

    def _cms_cat(self, tid, pg):
        k = str(tid)+'_'+str(int(pg))
        now = time.time()
        if k in self.ccache and now-self.ccache[k][0] < 60:
            return self.ccache[k][1]
        try:
            d = self.s.get(self.cms+'?ac=videolist&t='+str(tid)+'&pg='+str(int(pg)), headers=self.headers, timeout=12).json()
            if isinstance(d, dict) and (d.get('list') or d.get('pagecount')):
                self.ccache[k] = (now, d)
                return d
        except Exception:
            pass
        d = self._post('/api/site/catalog', {'api':self.cms,'tid':str(tid),'page':int(pg)}, timeout=20) or {}
        if d:
            self.ccache[k] = (now, d)
        return d

    def _cms_detail(self, rid):
        try:
            d = self.s.get(self.cms+'?ac=detail&ids='+str(rid), headers=self.headers, timeout=10).json()
            li = (d.get('list') or [{}])[0]
            return li if li.get('vod_play_url') else None
        except Exception:
            return None

    def _nf_list(self, tid, pg):
        if str(tid)=='71':
            p1 = int(pg)*2+3
            with ThreadPoolExecutor(max_workers=2) as ex:
                f1 = ex.submit(self._cms_cat, str(tid), p1)
                f2 = ex.submit(self._cms_cat, str(tid), p1+1)
                d = f1.result(); d2 = f2.result()
            seen, lst = set(), []
            for x in (d.get('list') or [])+(d2.get('list') or []):
                nm = x.get('vod_name','')
                if nm and nm in seen:
                    continue
                seen.add(nm); lst.append(x)
            return lst, max(1, -(-(int(d.get('pagecount',1) or 1)-4)//2))
        d = self._cms_cat(str(tid), int(pg))
        seen, lst = set(), []
        for x in (d.get('list') or []):
            nm = x.get('vod_name','')
            if nm and nm in seen:
                continue
            seen.add(nm); lst.append(x)
        return lst, max(1, int(d.get('pagecount',1) or 1))

    def _nf_map(self):
        now = time.time()
        if self.nfmap and now-self.nft < 600:
            return self.nfmap
        if getattr(self, '_nfb', False):
            t0 = time.time()
            while getattr(self, '_nfb', False) and time.time()-t0 < 15:
                time.sleep(0.5)
            return self.nfmap or {}
        self._nfb = True
        out = {}
        pages = []
        plan = {'6':3,'7':3,'8':3,'9':3,'10':3,'11':4,'12':2,'13':4,'14':8,'15':4,'16':4,'17':3,'18':2,'19':2,'23':1,'71':0,'72':0}
        for tid, n in plan.items():
            try:
                d0 = self._cms_cat(tid, 1)
                pc = int(d0.get('pagecount',1) or 1)
            except Exception:
                pc = 0
            if tid=='71':
                pages += [(tid,p) for p in range(5, pc+1)]
            elif tid=='72':
                pages += [(tid,p) for p in range(1, pc+1)]
            else:
                pages += [(tid,p) for p in range(1, min(n, pc)+1)]
        def fp(tp):
            tid, pg = tp
            try:
                d = self._cms_cat(tid, pg)
                for x in (d.get('list') or []):
                    nm = x.get('vod_name',''); u = x.get('vod_play_url') or ''
                    if nm and u:
                        out[nm] = u
            except Exception:
                pass
        with ThreadPoolExecutor(max_workers=12) as ex:
            list(ex.map(fp, pages))
        self.nfmap, self.nft = out, now
        self._nfb = False
        return out

    def _zb_list(self, pg):
        zbs = [{'key':'source-984a66ab13','name':'央视卫视','tid':'25'}]
        drop = {'熊猫频道','橘汁带你看世界杯','戏曲频道'}
        def fetch(it):
            d = self._post('/api/tvbox/category', {'api':'tvbox-py://'+it['key'],'tid':it['tid'],'page':str(pg),'filter':{},'extend':{}}, timeout=8) or {}
            out = []
            for x in self._lst(d):
                if x.get('vod_name','') in drop:
                    continue
                c = dict(self._card(it,x))
                c['vod_pic'] = 'https://images.weserv.nl/?url=' + x.get('vod_pic','')
                out.append(c)
            return out
        with ThreadPoolExecutor(max_workers=1) as ex:
            res = list(ex.map(fetch, zbs))
        seen, lst = set(), []
        for x in [y for z in res for y in z]:
            nm = x.get('vod_name','')
            if nm and nm in seen:
                continue
            seen.add(nm); lst.append(x)
        return {'list':lst,'page':int(pg),'pagecount':1,'limit':len(lst),'total':len(lst)}

    def _enc(self, key, rid, name=''):
        raw = key+'|'+str(rid)+('|'+quote(name) if name else '')
        return base64.urlsafe_b64encode(raw.encode()).decode().rstrip('=')

    def _dec(self, vid):
        try:
            p = base64.urlsafe_b64decode(vid + '='*(-len(vid)%4)).decode().split('|')
            if len(p) >= 2:
                return p[0], p[1], unquote(p[2]) if len(p) > 2 else ''
        except Exception:
            pass
        return self.key, vid, ''

    def _name(self, key):
        if key == 'cms':
            return 'Netflix'
        for s in self.srcs:
            if s['key']==key:
                return s['name']
        return key

    def _classes(self, key):
        if key == self.key:
            return self.cls.get(key) or {'电影':'1','电视剧':'2','动漫':'4','综艺':'3','短剧':'64'}
        if key not in self.cls:
            d = self._post('/api/tvbox/home', {'api':'tvbox-py://'+key,'filter':True}, timeout=8) or {}
            self.cls[key] = {c['type_name']:str(c['type_id']) for c in (d.get('class') or [])}
        return self.cls[key]

    def _tid(self, key, tid):
        if key == self.key:
            return str(tid)
        t = self._classes(key)
        for n in [x for x,i in self._classes(self.key).items() if i==str(tid)]:
            for c in [n]+self.alias.get(n,[]):
                if c in t:
                    return t[c]
            for c in [n]+self.alias.get(n,[]):
                for k in t:
                    if c in k or k in c:
                        return t[k]
        return None

    def _card(self, s, x):
        return {'vod_id':self._enc(s['key'],x['vod_id'],x.get('vod_name','')),'vod_name':x.get('vod_name',''),'vod_pic':x.get('vod_pic',''),'vod_remarks':x.get('vod_remarks','')}

    def _lst(self, d):
        d = d or {}
        return d.get('list') or ((d.get('data') or {}).get('list') if isinstance(d.get('data'),dict) else None) or []

    def homeContent(self, filter=False):
        now = time.time()
        if self.hcache and now-self.hts < 60:
            return self.hcache
        d = self._post('/api/tvbox/home', {'api':self.api,'filter':True}) or {}
        classes = [{'type_id':'1','type_name':'电影'},{'type_id':'2','type_name':'电视剧'},{'type_id':'4','type_name':'动漫'},{'type_id':'3','type_name':'综艺'},{'type_id':'64','type_name':'短剧'}]
        classes += [{'type_id':'nf71','type_name':'Netflix电影'},{'type_id':'nf72','type_name':'Netflix剧集'},{'type_id':'nf70','type_name':'邵氏电影'},{'type_id':'yy','type_name':'芸芸音乐'}]
        rawf = d.get('filters') or {}
        filters = {}
        for c in classes:
            t = str(c.get('type_id'))
            if t in rawf:
                fl = list(rawf[t])
                filters[c.get('type_name')] = fl
                filters[t] = fl
        yy_flt = [{'key':'type','name':'歌单类型','value':[{'n':'推荐歌单','v':'recommend'},{'n':'排行榜','v':'toplist'},{'n':'热门歌单','v':'hot'},{'n':'热门歌手','v':'artist'}]}]
        filters['芸芸音乐'] = yy_flt
        filters['yy'] = yy_flt
        out = {'class':classes,'filters':filters,'list':[]}
        ThreadPoolExecutor(max_workers=1).submit(self._nf_map)
        self.hcache, self.hts = out, now
        return out

    def categoryContent(self, tid, pg, filter=False, extend={}):
        ext = extend if isinstance(extend,dict) else {}
        fil = filter if isinstance(filter,dict) else {}
        key = ext.get('src') or fil.get('src') or self.key
        tid = str(tid)
        if tid in self.nf:
            lst, pc = self._nf_list(self.nf[tid], pg)
            out = [self._card({'key':'cms'},x) for x in lst]
            return {'list':out,'page':int(pg),'pagecount':pc,'limit':len(out),'total':pc*len(out)}
        if tid in self.extra:
            ek, et, en = self.extra[tid]
            et = fil.get('type') or et
            d = self._post('/api/tvbox/category', {'api':'tvbox-py://'+ek,'tid':et,'page':int(pg),'filter':{},'extend':{}}, timeout=10) or {}
            lst = [self._card({'key':ek},x) for x in self._lst(d)]
            pc = d.get('pagecount') or 1
            return {'list':lst,'page':int(pg),'pagecount':pc,'limit':len(lst),'total':pc*len(lst)}
        if tid == 'zb':
            return self._zb_list(pg)
        if key not in [s['key'] for s in self.play_srcs]:
            key = self.key
        if tid in self.cat_default and key == self.key:
            key = self.cat_default[tid]
        tt = self._tid(key, tid)
        if tt is None:
            return {'list':[],'page':int(pg),'pagecount':1,'limit':0,'total':0}
        d = self._post('/api/tvbox/category', {'api':'tvbox-py://'+key,'tid':tt,'page':int(pg),'filter':{k:v for k,v in fil.items() if k!='src'},'extend':{k:v for k,v in ext.items() if k!='src'}})
        d = d or {}
        lst = [self._card({'key':key},x) for x in self._lst(d)]
        pc = d.get('pagecount') or 1
        return {'list':lst,'page':int(pg),'pagecount':pc,'limit':len(lst),'total':pc*len(lst)}

    def detailContent(self, ids):
        vid = unquote(str(ids).split('$$$')[0])
        now = time.time()
        if vid in self.dcache and now-self.dts[vid] < 600:
            return {'list':[self.dcache[vid]]}
        key, rid, name = self._dec(vid)
        def agg():
            if not name:
                return []
            out = []
            try:
                for nm, u in self._nf_map().items():
                    if nm == name or nm in name or name in nm:
                        out.append(('Netflix', u)); break
            except Exception:
                pass
            def fetch(s):
                if s['key']==key:
                    return None
                try:
                    to = 10 if s['name']=='瓜子影视' else 3
                    r = self._post('/api/search', {'api':'tvbox-py://'+s['key'],'keyword':name,'page':1}, timeout=to)
                    lst = r if isinstance(r,list) else []
                    for item in (lst or [])[:3]:
                        nm = item.get('vod_name','')
                        if nm and (nm==name or name in nm or nm in name):
                            dd = self._post('/api/detail', {'api':'tvbox-py://'+s['key'],'ids':item['vod_id']}, timeout=3)
                            if dd and dd.get('vod_play_url'):
                                return s['name'], dd['vod_play_url']
                    return None
                except Exception:
                    return None
            with ThreadPoolExecutor(max_workers=min(len(self.srcs),10)) as ex:
                return out + [x for x in ex.map(fetch, self.srcs) if x]
        def merge(d, others):
            ps = [s['name'] for s in self.play_srcs]
            pr = [(f,u) for f,u in others if f in ps]
            npr = [(f,u) for f,u in others if f not in ps]
            ordered = [(f,u) for f,u in pr+[(self._name(key), d.get('vod_play_url') or '')]+npr if u]
            ordered = [(f,u) for f,u in ordered if f=='瓜子影视'] + [(f,u) for f,u in ordered if f!='瓜子影视']
            seen, fs, us = set(), [], []
            for f,u in ordered:
                if f not in seen:
                    seen.add(f); fs.append(f); us.append(u)
            d['vod_play_from'] = '$$$'.join(fs)
            d['vod_play_url'] = '$$$'.join(us)
            return d
        if key == 'cms':
            d = self._cms_detail(rid)
            if not d:
                return {'list':[]}
            d = merge(d, agg())
            d['vod_id'] = vid
            self.dcache[vid] = d; self.dts[vid] = now
            return {'list':[d]}
        if key == 'source-984a66ab13':
            d = self._post('/api/detail', {'api':'tvbox-py://'+key,'ids':rid}, timeout=8) or {}
            if not d:
                return {'list':[]}
            d['vod_play_from'] = d.get('vod_play_from') or '央视卫视'
            if d.get('vod_pic'):
                d['vod_pic'] = 'https://images.weserv.nl/?url=' + d['vod_pic']
            d['vod_id'] = vid
            self.dcache[vid] = d; self.dts[vid] = now
            return {'list':[d]}
        def main():
            return self._post('/api/detail', {'api':'tvbox-py://'+key,'ids':rid}, timeout=8) or {}
        with ThreadPoolExecutor(max_workers=2) as ex:
            fd = ex.submit(main)
            fa = ex.submit(agg)
            d = fd.result()
            others = fa.result()
        if not d:
            return {'list':[]}
        d = merge(d, others)
        d['vod_id'] = vid
        self.dcache[vid] = d; self.dts[vid] = now
        return {'list':[d]}

    def searchContent(self, key, quick=False):
        def fetch(s):
            to = 10 if s['name']=='瓜子影视' else 2.5
            d = self._post('/api/search', {'api':'tvbox-py://'+s['key'],'keyword':key,'page':1}, timeout=to)
            lst = d if isinstance(d,list) else []
            return [self._card(s,x) for x in (lst or [])[:3]]
        with ThreadPoolExecutor(max_workers=min(len(self.srcs),10)) as ex:
            res = list(ex.map(fetch, self.srcs))
        return {'list':[x for y in res for x in y][:30]}

    def playerContent(self, flag, id, vipFlags=None, vipUrls=None):
        u = unquote(str(id)).strip()
        if '$' in u:
            u = u.split('$')[-1].strip()
        if u.startswith('http'):
            if 'tvbox_ep_' not in u:
                return {'parse':0,'url':u}
            u = urlparse(u).path
        if not u.startswith('/'):
            u = '/'+u
        key = self.key
        if 'tvbox_ep_' in u:
            try:
                tok = u.split('tvbox_ep_')[-1].split('?')[0]
                key = json.loads(base64.urlsafe_b64decode(tok+'='*(-len(tok)%4)).decode()).get('s') or key
            except Exception:
                pass
        try:
            jurl = 'enc_'+base64.b64encode(quote('tvbox-play://'+key, safe='').encode()).decode()+'_'+format(int(time.time()*1000),'x')
            d = self.s.post(self.siteUrl+'/api/json', json={'jsonUrl':jurl,'movieUrl':u}, headers=self.headers, timeout=15).json()
        except Exception:
            return {'parse':0,'url':''}
        if not (isinstance(d,dict) and d.get('success') and d.get('url')) or d.get('parse') == 1:
            return {'parse':0,'url':''}
        m = d['url']
        return {'parse':0,'url': m if m.startswith('http') else self.siteUrl + (m if m.startswith('/') else '/'+m)}