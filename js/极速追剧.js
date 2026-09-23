/*
 * 极速追剧 (jisuzhuiju.com) —— drpy-node 源
 *
 * 建源依据（2026-09-22 实测）：
 *   · 纯 HTML 站（无苹果CMS 的 index.php/api）：首页 5 个分区（精选推荐/热播电视剧/热播电影/热播动漫/热播综艺）
 *   · 列表卡片统一结构：div.vod-card > a[/detail/<id>.html] + img.src + p.vod-title(名称) + p.vod-subtitle(主演)
 *   · 一级分类：/type/dianshiju.html、/type/dianying.html、/type/dongman.html、/type/zongyi.html
 *     **站点无分页**（?page=2 被忽略，/type/xxx-2.html 是另一份聚合页）→ 第 2 页起返回空，避免重复刷条
 *   · 详情 /detail/<id>.html：h1=名称、og:image=封面、meta description=简介、
 *     span.meta-value 依次为 主演/导演/地区/语言/年份/更新/备注
 *   · 播放线路：div.source-tabs>button（名称）+ div.source-panel>a.episode-btn（/vodplay/<id>-<from>-<n>.html）
 *     实测 578 有 4 条线路：腾讯官方线路(qq 34集) / 自建线路(jsm3u8 34集) / 普通线路二(bfzym3u8 34集) / 普通线路一(co 32集)
 *   · 取流：播放页 HTML 里没有 m3u8，真实地址由接口给 ——
 *     GET /api/play-url?vodId=<id>&playFrom=<from>&index=<n> → {"mode":"native","code":200,"url":"<m3u8>"}
 *     实测三条线路直链可播（#EXTM3U 正常，无需 Referer；"co" 线路偶发 code:500 无地址 → 走兜底）
 *   · ⚠ 播放端：直链 CDN（fengbao12 / vv.jisuzyv / cibn-edge-5g.1ljx）**只认国内 IP**
 *     —— 国外服务器 curl 取到的是 HTML 反爬页/空（2026-09-22 VPS 实测），
 *     国内客户端直连正常（#EXTM3U ✓）。所以 lazy 保持 parse:0 把直链交给播放器，
 *     **不要开"服务器代{}-理播放"**（那会走美国出口 → 403/空白）。
 *   · 站点本体美国可直连（不需要 cz-relay）
 *   · 搜索：/search?wd=<关键词>（无需 POST）
 *
 * 接口自测：
 *   /api/极速追剧?ac=list&t=dianshiju&pg=1
 *   /api/极速追剧?ac=detail&ids=578
 *   /api/极速追剧?wd=交锋&pg=1
 *   /api/极速追剧?play=/vodplay/578-bfzym3u8-1.html&flag=普通线路二
 *
 * 2026-09-22 建源 by Hermes
 */

const HOST = 'https://jisuzhuiju.com';
const SRC = '极速追剧';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

const HEADERS = {
    'User-Agent': UA,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Referer': HOST + '/',
};

// 一级分类（取自站点导航）
const CLASSES = [
    ['dianshiju', '电视剧'],
    ['dianying', '电影'],
    ['dongman', '动漫'],
    ['zongyi', '综艺'],
];

// 线路键 → 站点显示名（接口用的键，详情页标签用的名字）
const SOURCE_NAMES = {
    qq: '腾讯官方线路',
    jsm3u8: '自建线路',
    bfzym3u8: '普通线路二',
    co: '普通线路一',
};

function fixUrl(u) {
    u = String(u == null ? '' : u).trim();
    if (!u) return '';
    if (u.startsWith('//')) return 'https:' + u;
    if (/^https?:\/\//i.test(u)) return u;
    return HOST + (u.startsWith('/') ? '' : '/') + u;
}

function stripTags(s) {
    return String(s == null ? '' : s).replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim();
}

function idOf(href) {
    const m = String(href == null ? '' : href).match(/\/detail\/(\d+)\.html/);
    return m ? m[1] : '';
}

/** 播放页地址 → [vodId, playFrom, index] */
function epOf(href) {
    const m = String(href == null ? '' : href).match(/\/vodplay\/(\d+)-([A-Za-z0-9_]+)-(\d+)\.html/);
    return m ? [m[1], m[2], m[3]] : null;
}

/** 取页（引擎里 request 实测返回空，改用本引擎已验证可用的 axios；失败回退 request）
 *  —— 2026-09-22 实测：同一引擎下 axios 正常、request 返回 len=0 */
async function getHtml(url) {
    for (let i = 0; i < 2; i++) {
        try {
            const r = await axios({
                url: url,
                headers: HEADERS,
                timeout: 15000,
                responseType: 'text',
            });
            const d = r && r.data;
            const t = (typeof d === 'string') ? d : (d ? JSON.stringify(d) : '');
            if (t && t.length > 200) return t;
            log('取页内容过短(' + url + '): len=' + (t ? t.length : 0));
        } catch (e) {
            log('取页失败(' + url + '): ' + ((e && e.message) || e));
            if (i === 1) {
                try { return (await request(url, { headers: HEADERS, timeout: 15000 })) || ''; } catch (e2) { }
            }
        }
        await sleep(300);
    }
    return '';
}

/** 卡片里取详情链接：pdfh 优先，兜底在节点 HTML 里正则（站点结构：<a href="/detail/N.html"><div class="vod-card">） */
function hrefOf(node) {
    try { const h = pdfh(node, 'a&&href'); if (h) return h; } catch (e) { }
    const m = String(node == null ? '' : node).match(/href="([^"]*\/detail\/\d+\.html)"/);
    return m ? m[1] : '';
}

/** 列表卡片解析（首页 / 一级 / 搜索 通用）
 *  注意：站点是 <a href="/detail/N.html"><div class="vod-card">…</div></a>，
 *  id 在卡片**外层**的 a 上，所以按 a 选（div.vod-card a 是 0 个）——2026-09-22 实测 */
function parseList(html) {
    const out = [], seen = {};
    let items = [], used = '';
    for (const r of ['a[href*="/detail/"]', 'a.text-decoration-none', 'div.vod-card']) {
        try { items = pdfa(html, r) || []; } catch (e) { items = []; }
        if (items.length) { used = r; break; }
    }
    if (!items.length) log('列表规则未命中（尝试过 a[href*="/detail/"] / a.text-decoration-none / div.vod-card）');
    for (const it of items) {
        try {
            const id = idOf(hrefOf(it));
            if (!id || seen[id]) continue;
            const name = stripTags(pdfh(it, '.vod-title&&Text') || pdfh(it, 'img&&alt') || pdfh(it, 'a&&title'))
                .replace(/(封面|海报)图片$/, '');
            if (!name) continue;
            const pic = pdfh(it, 'img&&data-src') || pdfh(it, 'img&&src') || '';
            const remarks = stripTags(pdfh(it, '.vod-subtitle&&Text'));
            seen[id] = 1;
            out.push({ vod_id: id, vod_name: name, vod_pic: fixUrl(pic), vod_remarks: remarks });
        } catch (e) { /* 单条异常忽略 */ }
    }
    if (used) log('列表规则生效<' + used + '>：' + out.length + ' 条');
    return out;
}

var rule = {
    类型: '影视',
    title: SRC,
    desc: '极速追剧 jisuzhuiju.com 纯 js 源（/api/play-url 取 m3u8 直链）',
    host: HOST,
    homeUrl: '/',
    url: '/type/fyclass.html',
    detailUrl: '/detail/fyid.html',
    searchUrl: '/search?wd=**',
    searchable: 2,
    quickSearch: 1,
    filterable: 0,
    timeout: 15000,
    play_parse: true,
    headers: HEADERS,

    class_parse: async function () {
        return { class: CLASSES.map(function (c) { return { type_id: c[0], type_name: c[1] }; }) };
    },

    推荐: async function () {
        const html = await getHtml(HOST + '/');
        return parseList(html).slice(0, 60);
    },

    一级: async function (tid, pg, filter, extend) {
        pg = Number(pg) || 1;
        // 站点没有分页控件（?page=N 无效）→ 第 2 页起直接返回空
        if (pg > 1) return [];
        const tid2 = (extend && extend.class) || tid || 'dianshiju';
        const html = await getHtml(HOST + '/type/' + tid2 + '.html');
        return parseList(html);
    },

    二级: async function (ids) {
        const id = Array.isArray(ids) ? ids[0] : ids;
        const html = await getHtml(HOST + '/detail/' + id + '.html');
        const vod = {
            vod_id: String(id),
            vod_name: '',
            vod_pic: '',
            vod_content: '',
            vod_remarks: '',
            vod_play_from: SRC,
            vod_play_url: '',
        };
        try {
            vod.vod_name = stripTags(pdfh(html, 'h1&&Text'));
            vod.vod_pic = fixUrl(pdfh(html, 'meta[property="og:image"]&&content') || pdfh(html, 'div.detail-poster-wrapper>img&&src'));
            vod.vod_content = stripTags(pdfh(html, 'meta[name="description"]&&content'));
            const metas = [];
            for (const s of (pdfa(html, 'span.meta-value') || [])) metas.push(stripTags(pdfh(s, 'span&&Text') || String(s)));
            // 详情页顺序：主演 / 导演 / 地区 / 语言 / 年份 / 更新 / 备注
            if (metas[0]) vod.vod_actor = metas[0];
            if (metas[1]) vod.vod_director = metas[1];
            if (metas[2]) vod.vod_area = metas[2];
            if (metas[4]) vod.vod_year = metas[4];
            if (metas[5]) vod.vod_remarks = metas[5];
            if (metas[6]) vod.vod_remarks = metas[6] === '' ? vod.vod_remarks : metas[6];
        } catch (e) {
            log('二级字段解析异常: ' + ((e && e.message) || e));
        }

        // 播放线路：标签 + 分集面板一一对应
        try {
            const tabs = pdfa(html, 'div.source-tabs>button') || [];
            const panels = pdfa(html, 'div.source-panel') || [];
            const froms = [], urls = [];
            for (let i = 0; i < panels.length; i++) {
                const name = stripTags(pdfh(tabs[i] || '', 'button&&Text')) || ('线路' + (i + 1));
                const eps = [];
                for (const a of (pdfa(panels[i], 'a.episode-btn') || [])) {
                    const href = pdfh(a, 'a&&href') || String(a);
                    const ep = epOf(href);
                    if (!ep) continue;
                    const text = stripTags(pdfh(a, 'a&&Text')) || ('第' + (eps.length + 1) + '集');
                    eps.push(text + '$' + fixUrl(href));
                }
                if (eps.length) { froms.push(name); urls.push(eps.join('#')); }
            }
            if (urls.length) {
                vod.vod_play_from = froms.join('$$$');
                vod.vod_play_url = urls.join('$$$');
            } else {
                log('未解析到播放线路: ' + HOST + '/detail/' + id + '.html');
            }
        } catch (e) {
            log('播放线路解析异常: ' + ((e && e.message) || e));
        }
        return vod;
    },

    搜索: async function (wd, quick, pg) {
        let kw = wd || '';
        if (!kw && this.input) {
            const m = String(this.input).match(/[?&]wd=([^&]*)/);
            if (m) { try { kw = decodeURIComponent(m[1]); } catch (e) { kw = m[1]; } }
        }
        const html = await getHtml(HOST + '/search?wd=' + encodeURIComponent(kw));
        return parseList(html).slice(0, 40);
    },

    lazy: async function (flag, id) {
        const raw = String(id == null ? '' : id);
        if (/^https?:\/\//i.test(raw) && !/jisuzhuiju\.com\/vodplay\//i.test(raw)) return { parse: 0, url: raw };
        const ep = epOf(raw);
        if (!ep) {
            // 不是播放页地址：交给客户端内置浏览器嗅探
            return { parse: 1, url: fixUrl(raw) };
        }
        const pageUrl = HOST + '/vodplay/' + ep[0] + '-' + ep[1] + '-' + ep[2] + '.html';
        const api = HOST + '/api/play-url?vodId=' + encodeURIComponent(ep[0])
            + '&playFrom=' + encodeURIComponent(ep[1]) + '&index=' + encodeURIComponent(ep[2]);
        try {
            const r = await axios({
                url: api,
                headers: Object.assign({}, HEADERS, {
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'application/json, text/plain, */*',
                    'Referer': pageUrl,
                }),
                timeout: 15000,
                responseType: 'text',
            });
            const d = r && r.data;
            const txt = (typeof d === 'string') ? d : (d ? JSON.stringify(d) : '');
            const j = JSON.parse(String(txt));
            if (j && j.code === 200 && j.url) {
                log('解析到直链<' + (SOURCE_NAMES[ep[1]] || ep[1]) + ' 第' + ep[2] + '集>: ' + String(j.url).slice(0, 80));
                return { parse: 0, url: j.url, header: { 'User-Agent': UA, 'Referer': HOST + '/' } };
            }
            log('play-url 无地址(' + api + '): ' + String(txt).slice(0, 120));
        } catch (e) {
            log('play-url 异常(' + api + '): ' + ((e && e.message) || e));
        }
        // 兜底：把播放页交给客户端嗅探
        return { parse: 1, url: pageUrl };
    },
};
