# -*- coding: utf-8 -*-
# by @嗷呜
# 2026-11-10 电视端修复版
#   现象: 电视版 TVBox 各分类点进去全空白(手机端有弹窗能验证的才正常)。
#   原因: 站点只给"分类列表页/搜索页"加了系统安全验证(/type/N.html、
#         /cupfox-search 都会返回"系统安全验证"页), 原脚本靠 Android 弹窗让
#         用户看验证码 —— 电视端弹窗要么不显示、要么遥控器没法输入数字,
#         于是每次取列表都卡在 q.take() 上, 分类永远是空列表。
#   修法: 1) 分类列表改走站点未被拦截的数据接口 /index.php/ajax/data, 不再
#            需要验证码, 电视端直接出片;
#         2) 详情页与播放页实测不需要验证, 保持原 HTML 解析;
#         3) 验证码弹窗保留给手机端, 但加了超时与"拿不到界面就跳过"的保护,
#            不会再无限期卡住分类请求;
#         4) 顺手修正详情页"导演/主演"取值颠倒、"更新/连载"永远匹配不上的问题。
import json
import random
import re
import sys
import time
from urllib.parse import quote
from pyquery import PyQuery as pq
sys.path.append('..')
from base.spider import Spider


class Spider(Spider):

    def init(self, extend='{}'):
        self._handler = None
        self._toast = None
        self.playList = None
        try:
            from android.os import Handler, Looper
            self._handler = Handler(Looper.getMainLooper())
        except Exception:
            # 非 Android 运行时/精简运行时: 不弹窗也能正常取数
            self._handler = None

    def destroy(self):
        pass

    def getActivity(self):
        try:
            from java.lang import Class
        except Exception:
            return None
        try:
            activityThreadClass = Class.forName("android.app.ActivityThread")
            activityThread = activityThreadClass.getMethod("currentActivityThread", None).invoke(None, None)
            activitiesField = activityThreadClass.getDeclaredField("mActivities")
            activitiesField.setAccessible(True)
            activities = activitiesField.get(activityThread)
            if activities is not None:
                values = activities.values()
                try:
                    records = values.toArray()
                except:
                    records = values.getClass().getMethod("toArray").invoke(values)
                for activityRecord in records:
                    try:
                        activityRecordClass = activityRecord.getClass()
                        pausedField = activityRecordClass.getDeclaredField("paused")
                        pausedField.setAccessible(True)
                        if not pausedField.getBoolean(activityRecord):
                            activityField = activityRecordClass.getDeclaredField("activity")
                            activityField.setAccessible(True)
                            return activityField.get(activityRecord)
                    except:
                        continue
        except Exception:
            return None
        return None

    def execute(self, func):
        import threading
        threading.Thread(target=func).start()

    def run(self, func, delay=0):
        if self._handler is None:
            self.execute(func)
            return
        from java import dynamic_proxy
        from java.lang import Runnable
        import traceback

        def safe():
            try:
                func()
            except Exception as e:
                self.log("run error: " + str(e))
                self.log(traceback.format_exc())
        if not hasattr(self, '_r_class'):
            class R(dynamic_proxy(Runnable)):
                def __init__(self, fn):
                    super().__init__()
                    self.fn = fn

                def run(self):
                    self.fn()
            self._r_class = R
        if delay > 0:
            self._handler.postDelayed(self._r_class(safe), delay)
        else:
            self._handler.post(self._r_class(safe))

    def show(self, text):
        def make():
            if not text:
                return
            try:
                from android.widget import Toast
                activity = self.getActivity()
                if not activity:
                    return
                if self._toast is not None:
                    self._toast.cancel()
                self._toast = Toast.makeText(activity, text, Toast.LENGTH_LONG)
                self._toast.show()
            except Exception as e:
                self.log("show error: " + str(e))
        self.run(make)

    Host = 'https://www.cd-zj.com'

    cookies = {}

    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'referer': f'{Host}/',
        'sec-ch-ua': '"Not/A)Brand";v="8", "Chromium";v="148", "Google Chrome";v="148"',
        'sec-ch-ua-mobile': '?1',
        'sec-ch-ua-platform': '"Android"',
        'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
    }

    playList = None

    def getList(self, doc):
        vs = []
        for v in doc.items():
            img = v('img')
            name = v.attr('title')
            if not name:
                name = img.attr('alt')
            pics = img.attr('data-src') or img.attr('src') or ''
            vs.append({
                'vod_id': v.attr('href'),
                'vod_name': name,
                'vod_pic': (pics or '').replace('&amp;', '&'),
                'vod_remarks': v('.public-list-prb.hide').text()
            })
        return vs

    # ---------- 站点数据接口(分类列表不需要验证码) ----------
    def _apiList(self, tid, pg, limit=20):
        url = f"{self.Host}/index.php/ajax/data?mid=1&tid={tid}&limit={limit}&page={pg}"
        resp = self.fetch(url, headers=self.headers, cookies=self.cookies)
        data = json.loads(resp.text)
        if data.get('code') != 1:
            raise ValueError('api code %s' % data.get('code'))
        out = []
        for x in data.get('list') or []:
            pic = (x.get('vod_pic') or '').replace('&amp;', '&')
            out.append({
                'vod_id': f"/detail/{x.get('vod_id')}.html",
                'vod_name': x.get('vod_name') or '',
                'vod_pic': pic,
                'vod_remarks': x.get('vod_remarks') or '',
            })
        return {
            'list': out,
            'page': pg,
            'pagecount': int(data.get('pagecount') or 1),
            'limit': limit,
            'total': int(data.get('total') or len(out)),
        }

    def show_captcha_dialog(self, img_bytes, callback=None):
        from java import jclass, dynamic_proxy

        def build():
            try:
                activity = self.getActivity()
                if not activity:
                    if callback:
                        callback("")
                    return
                BitmapFactory = jclass("android.graphics.BitmapFactory")
                ImageView = jclass("android.widget.ImageView")
                EditText = jclass("android.widget.EditText")
                LinearLayout = jclass("android.widget.LinearLayout")
                AlertDialog = jclass("android.app.AlertDialog")
                OnClickListener = jclass("android.content.DialogInterface$OnClickListener")
                OnDismissListener = jclass("android.content.DialogInterface$OnDismissListener")
                ViewGroup = jclass("android.view.ViewGroup")
                bitmap = BitmapFactory.decodeByteArray(img_bytes, 0, len(img_bytes))
                img_view = ImageView(activity)
                img_view.setImageBitmap(bitmap)
                img_view.setAdjustViewBounds(True)
                img_view.setScaleType(ImageView.ScaleType.FIT_CENTER)
                img_params = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT
                )
                img_params.bottomMargin = 20
                input_et = EditText(activity)
                input_et.setHint("请输入验证码")
                layout = LinearLayout(activity)
                layout.setOrientation(LinearLayout.VERTICAL)
                layout.setPadding(40, 20, 40, 20)
                layout.addView(img_view, img_params)
                layout.addView(input_et)
                outer = self
                dismissed = [False]

                class PositiveListener(dynamic_proxy(OnClickListener)):
                    def onClick(self, dialog, which):
                        dismissed[0] = True
                        code = str(input_et.getText().toString()).strip()
                        dialog.dismiss()
                        if callback:
                            outer.execute(lambda: callback(code))

                class NegativeListener(dynamic_proxy(OnClickListener)):
                    def onClick(self, dialog, which):
                        dismissed[0] = True
                        dialog.dismiss()
                        if callback:
                            outer.execute(lambda: callback(""))

                class DismissListener(dynamic_proxy(OnDismissListener)):
                    def onDismiss(self, dialog):
                        if not dismissed[0]:
                            dismissed[0] = True
                            if callback:
                                outer.execute(lambda: callback(""))

                dialog = AlertDialog.Builder(activity) \
                    .setTitle("枫叶验证码") \
                    .setView(layout) \
                    .setPositiveButton("确定", PositiveListener()) \
                    .setNegativeButton("关闭", NegativeListener()) \
                    .create()
                dialog.setOnDismissListener(DismissListener())
                dialog.show()
            except Exception as e:
                self.log("show_captcha_dialog error: " + str(e))
                if callback:
                    try:
                        callback("")
                    except Exception:
                        pass
        self.run(build)

    def captcha(self, cookie):
        """手机端走弹窗人工输入; 电视端拿不到界面时最多等 60 秒就放弃,
        不再让分类请求无限期挂住。"""
        if self.getActivity() is None:
            self.log("captcha: 拿不到 Android 界面, 跳过人工验证")
            return False
        img_url = f"{self.Host}/captcha.php?type=code&r={random.random()}"
        resp = self.fetch(img_url, headers=self.headers, cookies=cookie)
        rck = resp.cookies.get_dict()

        from java import jclass
        ArrayBlockingQueue = jclass("java.util.concurrent.ArrayBlockingQueue")
        q = ArrayBlockingQueue(1)
        self.show_captcha_dialog(resp.content, lambda code: q.offer(code))
        code = None
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                code = q.poll()
            except Exception:
                code = None
            if code is not None:
                break
            time.sleep(0.2)
        code = str(code or '').strip()
        if not code:
            self.show("取消验证")
            return False
        post_url = f"{self.Host}/captcha.php?type=verify"
        verify = self.post(post_url, headers=self.headers, data={'check': code}, cookies=rck)
        self.log(f"验证结果: {verify.text}")
        try:
            data = json.loads(verify.text)
            if data.get('code') != 1:
                self.show("验证失败，请刷新重新验证")
                return False
            self.show("验证成功")
            vck = verify.cookies.get_dict()
            vck.update(rck)
            self.cookies = vck
            return True
        except Exception as e:
            self.show("验证异常: " + str(e))
            return False

    def getHtml(self, url):
        resp = self.fetch(url, headers=self.headers, cookies=self.cookies)
        if "系统安全验证" in resp.text:
            if self.captcha(resp.cookies.get_dict()):
                resp = self.fetch(url, headers=self.headers, cookies=self.cookies)
            if "系统安全验证" in resp.text:
                return pq(b"<html></html>")
        return pq(resp.content)

    def homeContent(self, filter):
        doc = self.getHtml(self.Host)
        cls = doc("div.head-more.none.box.size > a")
        classes = [
            {
                "type_id": c.attr("href").replace('.html', ''),
                "type_name": c.text(),
            } for c in cls.items() if c.attr("href") != "/"
        ]
        if not classes:
            classes = self._staticClasses()
        vs = doc("div.flex.wrap.border-box .public-list-exp")
        return {"class": classes, "filters": {}, "list": self.getList(vs)}

    @staticmethod
    def _staticClasses():
        """首页导航取不到时的兜底分类(与站内栏目一致)"""
        return [
            {"type_id": "/type/1", "type_name": "电影"},
            {"type_id": "/type/2", "type_name": "电视剧"},
            {"type_id": "/type/4", "type_name": "动漫"},
            {"type_id": "/type/3", "type_name": "综艺"},
            {"type_id": "/type/5", "type_name": "热门短剧"},
        ]

    def categoryContent(self, tid, pg, filter, extend):
        # /type/N 走数据接口, 不再触发站点验证码, 电视端也能出列表
        m = re.search(r'/type/(\d+)', tid or '')
        if m:
            try:
                return self._apiList(m.group(1), pg)
            except Exception as e:
                self.log("categoryContent api fallback: " + str(e))
        path = f"{tid}/page/{pg}.html"
        doc = self.getHtml(self.Host + path)
        vs = doc("div.list-vod.flex.wrap .public-list-exp")
        if not vs:
            vs = doc("div.public-list-exp")
        return {"list": self.getList(vs)}

    def detailContent(self, ids):
        doc = self.getHtml(self.Host + ids[0])
        vod = {
            'vod_name': doc(".slide-info-title.hide").text(),
            'vod_pic': (doc("img.lazy.lazy1.mask-1").attr("src") or '').replace('&amp;', '&'),
            'vod_content': doc(".text.cor3").text(),
        }
        vs = doc("div.detail-info.rel.flex-auto.wow .slide-info.hide")
        for i in vs.items():
            # 标签写在 <strong> 里, 先取整行文本再拆分, 不能先移除 strong,
            # 否则连"导演/主演"这些键一起被删掉, 永远匹配不上
            txt = (i.text() or '').strip()
            if not txt:
                continue
            if re.match(r'\d{4}-\d{2}-\d{2}', txt):
                vod['vod_year'] = txt[:4]
                continue
            if '：' in txt:
                key, val = txt.split('：', 1)
            elif ':' in txt:
                key, val = txt.split(':', 1)
            else:
                continue
            key, val = key.strip(), val.strip()
            if key == '导演':
                vod['vod_director'] = val
            elif key == '主演':
                vod['vod_actor'] = val
            elif key in ('连载', '更新'):
                vod.setdefault('vod_remarks', val)
        names = list(doc("div.swiper-wrapper .swiper-slide").items())
        urls = list(doc("ul.anthology-list-play.size").items())
        n, p = [], []
        for i, j in enumerate(names):
            j.remove(".badge")
            n.append(j.text() + f"#{i+1}")
            if i >= len(urls):
                continue
            ps = urls[i]('li')
            s = [
                f"{m.text()}${m('a').attr('href')}"
                for m in reversed(list(ps.items()))
            ]
            p.append('#'.join(s))
        vod['vod_play_from'] = '$$$'.join(n)
        vod['vod_play_url'] = '$$$'.join(p)
        return {'list': [vod]}

    def searchContent(self, key, quick, pg="1"):
        url = f"{self.Host}/cupfox-search/-------------.html?wd={quote(key)}"
        doc = self.getHtml(url)
        vs = doc("div.row-right .public-list-exp")
        if not vs:
            vs = doc("div.public-list-exp")
        return {"list": self.getList(vs)}

    def getJx(self, key, path):
        if self.playList is None:
            resp = self.getHtml(self.Host + path).text()
            pattern = r'MacPlayerConfig\.player_list\s*=\s*({.*?}),\s*MacPlayerConfig\.downer_list'
            m = re.search(pattern, resp, re.S)
            self.playList = json.loads(m.group(1)) if m else {}
        return self.playList.get(key) or {}

    def playerContent(self, flag, id, vipFlags):
        try:
            doc = self.getHtml(self.Host + id)
            script = doc("div.player-left .MacPlayer script")
            aj = json.loads(script.eq(0).text().split("=", 1)[-1])
            frmo = self.getJx(aj.get("from"), script.eq(1).attr("src"))
            if frmo.get("ps") == "0":
                return {"parse": 0, "url": aj.get("url")}
            parse = frmo.get("parse")
            resp = self.fetch(parse + aj.get("url"), headers=self.headers)
            token = pq(resp.content)("#player-data").attr("data-te")
            data = self.post(parse.split("?")[0] + "mplayer.php", headers=self.headers,
                             data={"url": aj.get("url"), "token": token}).json()
            if data.get("code") == 200:
                return {"parse": 0, "url": data.get("url")}
            return {"parse": 1, "url": self.Host + id}
        except Exception as e:
            print(e)
            return {"parse": 1, "url": self.Host + id}